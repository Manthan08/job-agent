# Ep 1 Caption + Full Series Plan

## Instagram caption (Ep 1)

I got tired of tailoring my resume for every single job… so I built an AI agent to do it. 🤖

This is Episode 1 of "Building my Job Agent in public" — the system design.

The pipeline:
📄 Parse resume → structured JSON
🗄️ Store everything in SQLite
📊 Score my fit against each job
✍️ Tailor + ATS-check loop until it passes
🎤 LangGraph interview coach from my story bank

Stack: Python, FastAPI, React, NVIDIA Nemotron, LangChain, LangGraph — all free-tier, deployed on Hugging Face Spaces.

⚠️ But there are 2 mistakes hidden in this design — things I got wrong when I started building. Can you spot them? Comment your guess 👇 I'll reveal both in Ep 2.

**Hashtags:**
#buildinpublic #ai #aiagents #langchain #langgraph #python #fastapi #softwareengineer #jobsearch #resumetips #devlife #codingproject #llm #techcareer #100daysofcode

## Series plan — "Building my Job Agent in public"

| Ep | Title / Hook | Content | Visual |
|----|--------------|---------|--------|
| 1 | The System Design | Idea + architecture diagram, 5 phases, stack | Hand-drawn diagram animation |
| 2 | Parsing resumes with LLMs | PDF → structured JSON, LangChain structured output, why regex fails | Code + JSON output side by side |
| 3 | The database layer | SQLite schema, why not Postgres, storing resumes/jobs/scores | Schema sketch + query demo |
| 4 | Scoring resume↔job fit | Prompt design, scoring rubric, funny bad scores | UI showing scores per job |
| 5 | The ATS loop ⭐ | Tailor → score → rewrite loop; before/after ATS score | Loop animation, score climbing |
| 6 | The interview coach | LangGraph agent, story bank, generated prep Qs | Graph diagram + chat demo |
| 7 | The UI | FastAPI + React, quick tour of the workbench | Screen recording of UI |
| 8 | Deploying for $0 | Docker + Hugging Face Spaces, gotchas | Terminal + live URL reveal |
| 9 | Results / lessons | Did it help the actual job search? Metrics, lessons learned | Talking head + stats |

**Cadence suggestion:** 2 eps/week. Ep 5 (ATS loop) is the strongest hook — consider teasing it in every earlier episode.

**Recurring format:** hook (2s) → problem (5s) → build (25s) → result (8s) → CTA (3s).
