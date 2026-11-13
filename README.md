# AI Job Application Agent

Learning project for an AI-assisted job application workflow:

1. Parse a resume into structured data.
2. Save resumes and jobs in SQLite.
3. Score resume/job fit.
4. Tailor an ATS-friendly resume for a job description.
5. Generate interview preparation from a story bank.
6. Serve the workflow through FastAPI and a React UI.

Powered by **NVIDIA Nemotron** (via `langchain-nvidia-ai-endpoints`) for all
LLM reasoning, LangChain for structured output, and LangGraph for the coach.

## Safety Note

This public copy intentionally excludes real resumes, generated tailored files, SQLite
databases, private story files, local watchlists, and `.env` secrets. Use the example
files in `data/` as templates for your own local data.

## Setup

Requires Python 3.11+.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set `NVIDIA_API_KEY` (free key from https://build.nvidia.com).
The default model is `nvidia/llama-3.3-nemotron-super-49b-v1`; change `NVIDIA_MODEL`
to use any NVIDIA-hosted model that supports structured output / tool calling.

## Common Commands

```powershell
python -m db.init_db
python -m scripts.smoke_test          # verify Nemotron + structured output
python -m unittest discover tests
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

## Docker Deploy

For the production-style single-container run:

```powershell
docker compose up --build
```

Open http://localhost:7860. See `DEPLOY_DOCKER.md` for VPS/reverse-proxy notes
and `DEPLOY_HUGGINGFACE.md` for Hugging Face Spaces.

For the frontend:

```powershell
cd frontend
npm install
npm run dev -- --port 5173
```

## Local Data

Keep these files local only:

- `data/resumes/`
- `data/tailored/`
- `data/job_watchlist.csv`
- `data/target_companies.csv`
- `db/*.db`
- `.env`

Git also excludes other `.env*` files, runtime data, and generated provider
comparison reports. Keep `.env.example` limited to placeholders. The nested
`resume-buddy/` deployment checkout stays separate from this repository.
