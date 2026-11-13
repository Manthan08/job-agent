import re
import sys
from pathlib import Path
from pypdf import PdfReader
from models.resume import ResumeModel
from config.settings import get_llm
from db.resume_repository import save_resume_to_db


def extract_pdf_text(
    resume_path,
    max_pages: int | None = None,
    max_chars: int | None = None,
) -> str:
    """Read a resume PDF and return its concatenated text.

    `extract_text()` can return None for image/empty pages, so we coalesce to ""
    to avoid a TypeError when concatenating.
    """
    text = ""
    with open(resume_path, "rb") as file:
        reader = PdfReader(file)
        if max_pages is not None and len(reader.pages) > max_pages:
            raise ValueError(f"PDF has too many pages. Limit is {max_pages}.")
        for page in reader.pages:
            text += page.extract_text() or ""
            if max_chars is not None and len(text) > max_chars:
                raise ValueError(
                    f"PDF text is too long. Limit is {max_chars} characters."
                )
    return text


def _resume_is_populated(resume: ResumeModel) -> bool:
    """A usable parse has at least a name and some skills/experience."""
    has_body = bool(resume.skills) or bool(resume.experience)
    return bool((resume.name or "").strip()) and has_body


# Section headers that mark the END of the education block when scanning raw text.
_SECTION_HEADERS = {
    "EXPERIENCE", "WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "EMPLOYMENT",
    "SKILLS", "TECHNICAL SKILLS", "CORE SKILLS", "PROJECTS", "PROJECT",
    "SUMMARY", "PROFESSIONAL SUMMARY", "OBJECTIVE", "CERTIFICATIONS",
    "CERTIFICATION", "ACHIEVEMENTS", "AWARDS", "PUBLICATIONS", "INTERESTS",
    "LANGUAGES", "CONTACT", "VOLUNTEER", "REFERENCES",
}
_EDU_HEADERS = (
    "EDUCATION", "ACADEMIC", "ACADEMICS", "ACADEMIC BACKGROUND",
    "EDUCATIONAL QUALIFICATION", "EDUCATIONAL QUALIFICATIONS", "QUALIFICATIONS",
)


def _looks_like_json(value: str) -> bool:
    return value.lstrip().startswith(("[", "{"))


def _is_section_header(stripped: str) -> bool:
    """A short ALL-CAPS line — the typical resume section divider."""
    up = stripped.upper()
    if up in _SECTION_HEADERS:
        return True
    return stripped == up and stripped.isupper() and len(stripped.split()) <= 4


def _extract_education_section(text: str) -> str | None:
    """Pull the EDUCATION block straight from raw text (no LLM).

    Both Nemotron tiers unreliably drop or over-structure the free-text education
    field, but the section is trivially locatable: find an education header, then
    collect the lines under it until the next section header or a blank gap.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().upper().startswith(_EDU_HEADERS):
            start = i + 1
            break
    if start is None:
        return None

    collected: list[str] = []
    for line in lines[start:]:
        s = line.strip()
        if not s:
            if collected:  # blank line after content closes the block
                break
            continue
        if _is_section_header(s):
            break
        collected.append(s)
        if len(collected) >= 6:  # safety cap — never run away
            break
    if not collected:
        return None
    return " | ".join(collected) if len(collected) > 1 else collected[0]


def _extract_phone(text: str) -> str | None:
    """Regex a phone number from the header region (no LLM)."""
    match = re.search(r"(\+?\d[\d\s().\-]{8,}\d)", text[:700])
    if not match:
        return None
    candidate = match.group(1).strip()
    digits = re.sub(r"\D", "", candidate)
    return candidate if 10 <= len(digits) <= 15 else None


def _backfill_factual_fields(resume: ResumeModel, text: str) -> None:
    """Fill simple factual fields the LLM dropped, deterministically from text.

    Only fires when a field is missing or mangled, so it can never overwrite a
    good LLM extraction — strictly additive.
    """
    if not resume.education or _looks_like_json(resume.education):
        edu = _extract_education_section(text)
        if edu:
            resume.education = edu
    if not resume.phone:
        phone = _extract_phone(text)
        if phone:
            resume.phone = phone


def parse_resume_text(text: str) -> ResumeModel:
    """Extract a structured ResumeModel from raw resume text via the LLM.

    Routed through invoke_structured so a degenerate (near-empty) parse is retried
    on a hotter model — Nemotron guided-JSON otherwise tends to under-populate
    nested fields like experience and skills.
    """
    from langchain_core.prompts import ChatPromptTemplate
    from config.settings import invoke_structured, parse_model

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You extract COMPLETE structured resume data. Capture EVERY field the schema "
         "defines that appears anywhere in the text — not just skills and experience. "
         "Resumes routinely include an EDUCATION section, a SUMMARY/objective, a "
         "PROJECTS section, and a LOCATION; you MUST capture each of these when it is "
         "present. Dropping a section that exists in the text is an invalid answer."),
        ("user",
         """Extract structured resume data from the resume text below.

Rules:
- Use only information present in the resume text.
- Do not guess or add extra information.
- If an optional field is truly missing from the text, set it to null.
- Populate `skills` and `experience` fully.
- `education`: capture the EDUCATION section (degree, field, institution, year)
  whenever the resume has one. Do not leave it null if an education section exists.
- `projects`: capture every project (name, description, technologies_used) when a
  projects section exists.
- `summary`, `location`, `current_position`: fill from the header/profile when present.
- For `urls`, include ONLY the candidate's personal profile/contact links from the
  header/contact area (LinkedIn, portfolio/website, GitHub profile). Do NOT include
  URLs that belong to specific projects, employers, or articles.
- Follow the ResumeModel schema.

Resume text:
{text}
"""),
    ])
    # Parsing is accuracy-critical and one-time per upload, so it runs on the
    # capable parse tier (49B), not the fast/nano tier used for per-tailor calls.
    result = invoke_structured(
        ResumeModel, prompt, {"text": text},
        validate=_resume_is_populated, model=parse_model(),
    )
    if result is None:
        raise ValueError("Could not extract structured data from the resume text.")
    # Deterministically recover the simple factual fields the LLM tends to drop
    # (education, phone) straight from the raw text — additive, never destructive.
    _backfill_factual_fields(result, text)
    return result


if __name__ == "__main__":

        HERE = Path(__file__).resolve().parent.parent
        my_resume_path = HERE / "data" / "resumes" / "sample_resume.pdf"

        resume_path = sys.argv[1] if len(sys.argv) > 1 else my_resume_path

        try:
            text = extract_pdf_text(resume_path)

            # Parse the structured resume to llm via ResumeModel
            resume = parse_resume_text(text)

            print(resume.model_dump_json(indent=2))

            resume_id = save_resume_to_db(resume, resume_path)
            print(f"Resume saved with ID: {resume_id}")

        except Exception as e:
            print(f"An error occurred while parsing the resume: {e}")
