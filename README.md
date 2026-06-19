# AI Job Application Agent

Learning project for an AI-assisted job application workflow:

1. Parse a resume into structured data.
2. Save resumes and jobs in SQLite.
3. Score resume/job fit.
4. Tailor an ATS-friendly resume for a job description.
5. Generate interview preparation from a story bank.
6. Serve the workflow through FastAPI and a React UI.

## Safety Note

This public copy intentionally excludes real resumes, generated tailored files, SQLite
databases, private story files, local watchlists, and `.env` secrets. Use the example
files in `data/` as templates for your own local data.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with your own OpenAI-compatible endpoint and API keys.

## Common Commands

```powershell
python -m db.init_db
python -m unittest discover tests
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

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

