"""Benchmark candidate FAST-tier models on speed AND honest ATS coverage.

The fast tier (score, keyword-classify, coach) is meant to run on a smaller,
quicker Nemotron than the quality-sensitive tailor tier. A blind swap is risky:
on 2026-06-19 the dense 49b came out BOTH slower and worse than the 120b MoE.
So gate any change on data — run this, and only set NVIDIA_MODEL_FAST in .env to
a candidate that is clearly faster while keeping ATS coverage at/above the 120b
baseline.

What it measures, per model, on one resume/JD pair:
  - analyze_keyword_coverage  -> seconds + ats_coverage_score(report)
  - score_resume_against_job  -> seconds + match_score

Usage:
    python -m scripts.benchmark_fast_model
    python -m scripts.benchmark_fast_model nvidia/nemotron-3-super-120b-a12b nvidia/nemotron-nano-9b-v2
    RESUME_ID=1 JOB_ID=4 python -m scripts.benchmark_fast_model

Reads NVIDIA_API_KEY etc. from .env (same as the app). Each model = real API
calls, so this costs a little quota. Keep the candidate list short.
"""

import os
import sys
import time

# Default candidates: the current locked 120b baseline + two nano candidates to
# beat it. All ids verified live on the integrate.api.nvidia.com /v1/models list
# (2026-06-20). The 30b-a3b is the same Nemotron-3 generation as the baseline with
# only ~3B active params, so it's the safest speed-for-quality trade.
DEFAULT_CANDIDATES = [
    "nvidia/nemotron-3-super-120b-a12b",   # current baseline (keep tailor on this)
    "nvidia/nemotron-3-nano-30b-a3b",      # primary fast-tier candidate
    "nvidia/nvidia-nemotron-nano-9b-v2",   # smaller/faster secondary
]

SAMPLE_RESUME = """Name: Sample Candidate
Current position: Senior Software Engineer
Location: Remote
Email: sample@example.com
Summary: Backend engineer with 8 years building C#/.NET services on Azure, plus
Python automation and early LLM/LangChain work.
Skills: C#, .NET Core, ASP.NET, Azure, SQL Server, REST APIs, Docker, Python,
message queues, CI/CD, microservices, unit testing
Experience:
  - Senior Software Engineer @ Acme (2019 - Present): Built and owned .NET Core
    microservices on Azure (App Service, Service Bus, Key Vault). Designed REST
    APIs, SQL schemas, and CI/CD pipelines. Mentored two engineers.
  - Software Engineer @ Globex (2016 - 2019): Shipped C#/ASP.NET features and SQL
    reporting; introduced automated tests and Docker-based local environments.
"""

SAMPLE_JOB = """Company: Example Corp
Position: Senior Backend Engineer (.NET / Azure)
Location: Remote
Years of experience required: 6+
Job description:
We need a senior backend engineer fluent in C# and .NET Core building cloud
services on Azure. Must have: REST API design, SQL, Azure Service Bus or similar
messaging, CI/CD, Docker, and unit/integration testing. Nice to have: Kubernetes,
event-driven architecture, and exposure to AI/LLM features.
"""


def _load_sample() -> tuple[str, str]:
    """Prefer a real DB row (RESUME_ID/JOB_ID) so the benchmark reflects real data."""
    resume_id = os.getenv("RESUME_ID")
    job_id = os.getenv("JOB_ID")
    if resume_id and job_id:
        try:
            from db.resume_repository import get_resume_by_id
            from db.job_repository import get_job_by_id
            from phase3_score.score_match import resume_to_text, job_to_text

            resume = get_resume_by_id(int(resume_id))
            job = get_job_by_id(int(job_id))
            if resume and job:
                print(f"Using DB resume #{resume_id} + job #{job_id}.")
                return resume_to_text(resume), job_to_text(job)
            print(f"Resume/job not found for those ids; using built-in sample.")
        except Exception as exc:  # noqa: BLE001 - benchmark, never hard-fail on setup
            print(f"Could not load DB rows ({exc}); using built-in sample.")
    return SAMPLE_RESUME, SAMPLE_JOB


def _bench_one(model: str, resume_text: str, job_text: str) -> dict:
    # The phase functions read fast_model() -> NVIDIA_MODEL_FAST at call time,
    # so pinning the env is enough to route both calls through the candidate.
    os.environ["NVIDIA_MODEL_FAST"] = model

    from phase4_tailor.keyword_coverage import analyze_keyword_coverage, ats_coverage_score
    from phase3_score.score_match import score_resume_against_job

    t0 = time.perf_counter()
    report = analyze_keyword_coverage(resume_text, job_text)
    kw_secs = time.perf_counter() - t0
    coverage = ats_coverage_score(report) if report else 0

    t1 = time.perf_counter()
    try:
        match = score_resume_against_job(resume_text, job_text)
        match_score = match.match_score
    except Exception as exc:  # noqa: BLE001
        match_score = -1
        print(f"  score failed: {exc}")
    score_secs = time.perf_counter() - t1

    return {
        "model": model,
        "kw_secs": kw_secs,
        "coverage": coverage,
        "score_secs": score_secs,
        "match_score": match_score,
        "total_secs": kw_secs + score_secs,
    }


def main() -> None:
    candidates = sys.argv[1:] or DEFAULT_CANDIDATES
    resume_text, job_text = _load_sample()

    print(f"\nBenchmarking {len(candidates)} model(s)\n" + "=" * 72)
    rows = []
    for model in candidates:
        print(f"\n-> {model}")
        rows.append(_bench_one(model, resume_text, job_text))

    print("\n" + "=" * 72)
    header = f"{'model':<42} {'kw_s':>6} {'cov%':>5} {'scr_s':>6} {'match':>6} {'total_s':>8}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['model']:<42} {r['kw_secs']:>6.1f} {r['coverage']:>5} "
            f"{r['score_secs']:>6.1f} {r['match_score']:>6} {r['total_secs']:>8.1f}"
        )
    print(
        "\nDecision rule: pick the fastest candidate whose cov% is at/above the "
        "120b baseline. Only then set NVIDIA_MODEL_FAST in .env.\n"
    )


if __name__ == "__main__":
    main()
