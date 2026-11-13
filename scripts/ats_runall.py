"""Run the full ATS pipeline in ONE process; write FINAL to /tmp/ats_final.txt."""
import os
os.environ.setdefault("NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1")
from phase3_score.score_match import score_resume_against_job
from phase4_tailor.keyword_coverage import analyze_keyword_coverage, ats_coverage_score, measure_resume_coverage
from phase4_tailor.tailor_resume import tailor_resume_for_job, tailored_to_text

TARGET=85
RESUME="""Name: Alex Example
Current position: Senior Software Engineer
Email: alex@example.com
Summary: Backend engineer with 8 years building enterprise web applications in C# and .NET.
Skills: C#, .NET, ASP.NET MVC, Web API, SQL Server, Entity Framework, JavaScript, jQuery, Azure App Service, Git, Agile
Experience:
  - Senior Software Engineer @ TechCorp (2019 - Present): Built and maintained ASP.NET Web API services for a logistics platform. Wrote SQL Server stored procedures and optimized queries. Integrated Azure App Service deployments. Mentored two junior developers. Worked in Agile sprints.
  - Software Engineer @ DataSoft (2016 - 2019): Developed ASP.NET MVC web applications. Built REST APIs consumed by Angular front ends. Used Entity Framework for data access. Fixed production defects and improved performance."""
JOB="""Company: CloudScale
Position: Senior .NET Engineer (Cloud / Microservices)
Job description:
Senior .NET Engineer to design and build cloud-native microservices.
Required: strong C# and .NET Core, RESTful Web APIs, microservices architecture,
Azure (App Service, Azure Functions, Azure Service Bus), Docker and Kubernetes,
CI/CD pipelines, SQL Server and Entity Framework Core, unit testing, message-based / event-driven systems.
Nice to have: RabbitMQ or Kafka, Redis caching, gRPC, Domain-Driven Design, observability."""

def log(m):
    open("/tmp/ats_final.txt","a").write(m+"\n")

open("/tmp/ats_final.txt","w").write("")
base=score_resume_against_job(RESUME,JOB).match_score; log(f"baseline_match={base}")
R=analyze_keyword_coverage(RESUME,JOB,target_score=TARGET)
log(f"report direct={len(R.direct_matches)} adjacent={len(R.adjacent_matches)} missing={len(R.missing_keywords)} intent_cov={ats_coverage_score(R)}")
must=[]; best_txt=""; best=0
for p in range(1,4):
    t=tailor_resume_for_job(RESUME,JOB,keyword_report=R,original_score=base,target_score=TARGET,must_cover_keywords=must)
    txt=tailored_to_text(t); m=measure_resume_coverage(txt,R)
    log(f"tailor_pass{p} real_coverage={m['score']} uncovered={[i.keyword for i in m['uncovered']]}")
    if m['score']>=best: best=m['score']; best_txt=txt
    if m['score']>=TARGET or not m['uncovered']: break
    must=[i.keyword for i in m['uncovered']]
rs=score_resume_against_job(best_txt,JOB).match_score
log(f"FINAL baseline={base} ATS_coverage={best} tailored_match={rs}")
log("DONE")
