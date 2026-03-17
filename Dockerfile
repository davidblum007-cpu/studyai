# ============================================================
# StudyAI – Production Dockerfile
# Base: python:3.11-slim
# ============================================================

FROM python:3.11-slim

# ---------- metadata ----------
LABEL maintainer="StudyAI"
LABEL description="AI-powered study assistant – Flask/Gunicorn production image"

# ---------- system dependencies ----------
# build-essential  : gcc etc. for compiled Python packages
# libpq-dev        : future PostgreSQL support (psycopg2)
# curl             : used by HEALTHCHECK
# sqlite3          : CLI access to database for debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ---------- working directory ----------
WORKDIR /app

# ---------- Python dependencies (layer-cached) ----------
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "gunicorn[gthread]>=22.0.0" \
    && pip install --no-cache-dir -r requirements.txt

# ---------- application source ----------
# .dockerignore excludes .env, *.db, __pycache__, secrets, etc.
COPY . .

# ---------- writable data directory ----------
# SQLite database lives in /app/data so it can be volume-mounted
RUN mkdir -p /app/data

# ---------- non-root user for security ----------
RUN groupadd --system studyai \
    && useradd --system --gid studyai --no-create-home studyai \
    && chown -R studyai:studyai /app

USER studyai

# ---------- port ----------
EXPOSE 8080

# ---------- health check ----------
# Calls the /api/health endpoint every 30s.
# Allows 10s for a response; fails after 3 consecutive failures.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# ---------- start command ----------
# gunicorn reads all tuning knobs from gunicorn.conf.py
CMD ["gunicorn", "--config", "gunicorn.conf.py", "server:app"]
