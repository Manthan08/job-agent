import re

from langchain_core.prompts import ChatPromptTemplate

from config.settings import invoke_structured, fast_model
from models.keyword_coverage import KeywordCoverageReport


def _report_is_populated(report: KeywordCoverageReport) -> bool:
    """A usable report must classify at least a few JD requirements."""
    total = (
        len(report.direct_matches)
        + len(report.adjacent_matches)
        + len(report.missing_keywords)
    )
    return total >= 3


def analyze_keyword_coverage(
    resume_text: str,
    job_text: str,
    confirmed_skills: list[str] | None = None,
    target_score: int = 100,
) -> KeywordCoverageReport:
    """Classify JD keywords before tailoring so generation stays evidence-gated.

    Nemotron (guided JSON) will leave nested arrays empty unless explicitly told
    not to — so the prompt is deliberately forceful about populating every list,
    and we retry on a degenerate (near-empty) result.
    """
    confirmed_skills = confirmed_skills or []
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are an evidence-based resume/JD keyword coverage analyst.

Your job: classify EVERY important job-description keyword/requirement before resume tailoring.

CRITICAL OUTPUT RULE:
- You MUST populate the arrays. Returning empty arrays is an INVALID answer.
- Extract and classify EVERY important skill, tool, platform, framework, responsibility,
  and seniority signal in the JD (typically 8-20 items). Put each into exactly ONE array:
  direct_matches, adjacent_matches, or missing_keywords.
- For each item fill ALL fields: keyword, jd_phrase, bucket, importance, resume_evidence,
  tailoring_instruction.

Classification:
- direct  = the resume clearly proves this exact skill/requirement (quote evidence).
- adjacent = the resume proves an equivalent/transferable concept under a different name
  (e.g. JD 'Azure Service Bus' vs resume 'message queue'; JD '.NET Core' vs resume '.NET / ASP.NET').
  Write truthful bridge wording in tailoring_instruction.
- missing = the resume proves neither the skill nor an honest equivalent. tailoring_instruction
  must say NOT to put this on the resume as a skill or achievement.

Other rules:
- Use only the provided resume + JD. Candidate-confirmed skills count as direct for the
  skills section (the user can defend them); use them in experience bullets only when resume
  evidence also supports project usage.
- importance: must_have for required/basic-qualification/repeated/core-stack items; preferred or
  nice_to_have otherwise.
- Bias toward 'adjacent' over 'missing' whenever an honest bridge exists — this is how an
  experienced candidate legitimately raises ATS keyword coverage.
- Write a one-line coverage_summary at the end.""",
            ),
            (
                "user",
                """Target score: {target_score}

Resume:
{resume_text}

Candidate-confirmed skills (self-attested, defensible in interview):
{confirmed_skills}

Job description:
{job_text}

Classify every important JD requirement now. Populate all three arrays (empty arrays are invalid).""",
            ),
        ]
    )
    payload = {
        "resume_text": resume_text,
        "job_text": job_text,
        "confirmed_skills": ", ".join(confirmed_skills) or "None provided",
        "target_score": target_score,
    }
    report = invoke_structured(
        KeywordCoverageReport, prompt, payload, validate=_report_is_populated,
        model=fast_model(), retries=1,
    )
    return report or KeywordCoverageReport(target_score=target_score)


def ats_coverage_score(report: KeywordCoverageReport) -> int:
    """Intent-based coverage score from the classification report.

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


def _keyword_present(keyword: str, haystack: str) -> bool:
    """Loose, ATS-style presence check for a keyword inside resume text."""
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    hay = haystack.lower()
    if kw in hay:
        return True
    # token overlap fallback for multi-word keywords (e.g. "CI/CD pipelines")
    tokens = [t for t in re.split(r"[^a-z0-9+#.]+", kw) if len(t) > 2]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in hay)
    return hits >= max(1, len(tokens) - 1)


def measure_resume_coverage(resume_text: str, report: KeywordCoverageReport) -> dict:
    """Measure REAL coverage by scanning the tailored resume TEXT.

    This is the honest 'after' number: a coverable keyword (direct or adjacent)
    only counts if it actually appears in the resume text. Returns the score plus
    the still-uncovered coverable keywords (the checklist for a re-tailor pass).
    """
    weights = {"must_have": 3, "preferred": 2, "nice_to_have": 1}
    covered = 0
    total = 0
    uncovered: list = []

    coverable = [*report.direct_matches, *report.adjacent_matches]
    for item in coverable:
        weight = weights.get(item.importance, 1)
        total += weight
        if _keyword_present(item.keyword, resume_text) or _keyword_present(
            item.jd_phrase, resume_text
        ):
            covered += weight
        else:
            uncovered.append(item)

    for item in report.missing_keywords:
        total += weights.get(item.importance, 1)

    score = round((covered / total) * 100) if total > 0 else 0
    return {"score": score, "uncovered": uncovered, "total_weight": total}


def backfill_uncovered_keywords(tailored, report: KeywordCoverageReport):
    """Deterministically cover still-missing DIRECT keywords — no LLM call.

    After the LLM tailors the resume, some keywords the candidate *genuinely has*
    (direct matches, in the JD's exact wording) can still be absent from the text.
    Listing those in the skills section is both honest and exactly what raises ATS
    keyword coverage — so we append them to an 'Additional Relevant Skills' category
    instead of spending another (slow) LLM tailoring pass.

    Honesty gate: ONLY `direct` items are inserted. `adjacent` items use a different
    tool name than the candidate actually used (e.g. JD 'AWS SQS' vs resume 'Azure
    Service Bus'), so injecting the raw JD term would be a false claim — those are
    left to the LLM's bridge wording. `missing` items are never added.

    Returns a (possibly) updated copy of the tailored resume.
    """
    from models.tailored import SkillCategory
    from phase4_tailor.tailor_resume import tailored_to_text

    text = tailored_to_text(tailored)
    seen = {s.lower() for cat in tailored.tailored_skills for s in cat.skills}
    additions: list[str] = []
    # Source of truth = membership in direct_matches (genuinely possessed), not the
    # per-item bucket label, which the model sometimes sets inconsistently.
    for item in report.direct_matches:
        if _keyword_present(item.keyword, text) or _keyword_present(item.jd_phrase, text):
            continue
        term = (item.keyword or item.jd_phrase or "").strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            additions.append(term)
    if not additions:
        return tailored

    backfill_label = "Additional Relevant Skills"
    skills = list(tailored.tailored_skills)
    for cat in skills:
        if cat.category.strip().lower() == backfill_label.lower():
            cat.skills = list(cat.skills) + additions
            break
    else:
        skills.append(SkillCategory(category=backfill_label, skills=additions))
    return tailored.model_copy(update={"tailored_skills": skills})


def bold_matched_keywords(tailored, report: KeywordCoverageReport):
    """Deterministically **bold** JD-matched keywords the model left unbolded.

    The tailor prompt asks the model to wrap JD-critical terms in **bold**, but the
    120b complies inconsistently, so resumes sometimes render with no emphasis at
    all. Bolding is pure PRESENTATION on terms already classified as genuinely
    present (direct) or honestly equivalent (adjacent) — so we can guarantee it
    deterministically without touching truthfulness (mirrors backfill_uncovered_keywords).

    Conservative by design:
      - only IMPORTANT (must_have/preferred) matched/adjacent terms,
      - whole-word, case-insensitive, longest term first,
      - and ONLY in fields where the model emitted NO bold of its own, so we never
        fight, nest, or double-up the model's choices.
    """
    import re

    terms: list[str] = []
    for item in [*report.direct_matches, *report.adjacent_matches]:
        if item.importance not in ("must_have", "preferred"):
            continue
        for term in (item.keyword, item.jd_phrase):
            term = (term or "").strip()
            if len(term) >= 2:
                terms.append(term)
    terms = sorted(set(terms), key=len, reverse=True)
    if not terms:
        return tailored

    # One alternation, longest-first, whole-word. A single pass over a field with no
    # existing '**' yields non-overlapping, non-nested matches.
    combined = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(t) for t in terms) + r")(?!\w)",
        re.IGNORECASE,
    )

    def emphasize(text: str) -> str:
        if not text or "**" in text:  # model already bolded this field — respect it
            return text
        return combined.sub(r"**\1**", text)

    skills = [
        cat.model_copy(update={"skills": [emphasize(s) for s in cat.skills]})
        for cat in tailored.tailored_skills
    ]
    experience = [
        exp.model_copy(update={"bullets": [emphasize(b) for b in exp.bullets]})
        for exp in tailored.tailored_experience
    ]
    return tailored.model_copy(
        update={
            "tailored_summary": emphasize(tailored.tailored_summary),
            "tailored_skills": skills,
            "tailored_experience": experience,
        }
    )
