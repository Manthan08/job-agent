# Docker Deployment

This app deploys as one Docker container:

- React is built with Vite during the image build.
- FastAPI serves both `/api/*` and the built React app.
- SQLite, uploaded resumes, generated profiles, and tailored PDFs live under
  `/home/user/app/runtime` in the container.

## Required Environment

Create `.env` from `.env.example` and set at least:

```env
NVIDIA_API_KEY=your-real-key
ANON_IP_HASH_SALT=replace-with-a-random-string
```

For a public HTTPS deploy, keep:

```env
ANON_COOKIE_SECURE=true
```

For local `http://localhost`, use:

```env
ANON_COOKIE_SECURE=false
```

## Local Docker Run

From the `job-agent` folder:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:7860
```

If port `7860` is already in use:

```powershell
$env:HOST_PORT="7861"
docker compose up --build
```

Then open http://localhost:7861.

Stop:

```powershell
docker compose down
```

The Compose volume `resume_buddy_runtime` keeps the SQLite DB and generated
files across restarts. To delete local Docker data completely:

```powershell
docker compose down -v
```

## Direct Docker Run

Use this when you do not want Compose:

```powershell
docker build -t resume-buddy .
docker volume create resume_buddy_runtime
docker run --rm `
  --name resume-buddy `
  -p 7860:7860 `
  --env-file .env `
  -e ANON_COOKIE_SECURE=false `
  -v resume_buddy_runtime:/home/user/app/runtime `
  resume-buddy
```

## VPS / Server Deploy

1. Install Docker and Docker Compose on the server.
2. Copy or clone this repo.
3. Create `.env` on the server with production secrets.
4. Start the app:

```bash
docker compose up -d --build
```

5. Put a reverse proxy in front of it, for example Nginx/Caddy/Cloudflare Tunnel,
   forwarding HTTPS traffic to `http://127.0.0.1:7860`.

Production `.env` should include:

```env
NVIDIA_API_KEY=...
ANON_IP_HASH_SALT=...
ANON_COOKIE_SECURE=true
FRONTEND_ORIGINS=https://your-domain.example
```

Because the production frontend is served by FastAPI on the same origin,
`VITE_API_BASE_URL` should stay empty.

## Health Check

The container health check calls:

```text
http://127.0.0.1:7860/api/health
```

Expected response:

```json
{"status":"ok"}
```
