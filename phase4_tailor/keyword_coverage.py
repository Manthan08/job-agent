from langchain_core.prompts import ChatPromptTemplate

from config.settings import get_llm
from models.keyword_coverage import KeywordCoverageReport


def analyze_keyword_coverage(
    resume_text: str,
    job_text: str,
    confirmed_skills: list[str] | None = None,
    target_score: int = 100,
) -> KeywordCoverageReport:
    """Classify JD keywords before tailoring so generation stays evidence-gated."""
    confirmed_skills = confirmed_skills or []
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are an evidence-based resume/JD keyword coverage analyst.

Your job is to classify important job-description keywords before resume tailoring.

Rules:
- Use only the provided resume and job description.
- Classify every important JD skill, tool, platform, framework, responsibility, and seniority signal.
- direct = resume clearly proves this exact skill or requirement.
- adjacent = resume proves an equivalent or transferable concept under a different name.
- missing = resume does not prove the skill and there is no honest equivalent.
- Candidate-confirmed skills are real self-attested skills the user says they can defend in an interview, even if the original resume omitted them.
- Treat candidate-confirmed skills as direct for the skills section. Use them in experience bullets only when resume evidence also supports project/work usage.
- For adjacent items, write bridge wording that is truthful. Example: Azure Service Bus can support "message queue" or "event-driven messaging" language, but it must not become a direct AWS SQS claim.
- For missing items, the tailoring instruction must say not to put the keyword into the resume as a skill or achievement.
- Prefer must_have for repeated requirements, required/basic qualifications, and core stack items.
- Return a structured KeywordCoverageReport.""",
            ),
            (
                "user",
                """Target score: {target_score}

Resume:
{resume_text}

Candidate-confirmed skills not found or not emphasized in the resume:
{confirmed_skills}

Job description:
{job_text}

Build the keyword coverage report.""",
            ),
        ]
    )
    structured_llm = get_llm().with_structured_output(KeywordCoverageReport)
    chain = prompt | structured_llm
    return chain.invoke(
        {
            "resume_text": resume_text,
            "job_text": job_text,
            "confirmed_skills": ", ".join(confirmed_skills) or "None provided",
            "target_score": target_score,
        }
    )


def ats_coverage_score(report: KeywordCoverageReport) -> int:
    """Keyword coverage score separate from evidence-based match score.

    Direct and adjacent items both count as covered because ATS/recruiter keyword
    scanning can see the JD language. Missing items remain uncovered.
    """
    weights = {"must_have": 3, "preferred": 2, "nice_to_have": 1}
    covered = 0
    total = 0

    for item in [*report.direct_matches, *report.adjacent_matches]:
        weight = weights.get(item.importance, 1)
        covered += weight
        total += weight

    for item in report.missing_keywords:
        total += weights.get(item.importance, 1)

    if total <= 0:
        return 0
    return round((covered / total) * 100)
