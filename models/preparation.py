"""Structured output for Phase 4.2 — the interview prep pack.

This is the SHAPE the RAG chain must return. Field descriptions double as
instructions to the LLM under `llm.with_structured_output`.

Anti-hallucination is STRUCTURAL (same idea as the tailored-resume model):
every question carries `grounded_in` (which real stories the answer draws on)
and an `is_gap` flag. If the JD wants something the candidate has NO story for,
the model must set is_gap=True and leave the answer as a study pointer rather
than inventing experience.
"""
from typing import List

from pydantic import BaseModel, Field


class PrepQuestion(BaseModel):
    """One likely interview question + a grounded suggested answer."""

    question: str = Field(
        description="A realistic interview question this specific job would ask, "
        "derived from the job description."
    )
    topic: str = Field(
        description="The JD area this question probes (e.g. 'async messaging', "
        "'SQL performance', 'system design')."
    )
    suggested_answer: str = Field(
        description="A strong answer built ONLY from the candidate's retrieved "
        "stories. Reference concrete projects, decisions, and numbers from them. "
        "If is_gap is True, instead give a short, honest pointer on what to study "
        "— never invent experience the stories don't contain."
    )
    grounded_in: List[str] = Field(
        default_factory=list,
        description="Titles/sources of the candidate stories this answer draws on. "
        "Empty when is_gap is True.",
    )
    is_gap: bool = Field(
        default=False,
        description="True if the JD needs this but no retrieved story supports it "
        "(a genuine preparation gap, not a strength).",
    )


class InterviewPrepPack(BaseModel):
    """The full prep pack for one (candidate x job) interview."""

    overview: str = Field(
        description="2-3 sentences on how to approach THIS interview, given the "
        "candidate's strongest relevant stories and the role's focus."
    )
    questions: List[PrepQuestion] = Field(
        default_factory=list,
        description="The prioritized list of likely questions with grounded answers.",
    )
    study_topics: List[str] = Field(
        default_factory=list,
        description="Topics the candidate should revise before the interview — the "
        "JD requirements with weak or no story coverage (the gaps).",
    )
