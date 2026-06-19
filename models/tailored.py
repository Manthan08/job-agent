from typing import List
from pydantic import BaseModel, Field


class SkillCategory(BaseModel):
    """One labelled group of skills, e.g. 'Languages & Frameworks' -> [C#, .NET].

    Categorising (instead of one flat list) lets the PDF render the two-column,
    grouped Skills section that matches the original resume, and makes the most
    JD-relevant buckets easy to surface first.
    """

    category: str = Field(
        description="Short category label, e.g. 'Languages & Frameworks', 'Cloud & DevOps', "
        "'Databases & Reporting', 'Architecture', 'Tools', 'Soft Skills'."
    )
    skills: List[str] = Field(
        default_factory=list,
        description="Skills in this category. May wrap JD-critical terms in **bold**. "
        "Only skills the candidate genuinely has or can honestly bridge.",
    )


class TailoredExperienceItem(BaseModel):
    """One job grouped by employer, with tailored bullet points.

    company / role_title / dates are FACTUAL — carry them over unchanged from the
    original resume. Only the bullets are reworded for the target JD.
    """

    company: str = Field(description="Employer name, carried over from the original resume.")
    role_title: str = Field(description="Job title held, carried over from the original resume.")
    start_date: str = Field(description="Start date, carried over from the original resume.")
    end_date: str | None = Field(
        default=None, description="End date (or null/'Present'), carried over from the original."
    )
    bullets: List[str] = Field(
        default_factory=list,
        description="Tailored achievement bullets for this role, in the JD's language but truthful. "
        "Start with strong active verbs; quantify only where the resume already provides numbers. "
        "May wrap JD-critical terms in **bold**.",
    )


class TailoredResumeModel(BaseModel):
    """Structured result of tailoring ONE resume to ONE job description.

    This is the SHAPE the LLM must return. Field descriptions double as
    instructions to the model when used with `llm.with_structured_output`.

    Honest-tailoring policy is encoded structurally: skills the candidate
    genuinely lacks land in `skill_gaps` (flagged, never silently inserted),
    and transferable-but-differently-named skills land in `bridge_notes`.
    The model literally cannot pretend a gap is a real skill.

    Contact info, projects and education are NOT here: they are factual and are
    carried straight from the original resume at render time, not tailored.
    """

    tailored_summary: str = Field(
        description="A rewritten professional summary/headline aimed squarely at THIS job. "
        "Use the JD's terminology, but only claim experience the resume actually evidences."
    )
    tailored_skills: List[SkillCategory] = Field(
        default_factory=list,
        description="Skills grouped into categories, reordered/reframed for this JD. Most "
        "JD-relevant categories first. Include skills the candidate genuinely has (matched), "
        "plus honestly-bridgeable adjacent skills (see bridge_notes). Do NOT include skills the "
        "candidate has never used.",
    )
    tailored_experience: List[TailoredExperienceItem] = Field(
        default_factory=list,
        description="Experience grouped by employer (most JD-relevant role first), each with "
        "tailored bullet points rewritten in the JD's language while staying truthful.",
    )
    skill_gaps: List[str] = Field(
        default_factory=list,
        description="JD requirements the candidate genuinely lacks and cannot honestly bridge. "
        "These are FLAGGED for the candidate to address (learn/prepare), never inserted into the resume.",
    )
    bridge_notes: List[str] = Field(
        default_factory=list,
        description="Honest mappings between a JD requirement and an equivalent skill the candidate has, "
        "where the underlying concept is the same. E.g. 'JD wants RabbitMQ; candidate used Azure Service "
        "Bus — same message-broker concept'.",
    )
