from typing import Literal

from pydantic import BaseModel, Field


CoverageBucket = Literal["direct", "adjacent", "missing"]
KeywordImportance = Literal["must_have", "preferred", "nice_to_have"]


class KeywordCoverageItem(BaseModel):
    """One JD keyword/requirement classified against the candidate's evidence."""

    keyword: str = Field(
        description="Normalized keyword or requirement, e.g. 'AWS SQS', 'JavaScript'."
    )
    jd_phrase: str = Field(
        description="The exact or near-exact phrase found in the job description."
    )
    bucket: CoverageBucket = Field(
        description="direct if evidenced, adjacent if honestly bridgeable, missing otherwise."
    )
    importance: KeywordImportance = Field(
        description="How important this requirement appears in the JD."
    )
    resume_evidence: str = Field(
        default="",
        description="Specific resume evidence for direct/adjacent items; empty for true gaps.",
    )
    tailoring_instruction: str = Field(
        description="How the tailor should use or avoid this keyword."
    )


class KeywordCoverageReport(BaseModel):
    """Structured checklist used to maximize honest JD alignment."""

    target_score: int = Field(
        default=85,
        ge=0,
        le=100,
        description="The desired post-tailoring score target.",
    )
    direct_matches: list[KeywordCoverageItem] = Field(
        default_factory=list,
        description="JD keywords the resume clearly supports.",
    )
    adjacent_matches: list[KeywordCoverageItem] = Field(
        default_factory=list,
        description="JD keywords the resume can honestly bridge through equivalent experience.",
    )
    missing_keywords: list[KeywordCoverageItem] = Field(
        default_factory=list,
        description="JD keywords that should not be inserted as resume claims.",
    )
    coverage_summary: str = Field(
        default="",
        description="Short human-readable summary of alignment and remaining risk.",
    )
