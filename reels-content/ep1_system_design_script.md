# Reel 1 — "I built an AI agent to run my job search" (System Design)

**Length:** ~45s · **Format:** 9:16, screen recording + diagram animation + voiceover

## Hook options (first 2s — pick one)
1. "I got tired of tailoring my resume for every job. So I built an AI agent to do it."
2. "This is the system design of the AI agent that runs my job search."
3. "8 years as a .NET engineer and I still hated resumes — so I automated them."

## Script + shot plan

| Time | Voiceover | On screen |
|------|-----------|-----------|
| 0–3s | Hook (above) | You on camera OR blank canvas, hook as bold text |
| 3–8s | "The idea: one pipeline that takes my resume and a job description, and outputs a tailored, ATS-friendly resume plus interview prep." | Diagram appears: Resume + JD → ??? → Tailored Resume. Draw-on animation |
| 8–16s | "Here's the design. Five phases. Parse the resume into structured JSON. Store everything in SQLite. Score the fit between me and the job." | Reveal phases 1–3 boxes one by one on the diagram |
| 16–24s | "Then the fun part — an ATS loop: tailor the resume, score it against the JD, and keep rewriting until it passes. Finally, a LangGraph coach generates interview prep from my story bank." | Highlight the tailor→score loop arrow, then phase 5 box |
| 24–34s | "Tech stack: Python, FastAPI backend, React frontend, NVIDIA Nemotron for all the LLM reasoning, LangChain for structured output, LangGraph for the agent. All free-tier." | Stack icons/labels pop in at bottom of diagram |
| 34–42s | "But here's the thing — there are 2 mistakes in this design. Things I got wrong when I started. Can you spot them?" | Diagram zoom-out, big text: "⚠️ 2 mistakes hidden in this design" |
| 42–45s | "Comment what you think they are — I'll reveal them in the next episode." | CTA text: "Comment your guess 👇 · Follow for Ep 2" |

## The 2 intended mistakes (reveal in Ep 2 or pinned comment)
1. **No multi-user design** — single SQLite file, no users table, no auth. Fine for me, breaks the moment anyone else uses it.
2. **Unbounded ATS loop** — tailor→score→rewrite has no retry cap or exit condition in the original design. Synchronous LLM calls that could loop forever (latency + token cost).

(Swap #2 if you had a different mistake in mind — the diagram supports either.)

## Recording notes
- Animate the diagram by revealing groups in Excalidraw (or screen-record while dragging elements in).
- Keep each diagram element on screen ≥1.5s.
- Add captions/subtitles — most reels watched on mute.
- B-roll ideas: VS Code scrolling through phase folders, terminal running smoke_test, the React UI.
