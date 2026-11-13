"""Quality + speed comparison across LLM providers, on the REAL pipeline.

Quality is the gate: this runs the actual parse -> score -> keyword -> tailor
pipeline for each provider PROFILE and writes a side-by-side HTML report so a
human can judge tailored-output quality (not just a speed number). NVIDIA Nemotron
is the baseline; a challenger only earns a tier if its quality holds.

Run:  python -m scripts.compare_providers
Env:  RESUME_PDF=<path>   (defaults to data/resumes/sample.pdf; provide it locally)
      PROFILES=baseline,groq,gemini   (subset to run)

Needs the relevant API keys set for whichever profiles you run:
  NVIDIA_API_KEY (baseline), GROQ_API_KEY (groq), GOOGLE_API_KEY (gemini).
Missing-key or failing profiles are recorded in the report, not fatal.
"""
import html
import os
import time
from pathlib import Path

# Provider profiles: (parse model, fast model, tailor model). Prefixes route the
# provider in config.settings.get_llm. Edit the model ids here to try variants.
PROFILES = {
    "baseline": {
        "label": "NVIDIA Nemotron (baseline)",
        "parse": "nvidia/llama-3.3-nemotron-super-49b-v1",
        "fast": "nvidia/nemotron-3-nano-30b-a3b",
        "tailor": "nvidia/nemotron-3-super-120b-a12b",
    },
    "groq": {
        "label": "Groq",
        "parse": "groq/llama-3.3-70b-versatile",
        # Groq's 70B is fast enough to use for the mechanical tier too; the 8B
        # sometimes returns empty fields that fail validators (e.g. score.reasoning).
        "fast": "groq/llama-3.3-70b-versatile",
        "tailor": "groq/llama-3.3-70b-versatile",
    },
    "gemini": {
        "label": "Google Gemini",
        "parse": "google/gemini-3.5-flash",
        "fast": "google/gemini-3.5-flash",
        "tailor": "google/gemini-3.5-flash",
    },
}

TARGET = 85
DEFAULT_RESUME = (
    Path(__file__).resolve().parent.parent / "data" / "resumes" / "sample.pdf"
)
JOB = """Company: Siemens Energy
Position: Generative AI Specialist
Job description:
Build production LLM / Generative AI applications: RAG pipelines, agentic workflows,
prompt engineering, vector search and embeddings. Strong Python and backend (FastAPI),
cloud (Azure), and experience shipping AI features end to end. Nice to have: LangChain /
LangGraph, structured output, evaluation, Docker, CI/CD."""


def _run_profile(key: str, prof: dict, resume_pdf: Path) -> dict:
    """Run the full pipeline for one profile; capture outputs, timings, errors."""
    os.environ["NVIDIA_MODEL_PARSE"] = prof["parse"]
    os.environ["NVIDIA_MODEL_FAST"] = prof["fast"]
    os.environ["NVIDIA_MODEL_TAILOR"] = prof["tailor"]

    from phase1_parse.parse_resume import extract_pdf_text, parse_resume_text
    from phase3_score.score_match import score_resume_against_job
    from phase4_tailor.keyword_coverage import (
        analyze_keyword_coverage,
        backfill_uncovered_keywords,
        measure_resume_coverage,
    )
    from phase4_tailor.tailor_resume import tailor_resume_for_job, tailored_to_text

    out = {"label": prof["label"], "profile": prof, "error": None, "times": {}}
    try:
        text = extract_pdf_text(str(resume_pdf))

        t0 = time.perf_counter()
        resume = parse_resume_text(text)
        out["times"]["parse"] = time.perf_counter() - t0
        out["parse"] = {
            "education": resume.education,
            "location": resume.location,
            "phone": resume.phone,
            "skills": len(resume.skills or []),
            "experience": len(resume.experience or []),
            "projects": len(resume.projects or []),
            "summary_len": len((resume.summary or "")),
        }

        resume_text = text  # tailor works from raw text + keyword report
        t0 = time.perf_counter()
        base = score_resume_against_job(resume_text, JOB)
        out["times"]["score"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        report = analyze_keyword_coverage(resume_text, JOB, target_score=TARGET)
        out["times"]["keyword"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        tailored = tailor_resume_for_job(
            resume_text, JOB, keyword_report=report,
            original_score=base.match_score, target_score=TARGET,
        )
        out["times"]["tailor"] = time.perf_counter() - t0

        tailored = backfill_uncovered_keywords(tailored, report)
        measured = measure_resume_coverage(tailored_to_text(tailored), report)
        out["baseline_match"] = base.match_score
        out["ats_coverage"] = measured["score"]
        out["tailored"] = {
            "summary": tailored.tailored_summary,
            "skills": [(c.category, c.skills) for c in tailored.tailored_skills],
            "experience": [
                (e.company, e.role_title, e.bullets) for e in tailored.tailored_experience
            ],
        }
    except Exception as exc:  # missing key / model error — record, don't abort
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["times"]["total"] = sum(out["times"].values())
    return out


def _esc(x) -> str:
    return html.escape(str(x))


def _col_html(key: str, r: dict) -> str:
    if r["error"]:
        return f"<td class='col'><h3>{_esc(r['label'])}</h3><p class='err'>{_esc(r['error'])}</p></td>"
    t = r["times"]
    p = r["parse"]
    tl = r["tailored"]
    skills = "".join(
        f"<li><b>{_esc(cat)}:</b> {_esc(', '.join(sk))}</li>" for cat, sk in tl["skills"]
    )
    exp = ""
    for company, role, bullets in tl["experience"]:
        bl = "".join(f"<li>{_esc(b)}</li>" for b in bullets)
        exp += f"<div class='job'><b>{_esc(company)}</b> — <i>{_esc(role)}</i><ul>{bl}</ul></div>"
    return f"""<td class='col'>
      <h3>{_esc(r['label'])}</h3>
      <div class='metrics'>
        <span class='pill'>total {t['total']:.1f}s</span>
        <span class='pill'>ATS {r['ats_coverage']}/100</span>
        <span class='pill'>match {r['baseline_match']}</span>
      </div>
      <div class='times'>parse {t.get('parse',0):.1f}s · score {t.get('score',0):.1f}s · keyword {t.get('keyword',0):.1f}s · tailor {t.get('tailor',0):.1f}s</div>
      <h4>Parse completeness</h4>
      <ul class='parse'>
        <li>education: {('<span class=ok>OK</span> ' + _esc(p['education'])) if p['education'] else '<span class=bad>MISSING</span>'}</li>
        <li>location: {_esc(p['location']) or '<span class=bad>—</span>'}</li>
        <li>phone: {_esc(p['phone']) or '<span class=bad>—</span>'}</li>
        <li>skills: {p['skills']} · experience: {p['experience']} · projects: {p['projects']}</li>
      </ul>
      <h4>Tailored summary</h4><p class='sum'>{_esc(tl['summary'])}</p>
      <h4>Tailored skills</h4><ul class='sk'>{skills}</ul>
      <h4>Tailored experience</h4>{exp}
    </td>"""


def main() -> None:
    resume_pdf = Path(os.getenv("RESUME_PDF", str(DEFAULT_RESUME)))
    wanted = [p.strip() for p in os.getenv("PROFILES", "").split(",") if p.strip()]
    profiles = {k: PROFILES[k] for k in (wanted or PROFILES) if k in PROFILES}

    print(f"Resume: {resume_pdf}\nProfiles: {', '.join(profiles)}\n")
    results = {}
    for key, prof in profiles.items():
        print(f"running {key} ({prof['label']}) ...", flush=True)
        results[key] = _run_profile(key, prof, resume_pdf)
        r = results[key]
        if r["error"]:
            print(f"  ! {r['error']}")
        else:
            print(f"  ok: total {r['times']['total']:.1f}s ATS {r['ats_coverage']} "
                  f"edu={'Y' if r['parse']['education'] else 'N'} proj={r['parse']['projects']}")

    cols = "".join(_col_html(k, results[k]) for k in profiles)
    report = f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>Provider comparison</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; color: #1a1a1a; background:#faf8f5; }}
  h1 {{ color:#2f5496; }}
  table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
  td.col {{ vertical-align: top; width: {100 // max(len(profiles),1)}%; border:1px solid #d8cfc4; padding:14px; background:#fff; }}
  h3 {{ color:#2f5496; margin:0 0 8px; }}
  h4 {{ margin:14px 0 4px; color:#7b5140; font-size:13px; text-transform:uppercase; letter-spacing:.4px; }}
  .pill {{ display:inline-block; background:#eef2f8; color:#2f5496; border-radius:10px; padding:2px 8px; font-size:12px; font-weight:700; margin-right:4px; }}
  .times {{ color:#666; font-size:12px; margin-top:4px; }}
  .sum {{ font-size:13px; }} ul {{ margin:4px 0; padding-left:18px; font-size:12.5px; }}
  .err {{ color:#a33; font-weight:700; }}
  .ok {{ color:#2a7; font-weight:700; }} .bad {{ color:#c33; font-weight:700; }}
  .job {{ margin-bottom:8px; }}
</style></head><body>
<h1>LLM provider comparison — quality is the gate</h1>
<p>Resume: <code>{_esc(resume_pdf)}</code> · Target ATS {TARGET}. NVIDIA = baseline.
Compare tailored summary / skills / bullets for QUALITY; times are secondary.</p>
<table><tr>{cols}</tr></table>
</body></html>"""

    out_path = Path(os.getenv("REPORT_OUT", str(
        Path(__file__).resolve().parent.parent / "data" / "provider_comparison.html"
    )))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
