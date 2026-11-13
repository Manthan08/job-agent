"""Benchmark NVIDIA models on the real pipeline (score + keyword + tailor).

For each model it times the three LLM-heavy calls and reports whether structured
output came back populated, so we can lock the fastest model that is still correct.

Run:  python -m scripts.bench_models
Override the list:  BENCH_MODELS="modelA,modelB" python -m scripts.bench_models
"""
import os
import time

# Models to compare (fastest -> strongest). Override via BENCH_MODELS.
DEFAULT_MODELS = [
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia/nemotron-3-super-120b-a12b",
]

TARGET = 85
RESUME = """Name: Alex Example
Current position: Senior Software Engineer
Location: Pune, India
Email: alex@example.com
Summary: Backend engineer with 8 years building enterprise web applications in C# and .NET.
Skills: C#, .NET, ASP.NET MVC, Web API, SQL Server, Entity Framework, JavaScript, jQuery, Azure App Service, Git, Agile
Experience:
  - Senior Software Engineer @ TechCorp (2019 - Present): Built and maintained ASP.NET Web API services for a logistics platform. Wrote SQL Server stored procedures and optimized queries. Integrated Azure App Service deployments. Mentored two junior developers. Worked in Agile sprints.
  - Software Engineer @ DataSoft (2016 - 2019): Developed ASP.NET MVC web applications. Built REST APIs consumed by Angular front ends. Used Entity Framework for data access. Fixed production defects and improved performance."""
JOB = """Company: CloudScale
Position: Senior .NET Engineer (Cloud / Microservices)
Years of experience required: 7
Job description:
Senior .NET Engineer to design and build cloud-native microservices.
Required: strong C# and .NET Core, RESTful Web APIs, microservices architecture,
Azure (App Service, Azure Functions, Azure Service Bus), Docker and Kubernetes,
CI/CD pipelines, SQL Server and Entity Framework Core, unit testing, message-based / event-driven systems.
Nice to have: RabbitMQ or Kafka, Redis caching, gRPC, Domain-Driven Design, observability."""


def _time(label, fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    print(f"    {label:<10} {dt:6.1f}s")
    return out, dt


def bench(model: str) -> None:
    # fast_model()/tailor_model() read these at call time, so set both to `model`.
    os.environ["NVIDIA_MODEL_FAST"] = model
    os.environ["NVIDIA_MODEL_TAILOR"] = model

    from phase3_score.score_match import score_resume_against_job
    from phase4_tailor.keyword_coverage import (
        analyze_keyword_coverage,
        backfill_uncovered_keywords,
        measure_resume_coverage,
    )
    from phase4_tailor.tailor_resume import tailor_resume_for_job, tailored_to_text

    print(f"\n=== {model} ===")
    total = 0.0
    base, dt = _time("score", lambda: score_resume_against_job(RESUME, JOB))
    total += dt
    report, dt = _time(
        "keyword", lambda: analyze_keyword_coverage(RESUME, JOB, target_score=TARGET)
    )
    total += dt
    tailored, dt = _time(
        "tailor",
        lambda: tailor_resume_for_job(
            RESUME, JOB, keyword_report=report, original_score=base.match_score,
            target_score=TARGET,
        ),
    )
    total += dt

    tailored = backfill_uncovered_keywords(tailored, report)
    measured = measure_resume_coverage(tailored_to_text(tailored), report)
    ok = bool(
        (tailored.tailored_summary or "").strip()
        and tailored.tailored_skills
        and tailored.tailored_experience
    )
    print(
        f"    -> total {total:5.1f}s | baseline_match={base.match_score} "
        f"ATS_coverage={measured['score']} | structured_ok={ok} "
        f"(direct={len(report.direct_matches)} adjacent={len(report.adjacent_matches)} "
        f"missing={len(report.missing_keywords)})"
    )


if __name__ == "__main__":
    models = [m.strip() for m in os.getenv("BENCH_MODELS", "").split(",") if m.strip()]
    for m in models or DEFAULT_MODELS:
        try:
            bench(m)
        except Exception as exc:  # keep going so one bad model doesn't abort the run
            print(f"    !! {m} failed: {exc}")
