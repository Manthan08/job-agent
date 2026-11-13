# Run Resume Buddy locally (Windows)

You can run it two ways: **Docker** (one container, same as production — recommended
for a quick check) or **native** (venv + Vite dev server, better for active dev).

## Option A: Docker (recommended for a local check)

Requires Docker Desktop running. From the `job-agent` folder:

```powershell
docker compose up --build
```

Open http://localhost:7860 — the React UI and API are served together on one port,
exactly as they will be in production. Stop with Ctrl+C.

If `7860` is already taken, run this first:

```powershell
$env:HOST_PORT="7861"
```

Then open http://localhost:7861.

Compose stores SQLite, uploads, and generated tailored PDFs in the named Docker
volume `resume_buddy_runtime`, so they survive container restarts. If you want a
throwaway run instead:

```powershell
docker build -t resume-buddy .
docker run --rm -p 7860:7860 --env-file .env -e ANON_COOKIE_SECURE=false resume-buddy
```

(First model call can take ~30-60s on the 550b model — that's the model, not a bug.
For snappier local testing set `NVIDIA_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1`
in `.env`.)

## Option B: Native (two processes)

Create `.env` from `.env.example` and add your NVIDIA key. Then install dependencies
and start the FastAPI backend and React frontend.

## 1. Backend (PowerShell, from the `job-agent` folder)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m db.init_db
python -m scripts.smoke_test        # confirms Nemotron + structured output work
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Leave that running. (First model call can take ~30-60s on the 550b model — that's
the model, not a bug. If you want it snappier for local testing, set
`NVIDIA_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1` in `.env`.)

## 2. Frontend (a SECOND PowerShell window, from `job-agent\frontend`)

```powershell
cd frontend
npm install
npm run dev -- --port 5173
```

Open http://127.0.0.1:5173 . The Vite dev server proxies `/api` to the backend on
:8000 automatically.

## 3. Try it
1. Upload a resume PDF (or use the profile builder).
2. Paste a job description.
3. Click **Score**, then **Tailor**. Watch the notice for the ATS coverage score
   and the before -> after fit score. Download the tailored PDF.

## Optional: measure ATS coverage from the command line
```powershell
python -m scripts.ats_runall          # writes results to a temp file; prints DONE
```

## Troubleshooting
- `NVIDIA_API_KEY` error -> check `.env` exists in the `job-agent` folder.
- Slow first response -> expected on the 550b reasoning model; switch to super-49b.
- Port already in use -> change `--port` (and update `frontend/vite.config.js` proxy).
