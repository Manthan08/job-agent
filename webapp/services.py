"""Application service layer for the FastAPI/React workbench (AI-owned plumbing).

This is the ONLY place the UI talks to the engine. It wraps the existing phase
functions + repositories so the HTTP API stays a thin adapter. Nothing here is
interview-worthy AI code - the chains/prompts/RAG live in the phase packages and
were user-written; this module only orchestrates and reads/writes rows.

Pipeline recap (all already built):
    parse/profile -> ResumeDetails        (Phase 1)
    paste/URL     -> JobDetails           (Phase 2)
    score         -> JobApplications      (Phase 3)
    tailor        -> tailored PDF + link  (Phase 4.1)
    prep (RAG)    -> PreparationMaterials (Phase 4.2)
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

from models.jobs import JobDetailsModel
from models.keyword_coverage import KeywordCoverageReport
from models.match import MatchResult
from models.preparation import InterviewPrepPack
from models.tailored import TailoredResumeModel

from phase1_parse.parse_resume import extract_pdf_text, parse_resume_text
from phase3_score.score_match import (
    resume_to_text,
    job_to_text,
    score_resume_against_job,
)
from phase4_tailor.tailor_resume import tailor_resume_for_job
from phase4_tailor.render_pdf import render_tailored_pdf
from phase4_tailor.save_tailored import save_tailored_resume
from phase4_tailor.keyword_coverage import analyze_keyword_coverage, ats_coverage_score
from phase4_prep.generate_prep import generate_prep_for_job

from db.resume_repository import (
    get_resume_by_id,
    save_resume_to_db,
    save_tailored_resume_link,
)
from db.job_repository import get_job_by_id, save_job_to_db
from db.application_repository import save_application_to_db
from db.application_repository import ensure_application_score_detail_columns
from db.preparation_repository import get_application_id, save_prep_to_db
from db.public_safety import ensure_public_safety_schema as _ensure_public_safety_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "job-tracker.db"
RESUMES_DIR = REPO_ROOT / "data" / "resumes"
PROFILES_DIR = REPO_ROOT / "data" / "profiles"
TAILORED_OUTPUT_DIR = REPO_ROOT / "data" / "tailored"
MAX_PDF_UPLOAD_BYTES = int(os.getenv("MAX_PDF_UPLOAD_BYTES", "5000000"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "8"))
MAX_PDF_TEXT_CHARS = int(os.getenv("MAX_PDF_TEXT_CHARS", "80000"))
MAX_PROFILE_TEXT_CHARS = int(os.getenv("MAX_PROFILE_TEXT_CHARS", "12000"))
MAX_JOB_DESCRIPTION_CHARS = int(os.getenv("MAX_JOB_DESCRIPTION_CHARS", "30000"))
MAX_COACH_MESSAGE_CHARS = int(os.getenv("MAX_COACH_MESSAGE_CHARS", "800"))
PREP_PACK_DISABLED_MESSAGE = (
    "Prep Pack is disabled for public-safe mode because the current RAG story "
    "bank is single-tenant. Re-enable only after adding per-user story-bank "
    "isolation."
)
ANONYMOUS_SESSION_COOKIE = "resume_buddy_sid"
ANONYMOUS_SESSION_RETENTION_DAYS = int(
    os.getenv("ANON_SESSION_RETENTION_DAYS", "14")
)
ANON_DAILY_RESUME_LIMIT = int(os.getenv("ANON_DAILY_RESUME_LIMIT", "3"))
ANON_DAILY_SCORE_LIMIT = int(os.getenv("ANON_DAILY_SCORE_LIMIT", "10"))
ANON_DAILY_TAILOR_LIMIT = int(os.getenv("ANON_DAILY_TAILOR_LIMIT", "3"))
ANON_DAILY_COACH_LIMIT = int(os.getenv("ANON_DAILY_COACH_LIMIT", "30"))
ANON_DAILY_JOB_SAVE_LIMIT = int(os.getenv("ANON_DAILY_JOB_SAVE_LIMIT", "20"))
ANON_SESSION_RATE_LIMIT_PER_MINUTE = int(
    os.getenv("ANON_SESSION_RATE_LIMIT_PER_MINUTE", "20")
)
ANON_IP_RATE_LIMIT_PER_MINUTE = int(
    os.getenv("ANON_IP_RATE_LIMIT_PER_MINUTE", "60")
)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_LAST_CLEANUP_AT = 0.0


class TailorRunResult(NamedTuple):
    tailored: TailoredResumeModel
    pdf_path: Path
    keyword_report: KeywordCoverageReport
    ats_coverage_score: int


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return slug or "untitled"


def _require_within_limit(label: str, value: str, limit: int) -> None:
    if len(value or "") > limit:
        raise ValueError(f"{label} is too long. Limit is {limit} characters.")


def _validate_pdf_upload(file_bytes: bytes, filename: str) -> None:
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Upload a PDF resume file.")
    if len(file_bytes) > MAX_PDF_UPLOAD_BYTES:
        raise ValueError(
            f"Uploaded PDF is too large. Limit is {MAX_PDF_UPLOAD_BYTES} bytes."
        )
    if not file_bytes[:1024].lstrip().startswith(b"%PDF-"):
        raise ValueError("Upload a valid PDF resume file.")


def _validate_workday_url(page_url: str) -> None:
    parts = urlsplit((page_url or "").strip())
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]

    if parts.scheme != "https" or not host.endswith(".myworkdayjobs.com"):
        raise ValueError(
            "Use a supported HTTPS career/job posting URL, or paste the job "
            "description if this site cannot be imported."
        )
    if "job" not in segments:
        raise ValueError("Workday URL must point to a specific job posting.")


def _session_hash(anonymous_session_id: str) -> str:
    return hashlib.sha256(anonymous_session_id.encode("utf-8")).hexdigest()[:16]


def _session_dir(base: Path, anonymous_session_id: str | None) -> Path:
    if not anonymous_session_id:
        return base
    return base / _session_hash(anonymous_session_id)


def _session_scoped_job_url(job_url: str, anonymous_session_id: str | None) -> str:
    """Keep JobDetails.JobUrl unique per anonymous session.

    The existing schema has a global UNIQUE(JobUrl). For the no-login public MVP,
    two users may paste/import the same job. We suffix the stored URL with a
    non-secret session hash so each anonymous tenant gets its own row.
    """
    if not anonymous_session_id:
        return job_url
    suffix = f"anon-{_session_hash(anonymous_session_id)}"
    if job_url.endswith(suffix):
        return job_url
    base_url = job_url.split("#", 1)[0]
    return f"{base_url}#{suffix}"


def new_anonymous_session_id() -> str:
    """Generate an opaque no-login tenant id for one browser."""
    return secrets.token_urlsafe(32)


def is_valid_anonymous_session_id(session_id: str | None) -> bool:
    return bool(session_id and _SESSION_ID_RE.fullmatch(session_id))


def hash_ip_address(ip_address: str | None) -> str | None:
    """Hash IPs for abuse controls without storing raw network addresses."""
    if not ip_address:
        return None
    salt = os.getenv("ANON_IP_HASH_SALT", "resume-buddy-dev-salt")
    return hashlib.sha256(f"{salt}:{ip_address}".encode("utf-8")).hexdigest()


def ensure_public_safety_schema() -> None:
    with _connect() as conn:
        _ensure_public_safety_schema(conn)
        conn.commit()


def _ensure_public_safety_schema_on(conn: sqlite3.Connection) -> None:
    _ensure_public_safety_schema(conn)


def ensure_anonymous_session(session_id: str) -> None:
    """Create or refresh the anonymous tenant row."""
    if not is_valid_anonymous_session_id(session_id):
        raise ValueError("Invalid anonymous session id.")

    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        conn.execute(
            """
            INSERT INTO AnonymousSessions (Id, CreatedAt, LastSeenAt)
            VALUES (?, datetime('now'), datetime('now'))
            ON CONFLICT(Id) DO UPDATE SET LastSeenAt = datetime('now');
            """,
            (session_id,),
        )
        conn.commit()

    _maybe_cleanup_expired_anonymous_data()


def _daily_quota_for(event_type: str) -> int | None:
    return {
        "resume_upload": ANON_DAILY_RESUME_LIMIT,
        "score": ANON_DAILY_SCORE_LIMIT,
        "tailor": ANON_DAILY_TAILOR_LIMIT,
        "coach": ANON_DAILY_COACH_LIMIT,
        "job_save": ANON_DAILY_JOB_SAVE_LIMIT,
        "job_import": ANON_DAILY_JOB_SAVE_LIMIT,
    }.get(event_type)


def record_guarded_usage(
    anonymous_session_id: str,
    event_type: str,
    ip_hash: str | None,
    *,
    estimated_cost_usd: float = 0.0,
    metadata: dict | None = None,
    daily_limit: int | None = None,
    session_rate_limit: int | None = None,
    ip_rate_limit: int | None = None,
) -> None:
    """Enforce free-tier quotas/rates and record a metadata-only usage event."""
    if not is_valid_anonymous_session_id(anonymous_session_id):
        raise ValueError("Invalid anonymous session id.")

    effective_daily_limit = (
        _daily_quota_for(event_type) if daily_limit is None else daily_limit
    )
    effective_session_rate = (
        ANON_SESSION_RATE_LIMIT_PER_MINUTE
        if session_rate_limit is None
        else session_rate_limit
    )
    effective_ip_rate = (
        ANON_IP_RATE_LIMIT_PER_MINUTE if ip_rate_limit is None else ip_rate_limit
    )

    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)

        if effective_daily_limit is not None:
            used_today = conn.execute(
                """
                SELECT COUNT(*)
                FROM UsageEvents
                WHERE AnonymousSessionId = ?
                  AND EventType = ?
                  AND date(CreatedAt) = date('now');
                """,
                (anonymous_session_id, event_type),
            ).fetchone()[0]
            if used_today >= effective_daily_limit:
                raise ValueError(
                    f"Daily free limit reached for {event_type}. "
                    "Try again tomorrow."
                )

        session_recent = conn.execute(
            """
            SELECT COUNT(*)
            FROM UsageEvents
            WHERE AnonymousSessionId = ?
              AND CreatedAt >= datetime('now', '-60 seconds');
            """,
            (anonymous_session_id,),
        ).fetchone()[0]
        if session_recent >= effective_session_rate:
            raise ValueError("Too many requests. Please wait a minute and try again.")

        if ip_hash:
            ip_recent = conn.execute(
                """
                SELECT COUNT(*)
                FROM UsageEvents
                WHERE IpHash = ?
                  AND CreatedAt >= datetime('now', '-60 seconds');
                """,
                (ip_hash,),
            ).fetchone()[0]
            if ip_recent >= effective_ip_rate:
                raise ValueError("Too many requests. Please wait a minute and try again.")

        conn.execute(
            """
            INSERT INTO UsageEvents
                (AnonymousSessionId, EventType, IpHash, EstimatedCostUsd, Metadata)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                anonymous_session_id,
                event_type,
                ip_hash,
                estimated_cost_usd,
                json.dumps(metadata or {}),
            ),
        )
        conn.commit()


def usage_summary(days: int = 7) -> dict:
    """Non-public helper for checking public MVP traffic and feature usage."""
    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        since = f"-{days} days"
        active_sessions = conn.execute(
            """
            SELECT COUNT(DISTINCT AnonymousSessionId)
            FROM UsageEvents
            WHERE CreatedAt >= datetime('now', ?);
            """,
            (since,),
        ).fetchone()[0]
        total_events = conn.execute(
            """
            SELECT COUNT(*)
            FROM UsageEvents
            WHERE CreatedAt >= datetime('now', ?);
            """,
            (since,),
        ).fetchone()[0]
        events_by_type = {
            row["EventType"]: row["Count"]
            for row in conn.execute(
                """
                SELECT EventType, COUNT(*) AS Count
                FROM UsageEvents
                WHERE CreatedAt >= datetime('now', ?)
                GROUP BY EventType
                ORDER BY EventType;
                """,
                (since,),
            ).fetchall()
        }

    return {
        "days": days,
        "active_sessions": active_sessions,
        "total_events": total_events,
        "events_by_type": events_by_type,
    }


def cleanup_expired_anonymous_data(
    retention_days: int = ANONYMOUS_SESSION_RETENTION_DAYS,
) -> int:
    """Delete expired anonymous DB rows and their local generated files."""
    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        expired = [
            row[0]
            for row in conn.execute(
                """
                SELECT Id
                FROM AnonymousSessions
                WHERE LastSeenAt < datetime('now', ?);
                """,
                (f"-{retention_days} days",),
            ).fetchall()
        ]
        if not expired:
            return 0

        placeholders = ",".join("?" for _ in expired)
        file_paths = [
            row[0]
            for row in conn.execute(
                f"""
                SELECT OriginalFilePath
                FROM ResumeDetails
                WHERE AnonymousSessionId IN ({placeholders})
                  AND OriginalFilePath IS NOT NULL;
                """,
                expired,
            ).fetchall()
        ]

        conn.execute(
            f"DELETE FROM PreparationMaterials WHERE AnonymousSessionId IN ({placeholders});",
            expired,
        )
        conn.execute(
            f"DELETE FROM JobApplications WHERE AnonymousSessionId IN ({placeholders});",
            expired,
        )
        conn.execute(
            f"DELETE FROM ResumeDetails WHERE AnonymousSessionId IN ({placeholders});",
            expired,
        )
        conn.execute(
            f"DELETE FROM JobDetails WHERE AnonymousSessionId IN ({placeholders});",
            expired,
        )
        conn.execute(
            f"DELETE FROM UsageEvents WHERE AnonymousSessionId IN ({placeholders});",
            expired,
        )
        conn.execute(
            f"DELETE FROM AnonymousSessions WHERE Id IN ({placeholders});",
            expired,
        )
        conn.commit()

    for raw_path in file_paths:
        path = Path(raw_path)
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            pass

    return len(expired)


def _maybe_cleanup_expired_anonymous_data() -> None:
    global _LAST_CLEANUP_AT
    now = time.time()
    if now - _LAST_CLEANUP_AT < 24 * 60 * 60:
        return
    _LAST_CLEANUP_AT = now
    cleanup_expired_anonymous_data()


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def prep_pack_enabled() -> bool:
    """Whether the single-tenant Prep Pack feature is allowed to run."""
    value = os.getenv("PREP_PACK_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def tailoring_recommendation(score: int | None, target_score: int = 85) -> dict:
    """Decision gate for whether tailoring is worth the user's cost/effort."""
    if score is None:
        return {
            "status": "needs_score",
            "can_tailor": False,
            "target_score": target_score,
            "message": "Run the match score first, then tailor based on the JD gaps.",
        }

    if score < 65:
        return {
            "status": "not_recommended",
            "can_tailor": False,
            "target_score": target_score,
            "message": (
                "Not recommended: this role has a high chance of rejection because "
                "the original resume is below 65%."
            ),
        }

    if score < 70:
        return {
            "status": "stretch",
            "can_tailor": True,
            "target_score": target_score,
            "message": (
                "Stretch role: tailor only if the candidate can explain the adjacent "
                "gaps clearly in an interview."
            ),
        }

    return {
        "status": "optimize",
        "can_tailor": True,
        "target_score": target_score,
        "message": (
            "Good base fit: maximize direct and adjacent JD keyword coverage "
            "to target 85+ while staying truthful."
        ),
    }


def parse_confirmed_skills(value: str | list[str] | None) -> list[str]:
    """Normalize user-confirmed skills that were missing or underplayed."""
    if not value:
        return []

    raw_items = value
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]+", value)

    skills: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        skill = re.sub(r"\s+", " ", str(item or "")).strip()
        if not skill:
            continue
        key = skill.lower()
        if key in seen:
            continue
        seen.add(key)
        skills.append(skill[:80])
        if len(skills) >= 40:
            break
    return skills


# --------------------------------------------------------------------------- #
# Listing / read helpers (populate the UI selectors and status panels)
# --------------------------------------------------------------------------- #
def list_resumes(anonymous_session_id: str | None = None) -> list[dict]:
    """Original (non-tailored) resumes, newest first.

    Tailored outputs are also ResumeDetails rows but live under data/tailored/;
    we exclude them so the picker only shows real source resumes.
    """
    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        if anonymous_session_id is None:
            rows = conn.execute(
                """
                SELECT Id, Name, Email, CurrentPosition, OriginalFileName
                FROM ResumeDetails
                WHERE OriginalFilePath NOT LIKE '%tailored%'
                ORDER BY Id DESC;
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT Id, Name, Email, CurrentPosition, OriginalFileName
                FROM ResumeDetails
                WHERE OriginalFilePath NOT LIKE '%tailored%'
                  AND AnonymousSessionId = ?
                ORDER BY Id DESC;
                """,
                (anonymous_session_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def list_jobs(anonymous_session_id: str | None = None) -> list[dict]:
    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        if anonymous_session_id is None:
            rows = conn.execute(
                """
                SELECT Id, CompanyName, Position, JobLocation
                FROM JobDetails
                ORDER BY Id DESC;
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT Id, CompanyName, Position, JobLocation
                FROM JobDetails
                WHERE AnonymousSessionId = ?
                ORDER BY Id DESC;
                """,
                (anonymous_session_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_application(
    resume_id: int,
    job_id: int,
    anonymous_session_id: str | None = None,
) -> dict | None:
    """Current JobApplications row for a pair (score/status/tailored link), or None."""
    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        ensure_application_score_detail_columns(conn)
        if anonymous_session_id is None:
            row = conn.execute(
                """
                SELECT Id, MatchScorePercent, MatchReasoning, MatchedSkills,
                       MissingSkills, Status, TailoredResumeId
                FROM JobApplications
                WHERE ResumeId = ? AND JobId = ?;
                """,
                (resume_id, job_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT Id, MatchScorePercent, MatchReasoning, MatchedSkills,
                       MissingSkills, Status, TailoredResumeId
                FROM JobApplications
                WHERE ResumeId = ? AND JobId = ? AND AnonymousSessionId = ?;
                """,
                (resume_id, job_id, anonymous_session_id),
            ).fetchone()
        conn.commit()

    if not row:
        return None

    application = dict(row)
    application["MatchedSkills"] = _json_list(application.get("MatchedSkills"))
    application["MissingSkills"] = _json_list(application.get("MissingSkills"))
    return application


def get_existing_prep(
    application_id: int,
    anonymous_session_id: str | None = None,
) -> InterviewPrepPack | None:
    """Re-hydrate the last saved prep pack for an application, if any."""
    if not prep_pack_enabled():
        return None

    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        if anonymous_session_id is None:
            row = conn.execute(
                """
                SELECT MaterialContent FROM PreparationMaterials
                WHERE JobApplicationId = ? AND MaterialType = 'interview_prep'
                ORDER BY Id DESC LIMIT 1;
                """,
                (application_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT MaterialContent
                FROM PreparationMaterials
                WHERE JobApplicationId = ?
                  AND MaterialType = 'interview_prep'
                  AND AnonymousSessionId = ?
                ORDER BY Id DESC LIMIT 1;
                """,
                (application_id, anonymous_session_id),
            ).fetchone()
    if not row:
        return None
    return InterviewPrepPack.model_validate_json(row["MaterialContent"])


def get_tailored_pdf_path(
    application_id: int,
    anonymous_session_id: str | None = None,
) -> Path | None:
    """Filesystem path of the tailored PDF linked to an application, if it exists."""
    with _connect() as conn:
        _ensure_public_safety_schema_on(conn)
        if anonymous_session_id is None:
            row = conn.execute(
                """
                SELECT r.OriginalFilePath AS path
                FROM JobApplications a
                JOIN ResumeDetails r ON r.Id = a.TailoredResumeId
                WHERE a.Id = ?;
                """,
                (application_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT r.OriginalFilePath AS path
                FROM JobApplications a
                JOIN ResumeDetails r ON r.Id = a.TailoredResumeId
                WHERE a.Id = ? AND a.AnonymousSessionId = ?;
                """,
                (application_id, anonymous_session_id),
            ).fetchone()
    if not row or not row["path"]:
        return None
    path = Path(row["path"])
    return path if path.exists() else None


# --------------------------------------------------------------------------- #
# Inputs: resume (upload / profile builder) and job (paste / URL)
# --------------------------------------------------------------------------- #
def parse_and_save_uploaded_resume(
    file_bytes: bytes,
    filename: str,
    anonymous_session_id: str | None = None,
) -> int:
    """Persist an uploaded PDF, parse it to a ResumeModel, and save the row.

    Returns the new/updated ResumeDetails.Id.
    """
    _validate_pdf_upload(file_bytes, filename)
    target_dir = _session_dir(RESUMES_DIR, anonymous_session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{_slug(Path(filename).stem)}.pdf"
    dest = target_dir / safe_name
    dest.write_bytes(file_bytes)

    text = extract_pdf_text(
        dest,
        max_pages=MAX_PDF_PAGES,
        max_chars=MAX_PDF_TEXT_CHARS,
    )
    if not text.strip():
        raise ValueError("PDF did not contain extractable text.")
    resume = parse_resume_text(text)
    return save_resume_to_db(resume, dest, anonymous_session_id=anonymous_session_id)


def build_resume_from_profile(
    name: str,
    email: str,
    target_role: str,
    location: str,
    years_experience: str,
    summary_text: str,
    anonymous_session_id: str | None = None,
) -> int:
    """Quick profile builder: turn a few fields + free text into a saved resume.

    We compose a small structured text block and run it through the SAME
    extraction chain the PDF path uses, so a profile-built resume becomes a
    normal ResumeDetails row (no special-casing downstream).
    """
    _require_within_limit("Profile text", summary_text, MAX_PROFILE_TEXT_CHARS)
    target_dir = _session_dir(PROFILES_DIR, anonymous_session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    composed = (
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Current Position / Target Role: {target_role}\n"
        f"Location: {location}\n"
        f"Years of experience: {years_experience}\n\n"
        f"{summary_text}\n"
    )
    profile_path = target_dir / f"{_slug(name)}-{_slug(email)}.txt"
    profile_path.write_text(composed, encoding="utf-8")

    resume = parse_resume_text(composed)
    return save_resume_to_db(
        resume, profile_path, anonymous_session_id=anonymous_session_id
    )


def ingest_job_from_paste(
    company_name: str,
    position: str,
    job_description: str,
    job_location: str | None = None,
    job_url: str | None = None,
    years_required: int | None = None,
    anonymous_session_id: str | None = None,
) -> int:
    """Save a manually pasted JD as a JobDetails row. Returns JobDetails.Id."""
    _require_within_limit(
        "Job description", job_description, MAX_JOB_DESCRIPTION_CHARS
    )
    url = (
        job_url.strip()
        if job_url and job_url.strip()
        else f"manual://{_slug(company_name)}/{_slug(position)}"
    )
    url = _session_scoped_job_url(url, anonymous_session_id)
    job = JobDetailsModel(
        company_name=company_name,
        position=position,
        job_description=job_description,
        job_location=job_location or None,
        job_url=url,
        years_of_experience_required=years_required,
        is_open=True,
    )
    if anonymous_session_id is None:
        return save_job_to_db(job)
    return save_job_to_db(job, anonymous_session_id=anonymous_session_id)


def ingest_job_from_url(
    page_url: str,
    anonymous_session_id: str | None = None,
) -> int:
    """Best-effort job ingest from a supported career posting URL.

    Raises a clear ValueError for unsupported sites so the UI can tell the user
    to paste the JD instead.
    """
    from phase2_search.career_page import fetch_career_page_job, validate_career_page_url
    from phase2_search.workday import fetch_workday_job

    parts = urlsplit((page_url or "").strip())
    host = (parts.hostname or "").lower()
    if host.endswith(".myworkdayjobs.com"):
        _validate_workday_url(page_url)
        job = fetch_workday_job(page_url)
    else:
        safe_url = validate_career_page_url(page_url)
        job = fetch_career_page_job(safe_url)

    if anonymous_session_id:
        job = job.model_copy(
            update={
                "job_url": _session_scoped_job_url(job.job_url, anonymous_session_id)
            }
        )
    if anonymous_session_id is None:
        return save_job_to_db(job)
    return save_job_to_db(job, anonymous_session_id=anonymous_session_id)


# --------------------------------------------------------------------------- #
# Pipeline actions (score / tailor / prep)
# --------------------------------------------------------------------------- #
def run_score(
    resume_id: int,
    job_id: int,
    anonymous_session_id: str | None = None,
) -> tuple[MatchResult, int]:
    """Score a resume against a job and upsert the JobApplications row."""
    resume = get_resume_by_id(resume_id, anonymous_session_id=anonymous_session_id)
    job = get_job_by_id(job_id, anonymous_session_id=anonymous_session_id)
    if resume is None:
        raise ValueError(f"No resume with Id={resume_id}.")
    if job is None:
        raise ValueError(f"No job with Id={job_id}.")

    result = score_resume_against_job(resume_to_text(resume), job_to_text(job))
    application_id = save_application_to_db(
        resume_id,
        job_id,
        result,
        anonymous_session_id=anonymous_session_id,
    )
    return result, application_id


def run_tailor(
    resume_id: int,
    job_id: int,
    anonymous_session_id: str | None = None,
    confirmed_skills_text: str | None = None,
    confirmed_skills: list[str] | None = None,
) -> TailorRunResult:
    """Generate the tailored resume (Markdown + ATS PDF) and link it to the app.

    Returns the model and the PDF path.
    """
    resume = get_resume_by_id(resume_id, anonymous_session_id=anonymous_session_id)
    job = get_job_by_id(job_id, anonymous_session_id=anonymous_session_id)
    if resume is None:
        raise ValueError(f"No resume with Id={resume_id}.")
    if job is None:
        raise ValueError(f"No job with Id={job_id}.")

    application = get_application(
        resume_id,
        job_id,
        anonymous_session_id=anonymous_session_id,
    )
    score = application.get("MatchScorePercent") if application else None
    recommendation = tailoring_recommendation(score)
    if not recommendation["can_tailor"]:
        raise ValueError(recommendation["message"])

    resume_text = resume_to_text(resume)
    job_text = job_to_text(job)
    normalized_confirmed_skills = parse_confirmed_skills(
        confirmed_skills if confirmed_skills is not None else confirmed_skills_text
    )
    keyword_report = analyze_keyword_coverage(
        resume_text,
        job_text,
        confirmed_skills=normalized_confirmed_skills,
        target_score=recommendation["target_score"],
    )
    tailored = tailor_resume_for_job(
        resume_text,
        job_text,
        keyword_report=keyword_report,
        confirmed_skills=normalized_confirmed_skills,
        original_score=score,
        target_score=recommendation["target_score"],
    )
    output_dir = _session_dir(TAILORED_OUTPUT_DIR, anonymous_session_id)

    save_tailored_resume(
        tailored,
        resume.get("Name"),
        job.get("CompanyName"),
        job.get("Position"),
        output_dir=output_dir,
    )
    pdf_path = render_tailored_pdf(
        tailored,
        resume,
        job.get("CompanyName"),
        job.get("Position"),
        output_dir=output_dir,
    )
    save_tailored_resume_link(
        original_resume_id=resume_id,
        job_id=job_id,
        tailored=tailored,
        candidate_name=resume.get("Name"),
        candidate_email=resume.get("Email"),
        pdf_path=pdf_path,
        source_resume=resume,
        anonymous_session_id=anonymous_session_id,
    )
    return TailorRunResult(
        tailored=tailored,
        pdf_path=Path(pdf_path),
        keyword_report=keyword_report,
        ats_coverage_score=ats_coverage_score(keyword_report),
    )


def run_prep(
    resume_id: int,
    job_id: int,
    anonymous_session_id: str | None = None,
) -> tuple[InterviewPrepPack, int]:
    """Generate the grounded interview prep pack (RAG) and persist it.

    Requires an existing application (score first), since prep is keyed on it.
    """
    if not prep_pack_enabled():
        raise ValueError(PREP_PACK_DISABLED_MESSAGE)

    application_id = get_application_id(
        resume_id, job_id, anonymous_session_id=anonymous_session_id
    )
    if application_id is None:
        raise ValueError(
            "Score this resume against the job first — the prep pack attaches to "
            "the application record."
        )
    job = get_job_by_id(job_id, anonymous_session_id=anonymous_session_id)
    if job is None:
        raise ValueError(f"No job with Id={job_id}.")

    pack = generate_prep_for_job(job_to_text(job))
    if anonymous_session_id is None:
        save_prep_to_db(application_id, pack)
    else:
        save_prep_to_db(
            application_id, pack, anonymous_session_id=anonymous_session_id
        )
    return pack, application_id


# --------------------------------------------------------------------------- #
# Phase 5 — LangGraph coach agent (chat seam).
#
# Contract with the (user-written) graph: phase5_coach/coach_graph.py exposes a
# module-level compiled `graph` (a LangGraph StateGraph compiled WITH a
# checkpointer). Each resume x job pair maps to its own thread_id, so the graph's
# checkpointer keeps conversations isolated and durable across turns. This is the
# only API<->graph seam; the graph is imported LAZILY so the rest of the app keeps
# working before the graph exists.
# --------------------------------------------------------------------------- #
def coach_thread_id(
    resume_id: int,
    job_id: int,
    anonymous_session_id: str | None = None,
) -> str:
    """Stable per-pair conversation id — the graph checkpointer keys on this."""
    if anonymous_session_id:
        return f"coach-{_session_hash(anonymous_session_id)}-{resume_id}-{job_id}"
    return f"coach-{resume_id}-{job_id}"


def coach_is_ready() -> bool:
    """True once phase5_coach.coach_graph exposes a compiled `graph`."""
    try:
        from phase5_coach.coach_graph import graph  # noqa: F401
        return True
    except Exception:
        return False


def coach_reply(
    resume_id: int,
    job_id: int,
    user_message: str,
    anonymous_session_id: str | None = None,
) -> str:
    """Send one user turn to the coach graph and return the assistant's reply.

    Memory is the graph's responsibility: we invoke with a per-pair thread_id, so
    the checkpointer reloads prior turns automatically. We pass only the new human
    message; the `add_messages` reducer in the graph appends it to the history.

    Grounding (Phase 5.4): we also pass the flattened resume + JD text on every
    turn. Those state channels use the default (overwrite) reducer, so re-sending
    them is idempotent and keeps the coach grounded even if the active job changes
    mid-conversation. The graph reads them defensively, so this stays optional.
    """
    _require_within_limit(
        "Coach message", user_message, MAX_COACH_MESSAGE_CHARS
    )

    resume = get_resume_by_id(resume_id, anonymous_session_id=anonymous_session_id)
    job = get_job_by_id(job_id, anonymous_session_id=anonymous_session_id)
    if resume is None:
        raise ValueError(f"No resume with Id={resume_id}.")
    if job is None:
        raise ValueError(f"No job with Id={job_id}.")

    from langchain_core.messages import HumanMessage
    from phase5_coach.coach_graph import graph

    resume_text = resume_to_text(resume) if resume else ""
    job_text = job_to_text(job) if job else ""

    cfg = {
        "configurable": {
            "thread_id": coach_thread_id(
                resume_id, job_id, anonymous_session_id=anonymous_session_id
            )
        }
    }
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=user_message)],
            "resume_text": resume_text,
            "job_text": job_text,
        },
        cfg,
    )
    messages = result.get("messages") if isinstance(result, dict) else None
    if not messages:
        return "(the coach returned no message)"
    last = messages[-1]
    return getattr(last, "content", str(last))
