"""HTTP API for the React Resume Workbench.

FastAPI is intentionally a thin wrapper over `webapp.services`: the existing
LangChain, LangGraph, RAG, database, and PDF logic stay in the phase packages.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, NamedTuple

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from phase4_tailor.artifacts import compact_artifact_label
from webapp import services as svc

MAX_PDF_UPLOAD_BYTES = svc.MAX_PDF_UPLOAD_BYTES


class ProfileResumeRequest(BaseModel):
    name: str = Field(max_length=120)
    email: str = Field(max_length=254)
    target_role: str = Field(default="", max_length=160)
    location: str = Field(default="", max_length=160)
    years_experience: str = Field(default="", max_length=40)
    summary_text: str = Field(max_length=svc.MAX_PROFILE_TEXT_CHARS)


class PasteJobRequest(BaseModel):
    company_name: str = Field(max_length=160)
    position: str = Field(max_length=200)
    job_description: str = Field(max_length=svc.MAX_JOB_DESCRIPTION_CHARS)
    job_location: str | None = Field(default=None, max_length=160)
    job_url: str | None = Field(default=None, max_length=2048)
    years_required: int | None = None


class ImportJobRequest(BaseModel):
    page_url: str = Field(max_length=2048)


class PairRequest(BaseModel):
    resume_id: int
    job_id: int


class TailorRequest(PairRequest):
    confirmed_skills: list[str] = Field(default_factory=list, max_length=40)


class CoachRequest(PairRequest):
    message: str = Field(min_length=1, max_length=svc.MAX_COACH_MESSAGE_CHARS)


def _allowed_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


app = FastAPI(title="Resume Workbench API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnonymousContext(NamedTuple):
    session_id: str
    ip_hash: str | None


def _cookie_secure() -> bool:
    return os.getenv("ANON_COOKIE_SECURE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _anonymous_context(request: Request, response: Response) -> AnonymousContext:
    session_id = request.cookies.get(svc.ANONYMOUS_SESSION_COOKIE)
    if not svc.is_valid_anonymous_session_id(session_id):
        session_id = svc.new_anonymous_session_id()

    svc.ensure_anonymous_session(session_id)
    response.set_cookie(
        key=svc.ANONYMOUS_SESSION_COOKIE,
        value=session_id,
        max_age=svc.ANONYMOUS_SESSION_RETENTION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )
    client_host = request.client.host if request.client else None
    return AnonymousContext(
        session_id=session_id,
        ip_hash=svc.hash_ip_address(client_host),
    )


def _features() -> dict[str, bool]:
    return {
        "prep_pack_enabled": svc.prep_pack_enabled(),
        "coach_ready": svc.coach_is_ready(),
    }


def _bootstrap(ctx: AnonymousContext) -> dict[str, Any]:
    return {
        "resumes": svc.list_resumes(ctx.session_id),
        "jobs": svc.list_jobs(ctx.session_id),
        "features": _features(),
    }


def _pair_state(resume_id: int, job_id: int, ctx: AnonymousContext) -> dict[str, Any]:
    application = svc.get_application(resume_id, job_id, ctx.session_id)
    application_id = application.get("Id") if application else None
    pdf_path = (
        svc.get_tailored_pdf_path(application_id, ctx.session_id)
        if application_id is not None
        else None
    )
    prep_pack = (
        svc.get_existing_prep(application_id, ctx.session_id)
        if application_id is not None
        else None
    )
    score = application.get("MatchScorePercent") if application else None
    pdf_filename = pdf_path.name if pdf_path else None

    return {
        "application": application,
        "tailored_pdf_available": bool(pdf_path),
        "tailored_pdf_filename": pdf_filename,
        "tailored_pdf_display_name": (
            compact_artifact_label(pdf_filename) if pdf_filename else None
        ),
        "tailoring_recommendation": svc.tailoring_recommendation(score),
        "prep_pack": jsonable_encoder(prep_pack) if prep_pack else None,
    }


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bootstrap")
def bootstrap(ctx: AnonymousContext = Depends(_anonymous_context)) -> dict[str, Any]:
    return jsonable_encoder(_bootstrap(ctx))


@app.get("/api/pairs/{resume_id}/{job_id}")
def pair_state(
    resume_id: int,
    job_id: int,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    return jsonable_encoder(_pair_state(resume_id, job_id, ctx))


@app.post("/api/resumes/upload")
async def upload_resume(
    file: UploadFile = File(...),
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    filename = file.filename or "resume.pdf"
    if not filename.lower().endswith(".pdf") or file.content_type not in {
        "application/pdf",
        "application/x-pdf",
    }:
        raise HTTPException(status_code=400, detail="Upload a PDF resume file.")

    file_bytes = await file.read(MAX_PDF_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_PDF_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded PDF is too large. Limit is {MAX_PDF_UPLOAD_BYTES} bytes.",
        )

    try:
        svc.record_guarded_usage(ctx.session_id, "resume_upload", ctx.ip_hash)
        resume_id = svc.parse_and_save_uploaded_resume(
            file_bytes, filename, anonymous_session_id=ctx.session_id
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return jsonable_encoder({"resume_id": resume_id, **_bootstrap(ctx)})


@app.post("/api/resumes/profile")
def create_profile_resume(
    payload: ProfileResumeRequest,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    try:
        svc.record_guarded_usage(ctx.session_id, "resume_upload", ctx.ip_hash)
        resume_id = svc.build_resume_from_profile(
            **payload.model_dump(), anonymous_session_id=ctx.session_id
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return jsonable_encoder({"resume_id": resume_id, **_bootstrap(ctx)})


@app.post("/api/jobs/paste")
def paste_job(
    payload: PasteJobRequest,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    try:
        svc.record_guarded_usage(ctx.session_id, "job_save", ctx.ip_hash)
        job_id = svc.ingest_job_from_paste(
            **payload.model_dump(), anonymous_session_id=ctx.session_id
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return jsonable_encoder({"job_id": job_id, **_bootstrap(ctx)})


@app.post("/api/jobs/import")
def import_job(
    payload: ImportJobRequest,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    try:
        svc.record_guarded_usage(ctx.session_id, "job_import", ctx.ip_hash)
        job_id = svc.ingest_job_from_url(
            payload.page_url, anonymous_session_id=ctx.session_id
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return jsonable_encoder({"job_id": job_id, **_bootstrap(ctx)})


@app.post("/api/score")
def score(
    payload: PairRequest,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    try:
        svc.record_guarded_usage(ctx.session_id, "score", ctx.ip_hash)
        match, application_id = svc.run_score(
            payload.resume_id, payload.job_id, anonymous_session_id=ctx.session_id
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return jsonable_encoder(
        {
            "application_id": application_id,
            "match": match,
            "pair_state": _pair_state(payload.resume_id, payload.job_id, ctx),
        }
    )


@app.post("/api/tailor")
def tailor(
    payload: TailorRequest,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    try:
        svc.record_guarded_usage(ctx.session_id, "tailor", ctx.ip_hash)
        result = svc.run_tailor(
            payload.resume_id,
            payload.job_id,
            anonymous_session_id=ctx.session_id,
            confirmed_skills=payload.confirmed_skills,
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return jsonable_encoder(
        {
            "tailored": result.tailored,
            "pdf_path": str(result.pdf_path),
            "keyword_coverage": result.keyword_report,
            "ats_coverage_score": result.ats_coverage_score,
            "pair_state": _pair_state(payload.resume_id, payload.job_id, ctx),
        }
    )


@app.post("/api/prep")
def prep(
    payload: PairRequest,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, Any]:
    try:
        prep_pack, application_id = svc.run_prep(
            payload.resume_id, payload.job_id, anonymous_session_id=ctx.session_id
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return jsonable_encoder(
        {
            "application_id": application_id,
            "prep_pack": prep_pack,
            "pair_state": _pair_state(payload.resume_id, payload.job_id, ctx),
        }
    )


@app.post("/api/coach")
def coach(
    payload: CoachRequest,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> dict[str, str]:
    try:
        svc.record_guarded_usage(ctx.session_id, "coach", ctx.ip_hash)
        reply = svc.coach_reply(
            payload.resume_id,
            payload.job_id,
            payload.message,
            anonymous_session_id=ctx.session_id,
        )
    except Exception as exc:
        raise _bad_request(exc) from exc
    return {"reply": reply}


@app.get("/api/applications/{application_id}/tailored-pdf")
def tailored_pdf(
    application_id: int,
    ctx: AnonymousContext = Depends(_anonymous_context),
) -> FileResponse:
    path = svc.get_tailored_pdf_path(application_id, ctx.session_id)
    if not path:
        raise HTTPException(status_code=404, detail="Tailored PDF is not available.")

    file_path = Path(path)
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=file_path.name,
    )
