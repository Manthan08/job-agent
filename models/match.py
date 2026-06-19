from typing import List
from pydantic import BaseModel, Field


class MatchResult(BaseModel):
    """Structured result of scoring one resume against one job description.

    This is the SHAPE the LLM must return. Field descriptions double as
    instructions to the model when used with `llm.with_structured_output`.
    """

    match_score: int = Field(
        ge=0,
        le=100,
        description="Overall fit of the candidate for this job, 0-100. "
        "0 = no relevant overlap, 100 = perfect fit.",
    )
    reasoning: str = Field(
        description="A concise, evidence-based explanation of the score, "
        "citing specific skills/experience from the resume vs the job requirements."
    )
    matched_skills: List[str] = Field(
        default_factory=list,
        description="Skills/requirements from the job the candidate clearly meets.",
    )
    missing_skills: List[str] = Field(
        default_factory=list,
        description="Skills/requirements from the job the candidate lacks or does not evidence.",
    )
