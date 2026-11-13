"""HTTP API for the React Resume Workbench.

FastAPI is intentionally a thin wrapper over `webapp.services`: the existing
LangChain, LangGraph, RAG, database, and PDF logic stay in the phase packages.
"""
from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path
from typing import Any, NamedTuple

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from phase4_tailor.artifacts import compact_artifact_label
from webapp import services as svc

MAX_PDF_UPLOAD_BYTES = svc.MAX_PDF_UPLOAD_BYTES


# Static admin dashboard shell served at GET /admin. Holds NO secret: it asks for
# the admin token, stores it in sessionStorage, and fetches /api/admin/usage.
# Palette mirrors the React app's design tokens (frontend/src/styles.css :root).
_ADMIN_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>Resume Buddy · Admin</title>
<style>
  :root{
    --bg:#f8f4ec; --surface:#ffffff; --ink:#252019; --muted:#6f675d;
    --faint:#93887c; --line:#e4ddd2; --accent:#c35f2e; --sage:#497564;
    --blue:#466f91; --gold:#a87929; --radius:8px;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;}
  .wrap{max-width:980px;margin:0 auto;padding:32px 20px 64px;}
  h1{font-size:22px;margin:0 0 2px;}
  .sub{color:var(--muted);font-size:13px;margin:0 0 22px;}
  .bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:24px;}
  input,select,button{font:inherit;border:1px solid var(--line);border-radius:var(--radius);
    padding:9px 12px;background:var(--surface);color:var(--ink);}
  input{min-width:240px;}
  button{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:650;cursor:pointer;}
  button:hover{filter:brightness(1.05);}
  .err{color:#803b37;background:#fff2f0;border:1px solid #dfb7b4;border-radius:var(--radius);
    padding:10px 12px;font-size:13px;margin-bottom:18px;display:none;}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:28px;}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;}
  .card .k{color:var(--muted);font-size:12px;font-weight:650;text-transform:uppercase;letter-spacing:.04em;}
  .card .v{font-size:30px;font-weight:750;margin-top:6px;}
  .card .v small{font-size:13px;color:var(--faint);font-weight:600;}
  h2{font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin:0 0 12px;}
  .chart{display:flex;align-items:flex-end;gap:8px;height:180px;
    border-left:1px solid var(--line);border-bottom:1px solid var(--line);padding:8px 6px;}
  .col{flex:1 1 0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:6px;min-width:0;}
  .col .bv{width:70%;max-width:34px;background:var(--sage);border-radius:4px 4px 0 0;min-height:2px;}
  .col .cap{font-size:10px;color:var(--faint);white-space:nowrap;}
  .col .num{font-size:11px;color:var(--muted);font-weight:650;}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px;}
  td,th{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);}
  th{color:var(--muted);font-weight:650;}
  .muted{color:var(--faint);font-size:12px;margin-top:10px;}
</style>
</head>
<body>
<div class="wrap">
  <h1>Resume Buddy · Admin</h1>
  <p class="sub">Anonymous usage. Free-tier storage is ephemeral — counts reset when the Space restarts.</p>
  <div class="bar">
    <input id="tok" type="password" placeholder="Admin token" autocomplete="off" />
    <select id="days">
      <option value="7">Last 7 days</option>
      <option value="14">Last 14 days</option>
      <option value="30">Last 30 days</option>
      <option value="90">Last 90 days</option>
    </select>
    <button id="load">Load</button>
  </div>
  <div id="err" class="err"></div>
  <div id="out" style="display:none">
    <div class="cards" id="cards"></div>
    <h2>Activity by day</h2>
    <div class="chart" id="chart"></div>
    <h2 style="margin-top:28px">All events by type</h2>
    <table id="types"><tbody></tbody></table>
    <p class="muted" id="meta"></p>
  </div>
</div>
<script>
  const $ = (id) => document.getElementById(id);
  const tokKey = "rb_admin_token";
  $("tok").value = sessionStorage.getItem(tokKey) || "";

  function card(k, v, sub){
    return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+
      (sub ? ' <small>'+sub+'</small>' : '')+'</div></div>';
  }

  async function load(){
    const tok = $("tok").value.trim();
    const days = $("days").value;
    $("err").style.display = "none";
    if(!tok){ showErr("Enter the admin token."); return; }
    sessionStorage.setItem(tokKey, tok);
    try{
      const r = await fetch("/api/admin/usage?days="+days, {headers:{"X-Admin-Token":tok}});
      if(r.status === 404){ showErr("Wrong token, or ADMIN_TOKEN isn't set on the Space."); return; }
      if(!r.ok){ showErr("Request failed ("+r.status+")."); return; }
      render(await r.json());
    }catch(e){ showErr("Couldn't reach the server."); }
  }

  function showErr(m){ const e=$("err"); e.textContent=m; e.style.display="block"; $("out").style.display="none"; }

  function render(d){
    const ev = d.events_by_type || {};
    const cards = [
      card("Visitors", d.active_sessions ?? 0, "unique"),
      card("Resume uploads", ev.resume_upload ?? 0),
      card("Scores", ev.score ?? 0),
      card("Tailors", ev.tailor ?? 0),
      card("Total events", d.total_events ?? 0, "in "+d.days+"d"),
    ].join("");
    $("cards").innerHTML = cards;

    const days = d.by_day || [];
    const max = days.reduce((m,x)=>Math.max(m, x.events||0), 0) || 1;
    $("chart").innerHTML = days.length
      ? days.map(x => {
          const h = Math.round(((x.events||0)/max)*150);
          const lbl = (x.day||"").slice(5);
          return '<div class="col"><div class="num">'+(x.events||0)+
            '</div><div class="bv" style="height:'+h+'px"></div>'+
            '<div class="cap">'+lbl+'</div></div>';
        }).join("")
      : '<div class="muted" style="padding:20px">No activity in this window yet.</div>';

    const rows = Object.keys(ev).sort().map(k =>
      '<tr><td>'+k+'</td><td>'+ev[k]+'</td></tr>').join("")
      || '<tr><td colspan="2" class="muted">No events yet.</td></tr>';
    $("types").querySelector("tbody").innerHTML =
      '<tr><th>Event type</th><th>Count</th></tr>'+rows;

    $("meta").textContent = "Window: last "+d.days+" days.";
    $("out").style.display = "block";
  }

  $("load").addEventListener("click", load);
  $("tok").addEventListener("keydown", (e)=>{ if(e.key==="Enter") load(); });
  if($("tok").value) load();
</script>
</body>
</html>
"""


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

    # PDF text extraction + the LLM parse are blocking and multi-second. This is
    # an `async def` handler, so running them inline would freeze the event loop
    # and stall every other in-flight request. Offload to a worker thread (the LLM
    # call is network I/O, so it releases the GIL) and await it — the loop stays
    # free to service other users while this upload is parsed.
    def _parse_upload() -> int:
        svc.record_guarded_usage(ctx.session_id, "resume_upload", ctx.ip_hash)
        return svc.parse_and_save_uploaded_resume(
            file_bytes, filename, anonymous_session_id=ctx.session_id
        )

    try:
        resume_id = await asyncio.to_thread(_parse_upload)
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
            "original_match_score": result.original_match_score,
            "tailored_match_score": result.tailored_match_score,
            "iterations": result.iterations,
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


# --------------------------------------------------------------------------- #
# Admin usage analytics. The app already records anonymous visits (one row per
# session) and feature events (resume_upload, score, tailor, coach...). These two
# routes expose the existing `usage_summary()` over HTTP so the owner can read
# live counts on the deployed Space without shelling into the container.
#
# Auth = a single shared secret in ADMIN_TOKEN (set as an HF Space secret).
# Fail CLOSED: if ADMIN_TOKEN is unset or the supplied token doesn't match, the
# data route 404s (hides its existence) so nothing is ever public.
#
# NOTE: defined ABOVE the StaticFiles mount below so these paths win over the SPA.
# --------------------------------------------------------------------------- #
def _admin_authorized(token: str | None) -> bool:
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    if not expected:
        return False  # fail closed: no token configured => no access
    if not token:
        return False
    return hmac.compare_digest(token, expected)


@app.get("/api/admin/usage")
def admin_usage(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    token: str | None = Query(default=None),
) -> Any:
    supplied = request.headers.get("x-admin-token") or token
    if not _admin_authorized(supplied):
        # Same response whether the token is missing, wrong, or unconfigured.
        raise HTTPException(status_code=404, detail="Not found.")
    return jsonable_encoder(svc.usage_summary(days=days))


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard() -> str:
    # Self-contained page: holds NO secret. It asks for the admin token, keeps it
    # in sessionStorage, and calls /api/admin/usage (which enforces the token).
    return _ADMIN_DASHBOARD_HTML


# --------------------------------------------------------------------------- #
# Serve the built React frontend from the same origin (single-container deploy,
# e.g. Hugging Face Spaces). When `frontend/dist` exists (created by
# `npm run build`), it is mounted LAST so all /api routes above take precedence.
# In local dev you instead run Vite on :5173 and this mount simply won't exist.
# --------------------------------------------------------------------------- #
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )
