"""Persistence for resume-vs-job applications. Mirrors db/job_repository.py.

A JobApplications row is the JOIN of one resume + one job. It holds the
LLM-produced MatchScorePercent and the workflow Status. Idempotent upsert
keyed on UNIQUE(ResumeId, JobId) so re-scoring the same pair updates the
existing row instead of creating a duplicate.
"""

import json
import sqlite3
from pathlib import Path

from db.public_safety import ensure_public_safety_schema
from models.match import MatchResult


def ensure_application_score_detail_columns(conn: sqlite3.Connection) -> None:
    """Add match-snapshot detail columns to older local DB files."""
    ensure_public_safety_schema(conn)
    existing = {
        row[1] for row in conn.execute("PRAGMA table_info(JobApplications);").fetchall()
    }

    if "MatchReasoning" not in existing:
        conn.execute("ALTER TABLE JobApplications ADD COLUMN MatchReasoning Text NULL;")
    if "MatchedSkills" not in existing:
        conn.execute("ALTER TABLE JobApplications ADD COLUMN MatchedSkills Text NULL;")
    if "MissingSkills" not in existing:
        conn.execute("ALTER TABLE JobApplications ADD COLUMN MissingSkills Text NULL;")


def save_application_to_db(
    resume_id: int,
    job_id: int,
    match: MatchResult,
    status: str = "Not Applied",
    anonymous_session_id: str | None = None,
) -> int:
    """Insert or update one application; return its JobApplications.Id."""
    conn = None
    try:
        HERE = Path(__file__).resolve().parent
        db_path = HERE / "job-tracker.db"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        ensure_application_score_detail_columns(conn)

        matched_skills_json = json.dumps(match.matched_skills)
        missing_skills_json = json.dumps(match.missing_skills)

        cursor.execute(
            """
            INSERT INTO JobApplications (
                AnonymousSessionId, ResumeId, JobId, MatchScorePercent, MatchReasoning,
                MatchedSkills, MissingSkills, Status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ResumeId, JobId) DO UPDATE SET
                AnonymousSessionId=excluded.AnonymousSessionId,
                MatchScorePercent=excluded.MatchScorePercent,
                MatchReasoning=excluded.MatchReasoning,
                MatchedSkills=excluded.MatchedSkills,
                MissingSkills=excluded.MissingSkills,
                Status=excluded.Status
            RETURNING Id;
            """,
            (
                anonymous_session_id,
                resume_id,
                job_id,
                match.match_score,
                match.reasoning,
                matched_skills_json,
                missing_skills_json,
                status,
            ),
        )

        application_id = cursor.fetchone()[0]
        conn.commit()
        return application_id

    except sqlite3.Error as e:
        print(f"An error occurred while saving the application to the database: {e}")
        raise

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    pass
