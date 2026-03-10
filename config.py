"""
Zentrale Konfigurationskonstanten für StudyAI.

Alle Magic Numbers und konfigurierbaren Werte an einem Ort.
Einbinden via: from config import CLAUDE_MODEL, MAX_PDF_SIZE_BYTES, ...
"""
import os

# ── KI-Modell ────────────────────────────────────────────────────────────────
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)

# ── Upload-Limits ─────────────────────────────────────────────────────────────
MAX_PDF_SIZE_MB      = int(os.getenv("MAX_PDF_SIZE_MB", "50"))
MAX_PDF_SIZE_BYTES   = MAX_PDF_SIZE_MB * 1024 * 1024
MAX_PDFS_PER_REQUEST = int(os.getenv("MAX_PDFS", "10"))
MAX_PAGES_PER_PDF    = int(os.getenv("MAX_PAGES_PER_PDF", "200"))

# ── Spaced Repetition ─────────────────────────────────────────────────────────
SR_DEFAULT_EF              = 2.5    # Easiness Factor Startwert
SR_MIN_EF                  = 1.3    # Mindestwert für EF
SR_MAX_INTERVAL_DAYS       = 365    # Maximaler Interval in Tagen
SR_BASE_INTERVALS_MINUTES  = [1, 10, 1440, 4320, 10080]  # 1m, 10m, 1d, 3d, 7d

# ── Quiz ──────────────────────────────────────────────────────────────────────
QUIZ_BATCH_SIZE     = 5   # Karten pro API-Batch
QUIZ_MAX_QUESTIONS  = 20  # Maximale Fragen pro Quiz
QUIZ_DEFAULT_COUNT  = 10  # Standardanzahl Fragen

# ── Sicherheit / Validierung ──────────────────────────────────────────────────
MAX_SESSION_NAME_LENGTH      = 100
MAX_FLASHCARD_FRONT_LENGTH   = 500
MAX_FLASHCARD_BACK_LENGTH    = 2000
MAX_FLASHCARD_DIAGRAM_LENGTH = 2000
MAX_THEMES_PER_PLAN          = 500
MAX_CARD_ID_LENGTH           = 64

# ── Paginierung ───────────────────────────────────────────────────────────────
DEFAULT_PAGE_LIMIT  = 50
MAX_PAGE_LIMIT      = 200

# ── Cache ─────────────────────────────────────────────────────────────────────
SEARCH_CACHE_TTL_SECONDS = 3600  # 1 Stunde
SEARCH_CACHE_MAX_SIZE    = 100   # Einträge

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE        = os.getenv("LOG_FILE", "studyai.log")
LOG_MAX_BYTES   = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3

# ── Flask ─────────────────────────────────────────────────────────────────────
DEBUG_MODE  = os.getenv("FLASK_DEBUG", "0") == "1"
SERVER_PORT = int(os.getenv("PORT", "5000"))
SERVER_HOST = os.getenv("HOST", "127.0.0.1")

# ── Rate Limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_ANALYZE   = "3 per minute"
RATE_LIMIT_PLAN      = "5 per minute"
RATE_LIMIT_FLASHCARD = "5 per minute"
RATE_LIMIT_QUIZ      = "5 per minute"
RATE_LIMIT_DEFAULT   = "60 per minute"

# ── Firebase ──────────────────────────────────────────────────────────────────
FIREBASE_COLLECTION = "sessions"
FIREBASE_SYNC_RETRIES = 3
FIREBASE_SYNC_RETRY_BASE_SECONDS = 1  # Exponential: 1s, 2s, 4s

# ── ML / SR Engine ────────────────────────────────────────────────────────────
ML_MIN_TRAINING_SAMPLES = 2
ML_FEATURE_COUNT        = 5   # reps, interval, last_rating, success_rate, log_interval
ML_BOOST_THRESHOLD_HIGH = 0.90
ML_BOOST_THRESHOLD_MID  = 0.75
ML_BOOST_THRESHOLD_LOW  = 0.50

# ── Orchestrator ──────────────────────────────────────────────────────────────
CHUNK_FUTURE_TIMEOUT_SECONDS = 120   # Timeout pro Chunk-Future
MAX_PARALLEL_WORKERS         = int(os.getenv("MAX_WORKERS", "3"))
