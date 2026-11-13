# ---- Stage 1: build the React frontend ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin API in production (served by FastAPI below)
RUN npm run build

# ---- Stage 2: Python app that serves API + built frontend ----
FROM python:3.11-slim
# Hugging Face Spaces runs the container as uid 1000; make a matching user so
# SQLite + generated PDFs are writable.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    ANON_COOKIE_SECURE=true \
    JOB_AGENT_DB_PATH=/home/user/app/runtime/db/job-tracker.db \
    JOB_AGENT_DATA_DIR=/home/user/app/runtime/data \
    PORT=7860
WORKDIR $HOME/app
RUN mkdir -p "$HOME/app/runtime/db" "$HOME/app/runtime/data/resumes" \
    "$HOME/app/runtime/data/profiles" "$HOME/app/runtime/data/tailored"

COPY --chown=user requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .
COPY --chown=user --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 7860
# Initialize the SQLite schema, then start the server.
CMD ["sh", "-c", "python -m db.init_db && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
