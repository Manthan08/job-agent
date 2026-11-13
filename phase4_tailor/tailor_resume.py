from phase3_score.score_match import resume_to_text, job_to_text
from config.settings import invoke_structured, tailor_model
from db.resume_repository import get_resume_by_id, save_tailored_resume_link
from db.job_repository import get_job_by_id
from langchain_core.prompts import ChatPromptTemplate
from models.keyword_coverage import KeywordCoverageReport
from models.tailored import TailoredResumeModel
from phase4_tailor.save_tailored import save_tailored_resume
from phase4_tailor.render_pdf import render_tailored_pdf


def _tailored_is_populated(t: TailoredResumeModel) -> bool:
    """A usable tailored resume must have a summary, skills, and experience."""
    return bool(
        (t.tailored_summary or "").strip()
        and t.tailored_skills
        and t.tailored_experience
    )


def tailor_resume_for_job(
    resume_text: str,
    job_text: str,
    keyword_report: KeywordCoverageReport | None = None,
    confirmed_skills: list[str] | None = None,
    original_score: int | None = None,
    target_score: int = 85,
    must_cover_keywords: list[str] | None = None,
) -> TailoredResumeModel:
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert resume writer and ATS-optimization specialist. You tailor ONE resume to ONE job description so it ranks well in Applicant Tracking Systems (ATS) and reads well to a recruiter — without keyword stuffing.

CRITICAL OUTPUT RULE:
- You MUST populate tailored_summary, tailored_skills (5-7 categories), and tailored_experience
  (one item per original role). Empty arrays or an empty summary are an INVALID answer.

Writing style:
  - Professional, concise, recruiter-friendly. Start every experience bullet with a strong active verb.
  - No first person ("I", "my", "responsible for"); no filler ("helped with", "assisted in", "worked on").
  - One clear, high-impact achievement per bullet. ~3-4 bullets for the most recent / most JD-relevant
    roles, ~2-3 for older roles. ~5-7 skill categories, prioritized by JD relevance.
  - Lead with impact and scope; quantify ONLY where the resume already provides the number.

Output shape (structured):
  - tailored_summary: a punchy 2-3 sentence summary aimed squarely at THIS job, using the JD's
    terminology for skills the candidate genuinely has.
  - tailored_skills: LIST OF CATEGORIES, each {{category, skills}}. Buckets like "Languages & Frameworks",
    "Cloud & DevOps", "Databases", "Architecture", "Tools", "Soft Skills". Most-JD-relevant first.
  - tailored_experience: LIST GROUPED BY EMPLOYER, each {{company, role_title, start_date, end_date, bullets}}.
    * CARRY company, role_title, start_date, end_date VERBATIM from the original — never invent/alter/reorder/merge.
      Produce exactly one item per original role. Only rewrite the `bullets`.
  - skill_gaps: JD requirements the candidate genuinely lacks (FLAGGED, never on the resume).
  - bridge_notes: honest equivalences (same concept, different name).

Bold rule:
  - **bold** ONLY inside tailored_summary, tailored_skills and tailored_experience bullets, and only on
    JD-critical terms that are MATCHED or honestly ADJACENT/EQUIVALENT. Never bold anything in skill_gaps.

Grounding (anti-hallucination):
  - Use ONLY the resume and JD. Never invent skills, employers, dates, projects, certifications, years, or numbers.

Three-bucket policy — classify every important JD requirement into exactly one:
  1. MATCHED — candidate clearly has it. Reframe in the JD's terminology; surface in skills + experience.
  2. ADJACENT / EQUIVALENT — candidate has a same-concept skill under a different name (e.g. Azure Service Bus
     vs RabbitMQ — both message brokers). Record the honest mapping in bridge_notes; you MAY list it in skills.
  3. MISSING — neither the skill nor a true equivalent. Put in skill_gaps ONLY.

ATS keyword rule: classify FIRST (matched/adjacent/missing), THEN use JD-exact wording for matched/adjacent.
Keywords are a rewording layer, not a truth override.

Keyword coverage report (if provided): treat as the checklist. Cover every direct_match naturally in summary,
skills, or bullets. Cover every adjacent_match with honest bridge wording. Candidate-confirmed skills are
allowed in Skills. Never add missing_keywords as real skills/projects/achievements.

If original_score is 70+, optimize aggressively toward target_score using all truthful direct and adjacent
keywords while keeping the resume readable and honest."""),

        ("user", """Original match score: {original_score}
Target score: {target_score}

Keyword coverage report:
{keyword_report}

Candidate-confirmed skills:
{confirmed_skills}

MUST-COVER keywords (truthful direct/adjacent terms that are currently MISSING from the resume text —
weave each into the summary, skills, or a relevant bullet using honest JD wording):
{must_cover}

Tailor this resume:
{resume_text}

to this job description:
{job_text}
""")
    ])

    keyword_context = (
        keyword_report.model_dump_json(indent=2)
        if keyword_report
        else "No keyword coverage report provided. Apply the three-bucket policy yourself."
    )
    confirmed_skills = confirmed_skills or []
    must_cover = must_cover_keywords or []
    payload = {
        "resume_text": resume_text,
        "job_text": job_text,
        "keyword_report": keyword_context,
        "confirmed_skills": ", ".join(confirmed_skills) or "None provided",
        "original_score": original_score if original_score is not None else "not scored",
        "target_score": target_score,
        "must_cover": ", ".join(must_cover) or "None — first pass.",
    }
    result = invoke_structured(
        TailoredResumeModel, prompt, payload, validate=_tailored_is_populated,
        model=tailor_model(), retries=1,
    )
    if result is None:
        raise RuntimeError("Tailoring failed: model did not return a valid tailored resume.")
    return result


if __name__ == "__main__":
    resume_id = 1
    job_id = 3
    resume = get_resume_by_id(resume_id)
    job = get_job_by_id(job_id)
    resume_text = resume_to_text(resume)
    job_text = job_to_text(job)
    tailored_resume = tailor_resume_for_job(resume_text, job_text)
    print(tailored_resume.model_dump_json(indent=2))
    save_tailored_resume(tailored_resume, resume.get("Name"), job.get("CompanyName"), job.get("Position"))
    pdf_path = render_tailored_pdf(tailored_resume, resume, job.get("CompanyName"), job.get("Position"))
    print(f"Tailored PDF written to: {pdf_path}")
    tailored_resume_id = save_tailored_resume_link(
        original_resume_id=resume_id, job_id=job_id, tailored=tailored_resume,
        candidate_name=resume.get("Name"), candidate_email=resume.get("Email"), pdf_path=pdf_path,
    )
    print(f"Linked tailored resume (ResumeDetails Id={tailored_resume_id}) to application.")


def tailored_to_text(t: TailoredResumeModel) -> str:
    """Flatten a tailored resume into plain text (for coverage scans + re-scoring)."""
    import re as _re

    def _plain(s: str) -> str:
        return _re.sub(r"\*\*(.+?)\*\*", r"\1", s or "")

    lines = [f"Summary: {_plain(t.tailored_summary)}", "Skills:"]
    for cat in t.tailored_skills:
        lines.append(f"  {cat.category}: {', '.join(_plain(s) for s in cat.skills)}")
    lines.append("Experience:")
    for exp in t.tailored_experience:
        end = exp.end_date or "Present"
        lines.append(f"  - {exp.role_title} @ {exp.company} ({exp.start_date} - {end})")
        for b in exp.bullets:
            lines.append(f"      * {_plain(b)}")
    return "\n".join(lines)
