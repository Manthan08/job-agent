"""Phase 3 — match scoring.

Given one resume + one job, ask the LLM to score the fit (0-100) and explain it,
then persist the result as a JobApplications row.

Split (refined mentor contract):
  AI wrote: models/match.py (MatchResult), db read/write plumbing below.
  YOU write: the scoring CHAIN — the prompt (with a rubric) piped into a
             structured-output LLM, and the .invoke(...) call. See the TODO block.

Run:  python -m phase3_score.score_match
"""

import json
from config.settings import get_llm
from models.match import MatchResult
from db.resume_repository import get_resume_by_id
from db.job_repository import get_job_by_id
from db.application_repository import save_application_to_db
from langchain_core.prompts import ChatPromptTemplate


def _flatten_skill_names(skills: list) -> list[str]:
    """Return displayable skill names from original or tailored skill shapes."""
    names = []
    for item in skills:
        if isinstance(item, str):
            if item.strip():
                names.append(item)
            continue

        if isinstance(item, dict):
            grouped_skills = item.get("skills")
            if isinstance(grouped_skills, list):
                names.extend(_flatten_skill_names(grouped_skills))
                continue

            name = item.get("name") or item.get("skill")
            if name:
                names.append(str(name))

    return names


def _experience_description(item: dict) -> str:
    """Support original resume rows and tailored resume rows."""
    description = item.get("work_description")
    if description:
        return description

    bullets = item.get("bullets")
    if isinstance(bullets, list):
        return " ".join(str(bullet) for bullet in bullets if str(bullet).strip())

    return ""


def resume_to_text(resume: dict) -> str:
    """Flatten a ResumeDetails row into plain text for the prompt.

    Skills/Experience are stored as JSON strings (SQLite has no array type),
    so we parse them back before formatting.
    """
    skills = json.loads(resume["Skills"]) if resume.get("Skills") else []
    experience = json.loads(resume["Experience"]) if resume.get("Experience") else []
    skill_names = _flatten_skill_names(skills)

    lines = [
        f"Name: {resume.get('Name')}",
        f"Current position: {resume.get('CurrentPosition')}",
        f"Location: {resume.get('Location')}",
        f"Email: {resume.get('Email')}",
        f"Summary: {resume.get('Summary')}",
        f"Skills: {', '.join(skill_names)}",
        "Experience:",
    ]
    for item in experience:
        company = item.get("company", "")
        role = item.get("role_title", "")
        start = item.get("start_date", "")
        end = item.get("end_date") or "Present"
        desc = _experience_description(item)
        lines.append(f"  - {role} @ {company} ({start} - {end}): {desc}")
    return "\n".join(lines)


def job_to_text(job: dict) -> str:
    """Flatten a JobDetails row into plain text for the prompt."""
    return (
        f"Company: {job.get('CompanyName')}\n"
        f"Position: {job.get('Position')}\n"
        f"Location: {job.get('JobLocation')}\n"
        f"Years of experience required: {job.get('YearsOfExperienceRequired')}\n"
        f"Job description:\n{job.get('JobDescription')}"
    )


def score_resume_against_job(resume_text: str, job_text: str) -> MatchResult:
    try:
        #1. Build the structured-output LLM:
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an evidence-based job match evaluator.
                        Your task is to compare one candidate resume against one job description and produce a realistic match score from 0 to 100.    

                        Rules:
                        - Use only the resume and job description provided by the user.
                        - Do not invent skills, projects, years of experience, certifications, or achievements.
                        - Score direct evidence higher than keyword mentions.
                        - Treat must-have job requirements as more important than nice-to-have requirements.
                        - Adjacent experience can support the score, but must be clearly labeled as adjacent, not direct.
                        - Penalize missing hard requirements, unclear seniority fit, and missing domain/tool experience.
                        - A low score does not mean the candidate is weak; it only means this specific job is not a strong match.

                        Rubric:
                        - Core requirement match: 60%
                        - Seniority, ownership, and role scope match: 25%
                        - Domain/tooling alignment and transferable experience: 15%

                        Return a structured MatchResult with:
                        - match_score
                        - reasoning
                        - matched_skills
                        - missing_skills"""),
            ("user", 
                        """
                        Compare this resume against this job description.

                        Resume:
                        \n{resume_text}\n

                        Job: \n{job_text}\n

                        Evaluate the match using the rubric from the system message.

                        Be specific:
                        - For each strength, mention the resume evidence.
                        - For each gap, mention the JD requirement that is missing or weak.
                        - Keep the reasoning concise and practical.
                        - Do not mention anything that is not supported by the resume or JD."""
            ),
        ])

        #2. Invoke the chain and return the structured result:
        ## Chains in LLM or LangChain are typically built by piping a prompt into an LLM with a structured output parser. so output is automatically parsed into the MatchResult dataclass.
        structured_llm = get_llm().with_structured_output(MatchResult)
        chain = prompt | structured_llm

        return chain.invoke({"resume_text": resume_text, "job_text": job_text})
    
    except Exception as e:
        print(f"Error during scoring: {e}")
        raise


if __name__ == "__main__":
    # --- plumbing (AI) -------------------------------------------------------
    RESUME_ID = 1   # adjust to your resume row from Phase 1
    JOB_ID = 4      # the .NET + Azure OpenAI + RAG role (your strong match)

    resume = get_resume_by_id(RESUME_ID)
    job = get_job_by_id(JOB_ID)

    if resume is None:
        raise SystemExit(f"No resume with Id={RESUME_ID}. Run Phase 1 first.")
    if job is None:
        raise SystemExit(f"No job with Id={JOB_ID}. Ingest a job first.")

    resume_text = resume_to_text(resume)
    job_text = job_to_text(job)

    # --- the chain (YOU) -----------------------------------------------------
    result = score_resume_against_job(resume_text, job_text)

    # --- plumbing (AI) -------------------------------------------------------
    print(result.model_dump_json(indent=2))

    application_id = save_application_to_db(RESUME_ID, JOB_ID, result)
    print(f"Application saved with ID: {application_id} "
          f"(score: {result.match_score}%)")
