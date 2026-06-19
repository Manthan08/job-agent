"""Writer (AI-owned plumbing): persist a TailoredResumeModel to data/tailored/ as Markdown.

Mentor split: this is low-interview-value file I/O. The interview-worthy code
(the LCEL chain + prompt that PRODUCES the TailoredResumeModel) is user-written.
"""
from datetime import date
from pathlib import Path

from models.tailored import TailoredResumeModel
from phase4_tailor.artifacts import tailored_artifact_filename

TAILORED_DIR = Path(__file__).resolve().parent.parent / "data" / "tailored"

def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "_none_"


def _skills_md(categories) -> str:
    if not categories:
        return "_none_"
    return "\n".join(
        f"- **{c.category}:** {', '.join(c.skills)}" for c in categories
    )


def _experience_md(jobs) -> str:
    if not jobs:
        return "_none_"
    blocks = []
    for job in jobs:
        end = job.end_date or "Present"
        header = f"### {job.company} — {job.role_title} ({job.start_date} - {end})"
        bullets = "\n".join(f"- {b}" for b in job.bullets) if job.bullets else "_none_"
        blocks.append(f"{header}\n{bullets}")
    return "\n\n".join(blocks)


def save_tailored_resume(
    tailored: TailoredResumeModel,
    candidate_name: str,
    company: str,
    position: str,
    output_dir: Path | None = None,
) -> Path:
    """Write the tailored resume to data/tailored/Name_Company_Position.md.

    Returns the path written. Overwrites an existing file for the same
    candidate/company/position (re-running tailoring is idempotent on disk).
    """
    target_dir = output_dir or TAILORED_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = tailored_artifact_filename(candidate_name, company, position, "md")
    path = target_dir / filename

    content = f"""# Tailored Resume — {candidate_name}
**Target:** {position} @ {company}
**Generated:** {date.today().isoformat()}

## Summary
{tailored.tailored_summary}

## Skills
{_skills_md(tailored.tailored_skills)}

## Experience (reframed for this JD)
{_experience_md(tailored.tailored_experience)}

---
## ⚠️ Skill gaps (address before interview — NOT added to resume)
{_bullets(tailored.skill_gaps)}

## 🌉 Bridge notes (honest equivalents)
{_bullets(tailored.bridge_notes)}
"""
    path.write_text(content, encoding="utf-8")
    return path
