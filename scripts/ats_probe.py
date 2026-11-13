"""Resumable ATS validation harness (diagnostic). Run repeatedly until FINAL."""
import json, os, pathlib
from phase3_score.score_match import score_resume_against_job
from phase4_tailor.keyword_coverage import (
    analyze_keyword_coverage, ats_coverage_score, measure_resume_coverage)
from phase4_tailor.tailor_resume import tailor_resume_for_job, tailored_to_text
from models.keyword_coverage import KeywordCoverageReport

S = pathlib.Path(os.environ.get("ATS_STATE", "/tmp/ats_state")); S.mkdir(exist_ok=True)
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
Nice to have: RabbitMQ or Kafka, Redis caching, gRPC, Domain-Driven Design, observability.
You will own services end-to-end, mentor engineers, and drive architecture decisions."""

def done(n): return (S/n).exists()
def save(n,o): (S/n).write_text(json.dumps(o, indent=2, default=str))
def load(n): return json.loads((S/n).read_text())

if not done("base.json"):
    b = score_resume_against_job(RESUME, JOB)
    save("base.json", {"score": b.match_score}); print("STAGE base =", b.match_score); raise SystemExit

if not done("report.json"):
    r = analyze_keyword_coverage(RESUME, JOB, target_score=TARGET)
    save("report.json", r.model_dump())
    print("STAGE report: direct=%d adjacent=%d missing=%d intent_cov=%d" % (
        len(r.direct_matches), len(r.adjacent_matches), len(r.missing_keywords), ats_coverage_score(r)))
    raise SystemExit

R = KeywordCoverageReport(**load("report.json"))
base = load("base.json")["score"]

if not done("t1.json"):
    t = tailor_resume_for_job(RESUME, JOB, keyword_report=R, original_score=base, target_score=TARGET)
    txt = tailored_to_text(t); m = measure_resume_coverage(txt, R)
    save("t1.json", t.model_dump()); (S/"t1.txt").write_text(txt)
    save("m1.json", {"score": m["score"], "uncovered": [i.keyword for i in m["uncovered"]]})
    print("STAGE tailor#1: real_coverage=%d uncovered=%s" % (m["score"], [i.keyword for i in m["uncovered"]]))
    raise SystemExit

m1 = load("m1.json")
best_txt = (S/"t1.txt").read_text(); best_cov = m1["score"]

if m1["score"] < TARGET and not done("t2.json"):
    t = tailor_resume_for_job(RESUME, JOB, keyword_report=R, original_score=base,
                              target_score=TARGET, must_cover_keywords=m1["uncovered"])
    txt = tailored_to_text(t); m = measure_resume_coverage(txt, R)
    save("t2.json", t.model_dump()); (S/"t2.txt").write_text(txt)
    save("m2.json", {"score": m["score"], "uncovered": [i.keyword for i in m["uncovered"]]})
    print("STAGE tailor#2: real_coverage=%d uncovered=%s" % (m["score"], [i.keyword for i in m["uncovered"]]))
    raise SystemExit

if done("m2.json"):
    m2 = load("m2.json")
    if m2["score"] >= best_cov:
        best_txt = (S/"t2.txt").read_text(); best_cov = m2["score"]

if not done("rescore.json"):
    rs = score_resume_against_job(best_txt, JOB)
    save("rescore.json", {"score": rs.match_score}); print("STAGE rescore =", rs.match_score); raise SystemExit

print("==== FINAL ====")
print("baseline match   :", base)
print("ATS coverage     :", best_cov, "(target %d)" % TARGET)
print("tailored match   :", load("rescore.json")["score"])
