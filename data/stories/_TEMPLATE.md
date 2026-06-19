<!--
STORY BANK — the RAG corpus for Phase 4.
Each file = ONE real accomplishment/project from your career, written in detail.
These get split into chunks, embedded, and stored in Chroma. At generation time the
agent RETRIEVES the most relevant stories per JD requirement and grounds every
tailored bullet / interview answer in them (no invented achievements).

HOW TO WRITE GOOD STORIES (for retrieval quality):
  - One distinct story per file. Copy this template, rename the file (e.g. payments-latency.md).
  - Be concrete: technologies, scale, numbers/metrics, your specific role.
  - Use the STAR shape below — it makes each story self-contained, which chunks cleanly.
  - Repeat key terms naturally (the tech, the domain) — embeddings match on meaning, but
    concrete nouns still help.
  - Keep the leading underscore on this _TEMPLATE.md so the loader can skip it.
-->

# Title: <short name of the accomplishment>

**Role / Context:** <your title, the team, the company, the timeframe>
**Tech:** <languages, frameworks, cloud, datastores, tools>

## Situation
<What was the problem or the business context? Why did it matter?>

## Task
<What were YOU specifically responsible for? What was the goal/constraint?>

## Action
<What did you actually do? Decisions you made and WHY. Tradeoffs you weighed.
Be specific about the engineering — architecture, algorithms, patterns.>

## Result
<Outcome with numbers where possible: latency cut X%, $ saved, users served,
incidents reduced, shipped on date. What did you learn?>

## Skills demonstrated
<comma-separated: e.g. C#, .NET, Azure, distributed systems, performance tuning, leadership>
