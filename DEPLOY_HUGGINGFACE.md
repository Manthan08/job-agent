# Deploy free on Hugging Face Spaces

Hugging Face Spaces runs your Docker container for free with no credit card and
keeps it online. Because Nemotron runs on NVIDIA's hosted API, you don't need a
GPU — the free CPU Space is enough.

The app is already deploy-ready: a multi-stage `Dockerfile` builds the React
frontend and serves it together with the FastAPI API on port 7860.

## One-time setup

1. Create a free account at https://huggingface.co/join
2. Click **New** → **Space**.
   - Owner: you. Space name: `resume-buddy` (or anything).
   - License: MIT. **SDK: Docker** → **Blank**.
   - Hardware: **CPU basic (free)**. Visibility: **Public**.
3. Open the Space → **Settings** → **Variables and secrets** → **New secret**:
   - Name `NVIDIA_API_KEY`, value = your NVIDIA key.
   - (Optional) add variable `NVIDIA_MODEL` if you want a specific model.
   - (Optional) add `ANON_IP_HASH_SALT` = any random string.
   - (Optional) add secret `ADMIN_TOKEN` = a long random string. This unlocks the
     usage dashboard at `/admin` (visitor + resume-upload counts). Leave it unset
     and the dashboard stays closed (404).

## Push the code to the Space

A Space is a git repo. The only special requirement is that the Space's
`README.md` starts with the Hugging Face config block (title, `sdk: docker`,
`app_port: 7860`). This repo ships that block in **`SPACE_README.md`**.

```bash
# from inside the job-agent folder
git clone https://huggingface.co/spaces/<your-username>/resume-buddy hf-space
# copy the app into the space (keep the space's .git)
cp -r api config db models phase* webapp frontend requirements.txt Dockerfile .dockerignore hf-space/
cp SPACE_README.md hf-space/README.md          # IMPORTANT: provides sdk/app_port
cd hf-space
git add -A
git commit -m "Deploy Resume Buddy (FastAPI + React + Nemotron)"
git push                                        # use your HF username + an access token as password
```

(Create an access token at https://huggingface.co/settings/tokens — role "write".)

The Space will build the Docker image and go live at
`https://<your-username>-resume-buddy.hf.space` in a few minutes. Watch the
**Logs** tab for build progress.

## Usage dashboard
- Once `ADMIN_TOKEN` is set, open `https://<your-username>-resume-buddy.hf.space/admin`,
  enter the token, and you'll see live counts: unique visitors, resume uploads,
  scores, tailors, an activity-by-day chart, and a full event breakdown.
- The JSON behind it is `GET /api/admin/usage?days=7` (send the token as the
  `X-Admin-Token` header or a `?token=` query param). Without a valid token it
  returns 404, so the numbers are never public.
- ⚠ These counts are **not** all-time: free-tier storage resets on restart (see
  below), so the dashboard shows usage since the Space last (re)started.

## Notes
- Storage on the free tier is ephemeral: the SQLite DB and generated PDFs reset
  when the Space restarts. That's fine here — anonymous sessions and their data
  auto-expire after 14 days by design, and nothing private is meant to persist.
- If you later attach persistent storage or move to a VPS, set
  `JOB_AGENT_DB_PATH` and `JOB_AGENT_DATA_DIR` to the mounted storage location so
  SQLite, uploads, profiles, and tailored PDFs survive restarts.
- The app already enforces per-session rate limits and daily quotas (see the
  `ANON_*` settings in `.env.example`) so a public, free instance stays safe and
  keeps your NVIDIA token usage bounded.
- `ANON_COOKIE_SECURE=true` is set in the Dockerfile because Spaces serve HTTPS.
- To update later, just push new commits to the Space repo.

## Alternative: Render
If you prefer Render (also free): New → Web Service → connect the GitHub repo →
Runtime **Docker** → add `NVIDIA_API_KEY` env var. Note the free tier sleeps
after ~15 min idle (slow first request).
