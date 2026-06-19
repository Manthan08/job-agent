from phase3_score.score_match import resume_to_text, job_to_text
from config.settings import get_llm
from db.resume_repository import get_resume_by_id, save_tailored_resume_link
from db.job_repository import get_job_by_id
from langchain_core.prompts import ChatPromptTemplate
from models.keyword_coverage import KeywordCoverageReport
from models.tailored import TailoredResumeModel
from phase4_tailor.save_tailored import save_tailored_resume
from phase4_tailor.render_pdf import render_tailored_pdf


def tailor_resume_for_job(
    resume_text: str,
    job_text: str,
    keyword_report: KeywordCoverageReport | None = None,
    confirmed_skills: list[str] | None = None,
    original_score: int | None = None,
    target_score: int = 85,
) -> TailoredResumeModel:
    
    try:
        #1. Build the structured-output LLM:
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert resume writer and ATS-optimization specialist. You tailor ONE resume to ONE job description so it ranks well in Applicant Tracking Systems (ATS) and reads well to a recruiter — without keyword stuffing.

                          Writing style:
                            - Professional, concise, recruiter-friendly tone.
                            - Start every experience bullet with a strong active verb.
                            - No first person ("I", "my", "responsible for"); no passive or filler ("helped with", "assisted in", "worked on").
                            - One clear achievement per bullet; tight grammar.
                            - Keep bullets lean: ~3-4 for the most recent / most JD-relevant roles and ~2-3 for older roles; ~5-7 skill categories, prioritized by JD relevance; drop the least relevant.

                          Output shape (structured):
                            - tailored_summary: one rewritten summary aimed squarely at THIS job.
                            - tailored_skills: a LIST OF CATEGORIES. Each item = {{category, skills}}. Group skills into sensible
                              buckets such as "Languages & Frameworks", "Cloud & DevOps", "Databases & Reporting",
                              "Architecture", "Tools", "Soft Skills". Order categories most-JD-relevant first; within a
                              category order skills most-relevant first.
                            - tailored_experience: a LIST GROUPED BY EMPLOYER. Each item = {{company, role_title, start_date, end_date, bullets}}.
                              * CARRY company, role_title, start_date and end_date VERBATIM from the original resume — never invent,
                                alter, reorder, or merge them. Produce exactly one item per original role.
                              * Only rewrite the `bullets` for the target JD.
                            - skill_gaps: JD requirements the candidate genuinely lacks (flagged, NEVER put on the resume).
                            - bridge_notes: honest equivalences (same underlying concept, different name).

                          Bold rule:
                            - **bold** is allowed ONLY inside tailored_summary, tailored_skills and tailored_experience bullets.
                            - Bold only JD-critical terms that are MATCHED or honestly ADJACENT / EQUIVALENT.
                            - Never bold anything in skill_gaps; never move a missing skill onto the resume just because it is ATS-important.

                          Grounding (anti-hallucination):
                            - Use ONLY the resume and job description provided by the user.
                            - Never invent skills, employers, dates, projects, certifications, years of experience, or numbers.
                            - Quantify impact only where the resume already provides the number.

                          Three-bucket policy — classify every important JD requirement into exactly one:
                            1. MATCHED — the candidate clearly has it. Reframe it in the JD's terminology and surface it in
                               tailored_skills and tailored_experience.
                            2. ADJACENT / EQUIVALENT — the candidate has a different-named skill built on the SAME underlying
                               concept (e.g. JD wants RabbitMQ, candidate used Azure Service Bus — both message brokers). Record
                               the honest mapping in bridge_notes, and you MAY list it in tailored_skills.
                            3. MISSING — the candidate has neither the skill nor a true equivalent. Put it in skill_gaps ONLY.

                          ATS keyword rule: classify FIRST (matched / adjacent / missing), THEN use JD-exact wording. Keywords are
                          a rewording layer, not a truth override.

                          Keyword coverage report:
                            - If provided, treat it as the checklist for maximizing JD alignment.
                            - Cover every direct_match naturally in summary, skills, or bullets.
                            - Cover every adjacent_match with honest bridge wording. Example: Azure Service Bus may support
                              "message queue" / "event-driven" wording, but must not become a direct AWS SQS claim.
                            - Candidate-confirmed skills are allowed in the Skills section because the user says they can
                              defend them. Use them in experience bullets only when the resume also supports project/work usage.
                            - Never add missing_keywords as real skills, tools, projects, or achievements.
                            - If original_score is 70 or higher, optimize aggressively toward target_score using all truthful
                              direct and adjacent keywords while keeping the resume readable.
                           """),

            ("user", """Original match score: {original_score}
Target score: {target_score}

Keyword coverage report:
{keyword_report}

Candidate-confirmed skills:
{confirmed_skills}

Tailor this resume:
{resume_text}

to this job description:
{job_text}
            """)
        ])

        structured_llm = get_llm().with_structured_output(TailoredResumeModel)
        chain = prompt | structured_llm
        keyword_context = (
            keyword_report.model_dump_json(indent=2)
            if keyword_report
            else "No keyword coverage report provided. Apply the three-bucket policy yourself."
        )
        confirmed_skills = confirmed_skills or []
        return chain.invoke(
            {
                "resume_text": resume_text,
                "job_text": job_text,
                "keyword_report": keyword_context,
                "confirmed_skills": ", ".join(confirmed_skills) or "None provided",
                "original_score": original_score if original_score is not None else "not scored",
                "target_score": target_score,
            }
        )
    
    except Exception as e:
        print(f"Error during tailoring: {e}")
        raise e
    
if __name__ == "__main__":
    
    resume_id = 1
    job_id = 3

    resume = get_resume_by_id(resume_id)
    job = get_job_by_id(job_id)

    resume_text = resume_to_text(resume)
    job_text = job_to_text(job)

    tailored_resume = tailor_resume_for_job(resume_text, job_text)
    print(tailored_resume.model_dump_json(indent=2))

    save_tailored_resume(
        tailored_resume,
        resume.get("Name"),
        job.get("CompanyName"),
        job.get("Position"),
    )

    pdf_path = render_tailored_pdf(
        tailored_resume,
        resume,
        job.get("CompanyName"),
        job.get("Position"),
    )
    print(f"Tailored PDF written to: {pdf_path}")

    tailored_resume_id = save_tailored_resume_link(
        original_resume_id=resume_id,
        job_id=job_id,
        tailored=tailored_resume,
        candidate_name=resume.get("Name"),
        candidate_email=resume.get("Email"),
        pdf_path=pdf_path,
    )
    print(f"Linked tailored resume (ResumeDetails Id={tailored_resume_id}) to application.")
