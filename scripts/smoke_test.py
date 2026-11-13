"""Live smoke test for the NVIDIA Nemotron migration.

Confirms the two things the whole app depends on:
  1. The model answers a plain prompt (connectivity + auth).
  2. `.with_structured_output(PydanticModel)` returns valid structured JSON
     (every phase: parse, score, keyword-coverage, tailor, coach relies on this).

Run:  python -m scripts.smoke_test
Needs NVIDIA_API_KEY in your .env.
"""
from pydantic import BaseModel, Field

from config.settings import get_llm


class _Demo(BaseModel):
    score: int = Field(ge=0, le=100, description="any integer 0-100")
    reason: str = Field(description="one short sentence")


def main() -> None:
    llm = get_llm()

    print("1/2  plain call ...")
    resp = llm.invoke("Reply with exactly: hello")
    print("     ->", getattr(resp, "content", resp))

    print("2/2  structured output ...")
    structured = llm.with_structured_output(_Demo)
    out = structured.invoke(
        "Give a fit score of 88 and a one-line reason for a .NET engineer "
        "applying to a senior .NET role."
    )
    assert isinstance(out, _Demo), f"expected _Demo, got {type(out)}"
    print("     ->", out.model_dump())
    print("\nSUCCESS: Nemotron is wired up and structured output works.")


if __name__ == "__main__":
    main()
