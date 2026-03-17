# ============================================================
# StudyAI – gunicorn.conf.py
# Production Gunicorn configuration
# Docs: https://docs.gunicorn.org/en/stable/settings.html
# ============================================================

import multiprocessing
import os

# ------------------------------------------------------------------
# Server socket
# ------------------------------------------------------------------
bind = "0.0.0.0:8080"

# ------------------------------------------------------------------
# Worker processes
# Formula: cpu_count * 2 + 1, capped at 8.
# gthread workers are required for SSE streaming (each request holds
# an open connection; threads allow other requests to be served
# concurrently without spawning a new process per connection).
# ------------------------------------------------------------------
# SQLite WAL mode supports concurrent readers but only ONE writer at
# a time.  Capping workers at 4 avoids lock-queue pile-ups.
# Upgrade path: switch to PostgreSQL and raise to cpu_count*2+1.
_cpu = multiprocessing.cpu_count()
workers = min(_cpu, 4)          # was min(_cpu*2+1, 8) – reduced for SQLite safety
worker_class = "gthread"
threads = 4                     # 4 workers × 4 threads = 16 concurrent slots

# ------------------------------------------------------------------
# Timeouts
# ⚠️  MUST be synchronised with nginx proxy_read_timeout (nginx.conf).
#     Set nginx to 310s so Gunicorn (300s) always kills the worker
#     first, which gives a clean 504 rather than a mid-stream 502.
# ------------------------------------------------------------------
timeout = 300
graceful_timeout = 30
keepalive = 5

# ------------------------------------------------------------------
# Request recycling
# Recycling workers periodically prevents slow memory leaks.
# Jitter avoids all workers restarting at the same moment.
# ------------------------------------------------------------------
max_requests = 1000
max_requests_jitter = 100

# ------------------------------------------------------------------
# Logging (stdout/stderr so Docker captures them automatically)
# ------------------------------------------------------------------
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sµs'

# ------------------------------------------------------------------
# Application preloading
# preload_app = False is REQUIRED for SQLite thread-safety.
# With preload_app = True, the DB connection would be shared across
# forked workers, causing "database is locked" errors under load.
# ------------------------------------------------------------------
preload_app = False

# ------------------------------------------------------------------
# Performance
# /dev/shm is a RAM-backed tmpfs; using it for the worker heartbeat
# files avoids disk I/O and is significantly faster on Linux.
# ------------------------------------------------------------------
worker_tmp_dir = "/dev/shm"

# ------------------------------------------------------------------
# Proxy / forwarded headers
# Required when Gunicorn sits behind Nginx or any other reverse proxy.
# ------------------------------------------------------------------
forwarded_allow_ips = "*"
secure_scheme_headers = {"X-Forwarded-Proto": "https"}

# ------------------------------------------------------------------
# Process naming (visible in `ps aux`)
# ------------------------------------------------------------------
proc_name = "studyai"

# ------------------------------------------------------------------
# Server hooks – lifecycle callbacks
# ------------------------------------------------------------------

def on_starting(server):
    server.log.info(
        "StudyAI Gunicorn starting – workers=%d class=%s threads=%d",
        workers, worker_class, threads
    )


def post_fork(server, worker):
    server.log.info("Worker spawned (pid=%d)", worker.pid)


def worker_exit(server, worker):
    server.log.info("Worker exited (pid=%d)", worker.pid)


def on_exit(server):
    server.log.info("StudyAI Gunicorn shut down cleanly.")
