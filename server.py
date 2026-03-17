"""
StudyAI – Flask API Server
==========================
Endpoints:
  GET    /                              → Web-UI (index.html)
  GET    /api/health                   → Health-Check (Firebase-Status, Model)
  GET    /api/config                   → Frontend-Konfiguration (Firebase Web Config)

  GET    /api/auth/me                  → Aktueller User (aus Firebase-Token)

  POST   /api/analyze                  → PDF-Upload & Analyse (SSE-Streaming)
  POST   /api/plan                     → Lernplan generieren
  POST   /api/flashcards               → Flashcards generieren (SSE-Streaming)
  POST   /api/export/anki              → Anki-Deck (.apkg) herunterladen

  POST   /api/sr/rate                  → SM-2: Karte bewerten
  POST   /api/sr/due                   → SM-2: Fällige Karten abfragen
  POST   /api/sr/train                 → ML-Modell auf Review-Logs trainieren

  POST   /api/quiz/generate            → MC-Fragen generieren (SSE-Streaming)

  POST   /api/sessions                 → Session erstellen
  GET    /api/sessions                 → Alle Sessions auflisten
  GET    /api/sessions/<id>            → Session laden
  PATCH  /api/sessions/<id>            → Session umbenennen
  DELETE /api/sessions/<id>            → Session löschen
  POST   /api/sessions/<id>/save       → Session-State speichern
  GET    /api/sessions/<id>/export     → Session als JSON exportieren
  POST   /api/sessions/import          → Session aus JSON importieren

  GET    /api/security/audit           → Audit-Logs (nur localhost)
  GET    /api/security/stats           → Security-Statistiken (nur localhost)

  POST   /api/user/delete              → GDPR Art. 17: Account + Daten löschen
  POST   /api/user/export              → GDPR Art. 20: Alle Daten als ZIP exportieren

  POST   /api/sessions/<id>/flashcards           → Flashcard hinzufügen (Phase 4)
  GET    /api/sessions/<id>/flashcards/<card_id> → Einzelne Flashcard abrufen
  PATCH  /api/sessions/<id>/flashcards/<card_id> → Flashcard bearbeiten
  DELETE /api/sessions/<id>/flashcards/<card_id> → Flashcard löschen

  GET    /api/billing/usage            → Aktueller Verbrauch + Limits
  GET    /api/user/profile             → User-Profil (Tier + Usage)
  POST   /api/billing/checkout         → Stripe Checkout starten
  POST   /api/billing/portal           → Stripe Abo-Verwaltung
  POST   /api/webhooks/stripe          → Stripe Webhook

  GET    /privacy.html                 → Datenschutzerklärung
  GET    /terms.html                   → Nutzungsbedingungen

  GET    /api/sessions/<id>/chat       → Chat-History laden (Phase 5)
  POST   /api/sessions/<id>/chat       → Frage stellen + SSE-Streaming-Antwort (Phase 5)
  DELETE /api/sessions/<id>/chat       → Chat-History löschen (Phase 5)

  POST   /api/sessions/<id>/share      → Share-Token erstellen (Phase 6)
  GET    /api/sessions/<id>/share      → Aktiven Share-Token abrufen (Phase 6)
  DELETE /api/sessions/<id>/share      → Share-Token widerrufen (Phase 6)
  GET    /shared/<token>               → Öffentliche Deck-Ansicht (Phase 6)

  POST   /api/sessions/<id>/flashcards/<card_id>/improve → KI-Karten-Verbesserung (Phase 6)

  GET    /api/gamification/stats       → Streak + Badges des eingeloggten Users (Phase 6)
  POST   /api/gamification/check       → Neue Badges prüfen + vergeben (Phase 6)

  GET    /api/admin/stats              → Plattform-Statistiken (nur Admins, Phase 6)
"""

import os
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import tempfile
import threading
import time
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ── Sentry Error-Tracking (optional – deaktiviert wenn SENTRY_DSN fehlt) ─────
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=_sentry_dsn,
            integrations=[
                FlaskIntegration(transaction_style="url"),
                LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
            ],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.05")),
            environment=os.getenv("FLASK_ENV", "development"),
            release=os.getenv("APP_VERSION", "1.0.0"),
            send_default_pii=False,   # GDPR: keine PII an Sentry senden
        )
        print("[Sentry] Initialized – environment:", os.getenv("FLASK_ENV", "development"))
    except ImportError:
        print("[Sentry] sentry-sdk nicht installiert – Error-Tracking deaktiviert.")
        print("         Installieren: pip install sentry-sdk[flask]")

from flask import Flask, request, jsonify, send_from_directory, send_file, Response, stream_with_context, session as flask_session
from flask_cors import CORS
from dotenv import load_dotenv
import genanki
from database import Database
from agents.quiz_agent import QuizAgent
from agents.security_manager import SecurityManager
from firebase_sync import FirebaseSync
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# .env laden (override=True damit System-Env-Vars überschrieben werden)
load_dotenv(override=True)

from agents.orchestrator import OrchestratorAgent
from agents.security_agent import SecurityError
from agents.planner_agent import PlannerAgent
from agents.flashcard_agent import FlashcardAgent
from agents.ml_sr_engine import MLSpacedRepetitionEngine, get_engine_for_user
from agents.chat_agent import ChatAgent
from agents.improve_card_agent import ImproveCardAgent
from admin import is_admin, estimate_cost_usd

# ── Logging ──────────────────────────────────────────────────────────────────
_log_file_handler = RotatingFileHandler(
    "studyai.log",
    maxBytes=5 * 1024 * 1024,  # 5 MB pro Datei
    backupCount=3,              # studyai.log, studyai.log.1, studyai.log.2, studyai.log.3
    encoding="utf-8",
)
_log_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
    datefmt="%H:%M:%S",
))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        _log_file_handler,
    ],
)
logger = logging.getLogger(__name__)

# ── Flask App ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
_secret_key = os.getenv("FLASK_SECRET_KEY", "")
if not _secret_key or _secret_key in ("studyai-dev-secret", "ersetze_mich_mit_einem_zufaelligen_string", "changeme"):
    import secrets as _secrets
    _secret_key = _secrets.token_hex(32)
    logger.warning("[server] FLASK_SECRET_KEY nicht gesetzt – temporärer Zufallskey wird verwendet. Bitte in .env setzen!")
app.secret_key = _secret_key
_allowed_origins = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000"
).split(",")
CORS(app, origins=_allowed_origins)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "60 per hour"],
    storage_uri="memory://",
)

def _get_rate_limit_key():
    """Rate-Limit-Key: bevorzugt Firebase-UID, Fallback auf IP."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Ersten 32 Zeichen des Tokens als Key (nicht den ganzen Token loggen)
        token_prefix = auth_header[7:39]
        return f"uid:{token_prefix}"
    return get_remote_address()

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        # Scripts: eigene Dateien + Firebase SDK + Chart.js + DOMPurify + Mermaid
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "www.gstatic.com cdn.jsdelivr.net cdnjs.cloudflare.com "
            "browser.sentry-cdn.com; "
        # Verbindungen: Firebase Auth, Firestore, Sentry, Anthropic (via Server-Proxy)
        "connect-src 'self' "
            "*.googleapis.com *.firebaseio.com *.firebaseapp.com "
            "securetoken.googleapis.com identitytoolkit.googleapis.com "
            "*.sentry.io; "
        # Frames: Google Sign-In Popup benötigt accounts.google.com
        "frame-src accounts.google.com; "
        # Bilder: Firebase Auth Avatare (lh3.googleusercontent.com)
        "img-src 'self' data: https://lh3.googleusercontent.com https://www.gstatic.com; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    return response

# ── Agents (Singletons) ────────────────────────────────────────────
# Singleton-Instanzen
orchestrator = OrchestratorAgent()
planner      = PlannerAgent()
flashcarder  = FlashcardAgent()
# ml_sr_engine ist jetzt per-User – kein globaler Singleton mehr.
# Zugriff über get_engine_for_user(uid) in den Endpoints.
db             = Database()
quiz_agent     = QuizAgent()
chat_agent     = ChatAgent()
improve_agent  = ImproveCardAgent()
firebase       = FirebaseSync()
sec_mgr        = SecurityManager(db_path=db.db_path)
sec_mgr.init_app(app)


# ── Auth-Hilfsfunktionen ──────────────────────────────────────────────────────

def _firebase_auth_enabled() -> bool:
    """True wenn Firebase Admin SDK initialisiert ist (für Token-Verifikation nutzbar)."""
    return firebase.enabled

def get_current_user() -> dict:
    """
    Liest und verifiziert den Firebase-ID-Token aus dem Authorization-Header.

    Rückgabe:
      {"uid": str, "email": str|None, "auth_enabled": bool}

    Gibt None zurück wenn Firebase aktiv, aber Token fehlt/ungültig ist.
    Gibt {"uid": "anon_<uuid>", ...} zurück wenn Firebase nicht konfiguriert (lokaler Modus).
    Jede Browser-Session bekommt eine eigene UID – keine Cross-Contamination.
    """
    if not _firebase_auth_enabled():
        # Session-unique UID – verhindert Datenvermischung zwischen verschiedenen Browsers/Usern
        if "anon_uid" not in flask_session:
            import uuid as _uuid
            flask_session["anon_uid"]  = f"anon_{_uuid.uuid4().hex[:16]}"
            flask_session.permanent    = True
        return {"uid": flask_session["anon_uid"], "email": None, "auth_enabled": False}

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None  # Token fehlt

    token = auth_header[7:].strip()
    try:
        from firebase_admin import auth as fb_auth
        decoded = fb_auth.verify_id_token(token, check_revoked=True)
        try:
            sec_mgr.log_auth_event(
                ip=request.remote_addr,
                event="token_valid",
                success=True,
                uid=decoded["uid"],
            )
        except Exception:
            pass
        return {
            "uid": decoded["uid"],
            "email": decoded.get("email"),
            "auth_enabled": True,
        }
    except Exception as e:
        # Nur generische Fehlermeldung loggen (kein Token-Inhalt)
        logger.warning("[Auth] Token-Verifikation fehlgeschlagen von IP: %s",
                      request.remote_addr)
        try:
            sec_mgr.log_auth_event(
                ip=request.remote_addr,
                event="token_invalid",
                success=False,
            )
        except Exception:
            pass  # Auth-Logging darf nie den Request blockieren
        return None


def _validate_sr_state(state: dict) -> tuple[bool, str]:
    """Validiert einen SR-State-Dict. Gibt (is_valid, error_msg) zurück."""
    if not isinstance(state, dict):
        return False, "state muss ein Objekt sein"

    required_fields = ["card_id", "repetitions", "interval", "ef"]
    for field in required_fields:
        if field not in state:
            return False, f"state fehlt Pflichtfeld: {field}"

    if not isinstance(state.get("repetitions"), (int, float)) or state["repetitions"] < 0:
        return False, "state.repetitions muss eine nicht-negative Zahl sein"

    if not isinstance(state.get("interval"), (int, float)) or state["interval"] < 0:
        return False, "state.interval muss eine nicht-negative Zahl sein"

    if not isinstance(state.get("ef"), (int, float)) or state["ef"] < 1.0:
        return False, "state.ef muss >= 1.0 sein"

    # next_review Datum validieren falls vorhanden
    if "next_review" in state and state["next_review"] is not None:
        try:
            from datetime import datetime
            datetime.fromisoformat(str(state["next_review"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False, "state.next_review muss ein gültiges ISO-Datum sein"

    return True, ""


def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    """Prüft ob eine Session dem User gehört."""
    owner = db.get_session_owner(session_id)
    if owner is None:
        return False
    # Strikte Prüfung: nur gleiche user_id hat Zugriff
    # "local" User darf nur "local"-Sessions sehen
    return owner == user_id


def _check_quota_or_abort(user: dict, metric: str):
    """
    Prüft Quota für die gegebene Metrik.
    Gibt None zurück wenn erlaubt, sonst 429-Response.
    """
    uid = user.get("uid")
    if not uid:
        return None   # Kein UID → kein Quota-Check (edge case)
    db.ensure_user(uid, user.get("email"))
    allowed, used, limit = db.check_quota(uid, metric)
    if not allowed:
        tier = db.get_user_tier(uid)
        limit_str = "∞" if limit == -1 else str(limit)
        return jsonify({
            "error": (
                f"Monatliches Limit erreicht ({used}/{limit_str} {metric.replace('_', ' ')}). "
                f"Upgrade auf Pro für mehr Kapazität."
            ),
            "used": used,
            "limit": limit,
            "tier": tier,
            "upgrade_url": "/billing",
        }), 429
    return None


# ── Routen ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Liefert die Haupt-UI."""
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/privacy.html")
def privacy():
    """DSGVO-Datenschutzerklärung."""
    return send_from_directory(str(BASE_DIR), "privacy.html")


@app.route("/terms.html")
def terms():
    """Nutzungsbedingungen."""
    return send_from_directory(str(BASE_DIR), "terms.html")


@app.route("/api/health")
def health():
    """
    Erweiterter Health-Check-Endpoint.
    Prüft: Datenbank, Redis (optional), Claude-API-Key, Firebase.
    Gibt HTTP 200 bei "ok", HTTP 503 bei "degraded" zurück.
    """
    checks: dict = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
    }

    # ── Datenbank-Check ──────────────────────────────────────────────────────
    try:
        db._get_conn().execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        checks["status"] = "degraded"

    # ── Redis-Check (optional) ───────────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        try:
            import redis as _redis_lib
            _r = _redis_lib.from_url(redis_url, socket_timeout=2)
            _r.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"unavailable: {exc}"
            # Redis-Ausfall ist kein fataler Fehler (degraded, aber nicht down)
    else:
        checks["redis"] = "not_configured"

    # ── Claude API Key ───────────────────────────────────────────────────────
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key.startswith("sk-ant-"):
        checks["claude"] = "configured"
    elif api_key:
        checks["claude"] = "invalid_format"
        checks["status"] = "degraded"
    else:
        checks["claude"] = "missing"
        checks["status"] = "degraded"

    # ── Firebase-Check ───────────────────────────────────────────────────────
    checks.update(firebase.status())

    http_status = 200 if checks["status"] == "ok" else 503
    return jsonify(checks), http_status


@app.route("/api/config")
def get_config():
    """
    Gibt die Frontend-Konfiguration zurück.
    Enthält Firebase Web Config (öffentlich, sicher) wenn konfiguriert.
    """
    web_api_key = os.getenv("FIREBASE_WEB_API_KEY", "").strip()
    project_id  = os.getenv("FIREBASE_PROJECT_ID", "").strip()

    if not web_api_key or not project_id:
        return jsonify({"firebase_enabled": False})

    auth_domain       = os.getenv("FIREBASE_AUTH_DOMAIN",
                                   f"{project_id}.firebaseapp.com")
    storage_bucket    = os.getenv("FIREBASE_STORAGE_BUCKET",
                                   f"{project_id}.appspot.com")
    messaging_sender  = os.getenv("FIREBASE_MESSAGING_SENDER_ID", "")
    app_id            = os.getenv("FIREBASE_APP_ID", "")

    return jsonify({
        "firebase_enabled": True,
        "firebaseConfig": {
            "apiKey":            web_api_key,
            "authDomain":        auth_domain,
            "projectId":         project_id,
            "storageBucket":     storage_bucket,
            "messagingSenderId": messaging_sender,
            "appId":             app_id,
        },
    })


@app.route("/api/auth/me")
def auth_me():
    """Gibt Infos zum aktuell eingeloggten User zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    return jsonify(user)


@app.route("/api/analyze", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("10 per minute", key_func=_get_rate_limit_key)
def analyze():
    """
    PDF-Upload und Analyse via Server-Sent Events (SSE).
    Liefert Fortschrittsupdates in Echtzeit, dann das Gesamtergebnis.
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    # Quota-Check: max. X Analysen pro Monat je Tier
    quota_err = _check_quota_or_abort(user, "analyses")
    if quota_err:
        return quota_err
    db.increment_usage(user["uid"], "analyses")
    # Unterstützt sowohl single-PDF ("pdf") als auch multi-PDF ("pdfs")
    files = request.files.getlist("pdfs")
    if not files:
        single = request.files.get("pdf")
        if single:
            files = [single]
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "Keine PDF-Datei gefunden. Nutze 'pdf' oder 'pdfs' im FormData."}), 400
    files = [f for f in files if f.filename]

    def generate():
        """SSE-Generator: streamt Fortschritt und Ergebnis."""
        def send_event(event_type: str, data: dict) -> str:
            return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            result_container = {}
            error_container = {}

            def on_progress(info: dict):
                yield_value = send_event("progress", info)
                # Wir können nicht direkt yielden – Workaround via Liste
                result_container["_last_progress"] = yield_value

            # Wir brauchen einen anderen Ansatz: synchrone Iteration
            # mit Fortschritt-Queue
            import queue, threading

            progress_queue = queue.Queue()
            done_event = threading.Event()

            def run_analysis():
                try:
                    def cb(info):
                        progress_queue.put(("progress", info))

                    # Token-Callback für Billing: protokolliert API-Kosten pro Call
                    def token_cb(agent, tok_in, tok_out):
                        try:
                            db.log_tokens(user["uid"], None, agent, tok_in, tok_out)
                        except Exception as _e:
                            logger.debug("[Billing] Token-Log fehlgeschlagen: %s", _e)

                    if len(files) == 1:
                        result = orchestrator.run(
                            files[0], files[0].filename,
                            progress_callback=cb, token_callback=token_cb
                        )
                    else:
                        # Multi-PDF: jede Datei einzeln analysieren, dann zusammenführen
                        results = []
                        for idx, f in enumerate(files):
                            def cb_multi(info, idx=idx, total=len(files)):
                                info["file_index"] = idx + 1
                                info["file_total"] = total
                                info["filename"] = f.filename
                                progress_queue.put(("progress", info))
                            r = orchestrator.run(
                                f, f.filename,
                                progress_callback=cb_multi, token_callback=token_cb
                            )
                            results.append(r)
                        result = orchestrator.merge_results(results)

                    progress_queue.put(("result", result))
                except Exception as e:
                    progress_queue.put(("error", {"message": str(e)}))
                finally:
                    done_event.set()

            thread = threading.Thread(target=run_analysis, daemon=True)
            thread.start()

            # Fortschritt streamen
            while not done_event.is_set() or not progress_queue.empty():
                try:
                    event_type, data = progress_queue.get(timeout=0.5)
                    yield send_event(event_type, data)
                    if event_type in ("result", "error"):
                        break
                except queue.Empty:
                    # Heartbeat senden damit die Verbindung offen bleibt
                    yield ": heartbeat\n\n"

            thread.join(timeout=300)

        except SecurityError as e:
            yield send_event("error", {"message": f"Sicherheitsfehler: {e}"})
        except Exception as e:
            logger.exception("Unerwarteter Fehler in /api/analyze")
            yield send_event("error", {"message": f"Interner Fehler: {e}"})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/plan", methods=["POST"])
def plan():
    """
    Erstellt einen Lernplan aus Phase-1-Output.
    Body (JSON): { alle_themen: [...], pruefungsdatum: 'YYYY-MM-DD', stunden_pro_tag: 3.0 }
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Kein JSON-Body empfangen."}), 400

    alle_themen    = data.get("alle_themen", [])
    pruefungsdatum = data.get("pruefungsdatum", "")
    try:
        stunden_pro_tag = float(data.get("stunden_pro_tag", 3))
        stunden_pro_tag = max(0.5, min(16.0, stunden_pro_tag))
    except (TypeError, ValueError):
        stunden_pro_tag = 3.0

    if not isinstance(alle_themen, list) or not alle_themen:
        return jsonify({"error": "Keine Themen übergeben. Bitte zuerst Phase 1 abschließen."}), 400
    if len(alle_themen) > 500:
        return jsonify({"error": "Zu viele Themen (max. 500)."}), 400
    if not pruefungsdatum or not isinstance(pruefungsdatum, str):
        return jsonify({"error": "Prüfungsdatum fehlt."}), 400
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", pruefungsdatum):
        return jsonify({"error": "Prüfungsdatum muss im Format YYYY-MM-DD sein."}), 400

    try:
        result = planner.create_plan(alle_themen, pruefungsdatum, stunden_pro_tag)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Fehler in /api/plan")
        return jsonify({"error": f"Interner Fehler: {e}"}), 500


@app.route("/api/flashcards", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("10 per minute", key_func=_get_rate_limit_key)
def flashcards():
    """
    Generiert Anki-Flashcards aus Phase-1-Chunks via SSE-Streaming.
    Body (JSON): { chunks: [{chunk_id, text, word_count, themen}] }
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    # Quota-Check: max. X Flashcard-Generierungen pro Monat
    quota_err = _check_quota_or_abort(user, "flashcard_gens")
    if quota_err:
        return quota_err
    db.increment_usage(user["uid"], "flashcard_gens")
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Kein JSON-Body empfangen."}), 400

    chunks = data.get("chunks", [])
    if not isinstance(chunks, list) or not chunks:
        return jsonify({"error": "Keine Chunks übergeben. Bitte zuerst Phase 1 abschließen."}), 400
    if len(chunks) > 200:
        return jsonify({"error": "Zu viele Chunks (max. 200)."}), 400

    def generate():
        import queue, threading

        def send_event(event_type: str, payload: dict) -> str:
            return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        q = queue.Queue()
        done = threading.Event()

        def run():
            try:
                def cb(current, total, msg):
                    q.put(("progress", {"current": current, "total": total, "message": msg}))

                result = flashcarder.generate_for_all_chunks(chunks, progress_callback=cb)
                q.put(("result", result))
            except Exception as e:
                q.put(("error", {"message": str(e)}))
            finally:
                done.set()

        threading.Thread(target=run, daemon=True).start()

        while not done.is_set() or not q.empty():
            try:
                etype, payload = q.get(timeout=0.5)
                yield send_event(etype, payload)
                if etype in ("result", "error"):
                    break
            except queue.Empty:
                yield ": heartbeat\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/sr/rate", methods=["POST"])
def sr_rate():
    """
    ML-SR: Berechnet den neuen Kartenstate nach einer Bewertung.
    Body: { state: {...} | null, card_id: str, rating: 0|1|2|3 }
    Returns: { new_state: {...}, next_review_label: str }
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data    = request.get_json(force=True, silent=True) or {}
    rating  = data.get("rating")
    card_id = str(data.get("card_id", "?"))[:64]  # max 64 chars
    state   = data.get("state") or MLSpacedRepetitionEngine.new_card_state(card_id)

    if rating not in (0, 1, 2, 3):
        return jsonify({"error": "rating muss 0, 1, 2 oder 3 sein."}), 400
    is_valid, err_msg = _validate_sr_state(state)
    if not is_valid:
        return jsonify({"error": f"Ungültiger state: {err_msg}"}), 400

    try:
        engine    = get_engine_for_user(user["uid"])
        new_state = engine.rate(state, int(rating))
        return jsonify({
            "new_state"          : new_state,
            "next_review_label"  : MLSpacedRepetitionEngine.time_until_due(new_state),
            "is_due"             : MLSpacedRepetitionEngine.is_due(new_state),
        })
    except Exception as e:
        logger.exception("Fehler in /api/sr/rate")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sr/due", methods=["POST"])
def sr_due():
    """
    ML-SR: Filtert Karten-States und gibt fällige zurück.
    Body: { states: { card_id: state_dict, ... } }
    Returns: { due_ids: [str], counts: { due, total, new } }
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data   = request.get_json(force=True, silent=True) or {}
    states = data.get("states", {})

    due_ids = [cid for cid, st in states.items() if MLSpacedRepetitionEngine.is_due(st)]
    new_ids = [cid for cid, st in states.items() if st.get("total_reviews", 0) == 0]

    return jsonify({
        "due_ids": due_ids,
        "counts" : {
            "due"  : len(due_ids),
            "total": len(states),
            "new"  : len(new_ids),
        },
    })


@app.route("/api/sr/train", methods=["POST"])
@limiter.limit("10 per minute")
def sr_train():
    """
    Trainiert das ML-Modell mit Review-Logs.
    Body: { logs: [ { rating, repetitions, interval, last_rating }, ... ] }
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data = request.get_json(force=True, silent=True) or {}
    raw_logs = data.get("logs", [])

    try:
        validated_logs = orchestrator.security.validate_review_logs(raw_logs)
        get_engine_for_user(user["uid"]).train(validated_logs)
        return jsonify({"success": True, "trained_samples": len(validated_logs)})
    except Exception as e:
        logger.exception("Fehler beim Modell-Training")
        return jsonify({"error": str(e)}), 400


@app.route("/api/export/anki", methods=["POST"])
@limiter.limit("10 per minute")
def export_anki():
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data = request.get_json(force=True, silent=True) or {}
    cards = data.get("cards", [])

    if not isinstance(cards, list) or not cards:
        return jsonify({"error": "Keine Karten zum Exportieren übergeben."}), 400
    if len(cards) > 5000:
        return jsonify({"error": "Zu viele Karten (max. 5000)."}), 400

    my_model = genanki.Model(
        1607392319,
        'StudyAI Model',
        fields=[
            {'name': 'Front'},
            {'name': 'Back'},
            {'name': 'Type'},
            {'name': 'Tier'},
            {'name': 'Diagram'},
        ],
        templates=[
            {
                'name': 'Card 1',
                'qfmt': '<div style="margin-bottom: 15px;"><span style="font-weight: bold; color: #888;">{{Type}}</span><span style="float: right; font-size: 12px; background: #333; color: white; padding: 3px 8px; border-radius: 12px;">{{Tier}}</span></div><hr><p style="margin-top: 20px; font-weight: 500;">{{Front}}</p>',
                'afmt': '{{FrontSide}}<hr id="answer"><p style="margin-top: 20px;">{{Back}}</p>{{#Diagram}}<br><div style="margin-top:20px; padding:10px; background:#f4f4f4; border-radius:8px;"><pre class="mermaid">{{Diagram}}</pre></div><script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs"; mermaid.initialize({ startOnLoad: true });</script>{{/Diagram}}',
            },
        ],
        css='.card { font-family: "Segoe UI", Arial, sans-serif; font-size: 20px; text-align: left; color: #111; background-color: white; padding: 20px; line-height: 1.5; } hr { border: 0; border-bottom: 2px dashed #ccc; margin: 20px 0; }'
    )

    my_deck = genanki.Deck(2059400110, 'StudyAI Export Deck')

    for c in cards:
        my_note = genanki.Note(
            model=my_model,
            fields=[
                c.get("front", ""),
                c.get("back", ""),
                c.get("typ", "Konzept"),
                c.get("tier", "Beginner"),
                c.get("diagram", ""),
            ]
        )
        my_deck.add_note(my_note)

    # Race-Condition-freier Export: tempfile → BytesIO → sofort löschen
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".apkg")
    try:
        os.close(tmp_fd)
        genanki.Package(my_deck).write_to_file(tmp_path)
        with open(tmp_path, "rb") as f:
            buf = io.BytesIO(f.read())
    except Exception as e:
        logger.exception("Fehler beim Anki-Export")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    buf.seek(0)
    download_name = f"StudyAI_{len(cards)}_Karten.apkg"
    return send_file(buf, as_attachment=True, download_name=download_name,
                     mimetype="application/zip")

# ── Session-Management ────────────────────────────────────────────────────────

@app.route("/api/sessions", methods=["POST"])
def create_session():
    """Erstellt eine neue Session. Body: {name: str}"""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get("name", "Unbenannte Session"))[:120].strip() or "Unbenannte Session"
    try:
        session_id = db.create_session(name, user_id=user["uid"])
        return jsonify({"session_id": session_id})
    except Exception as e:
        logger.exception("Fehler beim Erstellen der Session")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """Gibt alle Sessions des aktuellen Users zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    try:
        try:
            limit  = min(int(request.args.get("limit",  50)), 200)
            offset = max(int(request.args.get("offset",  0)),   0)
        except (ValueError, TypeError):
            limit, offset = 50, 0
        sessions = db.list_sessions(user_id=user["uid"], limit=limit, offset=offset)
        return jsonify({"sessions": sessions})
    except Exception as e:
        logger.exception("Fehler beim Laden der Sessions")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>", methods=["GET"])
def load_session(session_id):
    """Lädt alle Daten einer Session."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    try:
        data = db.load_session(session_id, user_id=user["uid"])
        if not data:
            return jsonify({"error": "Session nicht gefunden"}), 404
        return jsonify(data)
    except Exception as e:
        logger.exception("Fehler beim Laden der Session")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>", methods=["PATCH"])
def rename_session(session_id):
    """Benennt eine Session um. Body: {name: str}"""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    data = request.get_json(force=True, silent=True) or {}
    new_name = str(data.get("name", "")).strip()[:120]
    if not new_name:
        return jsonify({"error": "Name darf nicht leer sein"}), 400
    try:
        db.rename_session(session_id, new_name)
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("Fehler beim Umbenennen der Session")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    """Löscht eine Session (lokal + Firestore)."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    try:
        db.delete_session(session_id)
        firebase.delete_session(session_id)
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("Fehler beim Löschen der Session")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/save", methods=["POST"])
@limiter.limit("30 per minute")
def save_session(session_id):
    """
    Speichert den aktuellen App-State einer Session.
    Body: {analysis?, flashcards?, plan?, sr_states?, sr_logs?}
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    data = request.get_json(force=True, silent=True) or {}
    try:
        db.save_session_state(session_id, data)
        firebase.sync_session(session_id, data)
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("Fehler beim Speichern der Session")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/export", methods=["GET"])
def export_session(session_id):
    """Exportiert eine Session als JSON-Download."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    try:
        data = db.load_session(session_id)
        if not data:
            return jsonify({"error": "Session nicht gefunden"}), 404
        name = data.get("session", {}).get("name", "session")
        safe_name = "".join(c for c in name if c.isalnum() or c in " _-")[:40].strip()
        buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name=f"StudyAI_{safe_name}.json",
                         mimetype="application/json")
    except Exception as e:
        logger.exception("Fehler beim Exportieren der Session")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/import", methods=["POST"])
@limiter.limit("10 per minute")
def import_session():
    """
    Importiert eine Session aus einer JSON-Datei.
    Erstellt eine neue Session mit neuer ID.
    Body: JSON-Objekt (aus vorherigem Export)
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Kein gültiges JSON übergeben"}), 400
    try:
        session_info = data.get("session", {})
        name = session_info.get("name", "Importierte Session")
        session_id = db.create_session(f"{name} (Import)", user_id=user["uid"])
        payload = {k: data[k] for k in ("analysis", "flashcards", "plan", "sr_states", "sr_logs")
                   if k in data and data[k]}
        if payload:
            db.save_session_state(session_id, payload)
        return jsonify({"session_id": session_id, "name": f"{name} (Import)"})
    except Exception as e:
        logger.exception("Fehler beim Importieren der Session")
        return jsonify({"error": str(e)}), 500


# ── Security Audit ────────────────────────────────────────────────────────────

@app.route("/api/security/audit")
def security_audit():
    """Gibt die neuesten Audit-Logs zurück (nur localhost)."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "Nur lokal verfügbar"}), 403
    limit = min(int(request.args.get("limit", 100)), 500)
    only_suspicious = request.args.get("suspicious", "false").lower() == "true"
    logs = sec_mgr.get_suspicious_logs(limit) if only_suspicious else sec_mgr.get_recent_logs(limit)
    return jsonify({"logs": logs, "count": len(logs)})


@app.route("/api/security/stats")
def security_stats():
    """Gibt Security-Statistiken zurück (nur localhost)."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": "Nur lokal verfügbar"}), 403
    return jsonify(sec_mgr.get_stats())


# ── GDPR: Account-Verwaltung ──────────────────────────────────────────────────

@app.route("/api/user/delete", methods=["POST"])
@limiter.limit("3 per hour")
def delete_user_account():
    """
    GDPR Art. 17 – Recht auf Löschung.
    Löscht Account + alle Daten. Body: {confirmation: 'DELETE'}
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    data = request.get_json(force=True, silent=True) or {}
    if data.get("confirmation") != "DELETE":
        return jsonify({
            "error": "Sicherheitsbestätigung erforderlich: Sende {\"confirmation\": \"DELETE\"}"
        }), 400
    try:
        result = db.delete_all_user_data(user["uid"])
        firebase.delete_all_user_sessions(user["uid"])
        # Firebase Auth-Account löschen wenn Auth aktiv
        if _firebase_auth_enabled():
            try:
                from firebase_admin import auth as fb_auth
                fb_auth.delete_user(user["uid"])
            except Exception as e:
                logger.warning("[GDPR] Firebase-Auth-Deletion fehlgeschlagen: %s", e)
        logger.info("[GDPR] Account vollständig gelöscht: %s – %s", user["uid"], result)
        return jsonify({"success": True, "deleted": result})
    except Exception as e:
        logger.exception("[GDPR] Fehler bei Account-Löschung für %s", user.get("uid", "?"))
        return jsonify({"error": str(e)}), 500


@app.route("/api/user/export", methods=["POST"])
@limiter.limit("5 per day")
def export_user_data():
    """
    GDPR Art. 20 – Recht auf Datenportabilität.
    Gibt alle User-Daten als ZIP-Archiv (JSON) zurück.
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    try:
        data = db.export_all_user_data(user["uid"])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "studyai_export.json",
                json.dumps(data, ensure_ascii=False, indent=2)
            )
        buf.seek(0)
        logger.info("[GDPR] Datenexport für User %s: %d Sessions",
                    user["uid"], len(data.get("sessions", [])))
        return send_file(
            buf,
            as_attachment=True,
            download_name="StudyAI_Datenexport.zip",
            mimetype="application/zip",
        )
    except Exception as e:
        logger.exception("[GDPR] Fehler beim Datenexport für %s", user.get("uid", "?"))
        return jsonify({"error": str(e)}), 500


# ── Billing / Monetarisierung ─────────────────────────────────────────────────

@app.route("/api/user/profile", methods=["GET"])
def user_profile():
    """Gibt Tier, Usage und Limits für den eingeloggten User zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    db.ensure_user(user["uid"], user.get("email"))
    tier   = db.get_user_tier(user["uid"])
    usage  = db.get_usage(user["uid"])
    limits = db.TIER_LIMITS.get(tier, db.TIER_LIMITS["free"])
    return jsonify({
        "uid":    user["uid"],
        "email":  user.get("email"),
        "tier":   tier,
        "usage":  usage,
        "limits": limits,
    })


@app.route("/api/billing/usage", methods=["GET"])
def billing_usage():
    """Gibt aktuelle Monats-Usage und Tier-Limits zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    db.ensure_user(user["uid"], user.get("email"))
    tier   = db.get_user_tier(user["uid"])
    usage  = db.get_usage(user["uid"])
    limits = db.TIER_LIMITS.get(tier, db.TIER_LIMITS["free"])
    return jsonify({"tier": tier, "usage": usage, "limits": limits})


@app.route("/api/billing/checkout", methods=["POST"])
@limiter.limit("10 per hour")
def billing_checkout():
    """Erstellt eine Stripe Checkout Session und gibt die URL zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    try:
        from payment import create_checkout_session, is_configured
        if not is_configured():
            return jsonify({"error": "Stripe nicht konfiguriert"}), 503
        db.ensure_user(user["uid"], user.get("email"))
        base = request.host_url.rstrip("/")
        url = create_checkout_session(
            uid=user["uid"],
            email=user.get("email", ""),
            success_url=f"{base}/?payment=success",
            cancel_url=f"{base}/?payment=cancel",
        )
        return jsonify({"checkout_url": url})
    except Exception as e:
        logger.exception("[Billing] Checkout-Fehler für %s", user.get("uid", "?"))
        return jsonify({"error": str(e)}), 500


@app.route("/api/billing/portal", methods=["POST"])
@limiter.limit("10 per hour")
def billing_portal():
    """Erstellt eine Stripe Customer Portal Session und gibt die URL zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    try:
        from payment import create_portal_session, is_configured
        if not is_configured():
            return jsonify({"error": "Stripe nicht konfiguriert"}), 503
        base = request.host_url.rstrip("/")
        url = create_portal_session(user["uid"], return_url=f"{base}/")
        return jsonify({"portal_url": url})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("[Billing] Portal-Fehler für %s", user.get("uid", "?"))
        return jsonify({"error": str(e)}), 500


@app.route("/api/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    """
    Stripe-Webhook-Endpoint. Verarbeitet Subscription-Events.
    Muss in Stripe Dashboard konfiguriert sein.
    """
    try:
        from payment import handle_webhook
        ok = handle_webhook(
            payload=request.data,
            sig_header=request.headers.get("Stripe-Signature", ""),
        )
        return ("", 200) if ok else ("", 400)
    except Exception as e:
        logger.exception("[Billing] Webhook-Fehler")
        return jsonify({"error": str(e)}), 500


# ── Flashcard CRUD (Phase 4) ───────────────────────────────────────────────────

# Erlaubte Felder für Flashcard-Update (Whitelist)
_FLASHCARD_ALLOWED_FIELDS = {"front", "back", "type", "difficulty", "topic", "diagram", "hint"}


@app.route("/api/sessions/<session_id>/flashcards", methods=["POST"])
@limiter.limit("30 per minute")
def add_flashcard(session_id):
    """
    Fügt eine neue Flashcard zu einer Session hinzu.
    Body: {card: {front: str, back: str, type?: str, topic?: str, ...}}
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    data = request.get_json(force=True, silent=True) or {}
    card = data.get("card", {})
    if not isinstance(card, dict):
        return jsonify({"error": "card muss ein Objekt sein"}), 400
    front = str(card.get("front", "")).strip()
    back  = str(card.get("back",  "")).strip()
    if not front or not back:
        return jsonify({"error": "front und back sind Pflichtfelder"}), 400
    # Sanitize: nur erlaubte Felder, max. Längen aus config
    from config import MAX_FLASHCARD_FRONT_LENGTH, MAX_FLASHCARD_BACK_LENGTH
    safe_card: dict = {
        "front":      front[:MAX_FLASHCARD_FRONT_LENGTH],
        "back":       back[:MAX_FLASHCARD_BACK_LENGTH],
        "type":       str(card.get("type", "basic"))[:50],
        "difficulty": str(card.get("difficulty", "medium"))[:20],
        "topic":      str(card.get("topic", ""))[:200],
    }
    if card.get("hint"):
        safe_card["hint"] = str(card["hint"])[:500]
    try:
        card_id = db.add_flashcard(session_id, safe_card)
        return jsonify({"success": True, "card_id": card_id})
    except Exception as e:
        logger.exception("[Flashcard] Fehler beim Hinzufügen")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/flashcards/<card_id>", methods=["PATCH"])
@limiter.limit("60 per minute")
def update_flashcard(session_id, card_id):
    """
    Aktualisiert eine bestehende Flashcard (Partial-Update).
    Body: {card: {front?: str, back?: str, type?: str, topic?: str, ...}}
    Nur Felder die im Body enthalten sind, werden geändert.
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    if len(card_id) > 64:
        return jsonify({"error": "Ungültige card_id"}), 400
    data = request.get_json(force=True, silent=True) or {}
    card = data.get("card", {})
    if not isinstance(card, dict):
        return jsonify({"error": "card muss ein Objekt sein"}), 400
    # Nur erlaubte Felder übernehmen
    from config import MAX_FLASHCARD_FRONT_LENGTH, MAX_FLASHCARD_BACK_LENGTH, MAX_FLASHCARD_DIAGRAM_LENGTH
    safe_update: dict = {}
    if "front"      in card: safe_update["front"]      = str(card["front"])[:MAX_FLASHCARD_FRONT_LENGTH]
    if "back"       in card: safe_update["back"]        = str(card["back"])[:MAX_FLASHCARD_BACK_LENGTH]
    if "type"       in card: safe_update["type"]        = str(card["type"])[:50]
    if "difficulty" in card: safe_update["difficulty"]  = str(card["difficulty"])[:20]
    if "topic"      in card: safe_update["topic"]       = str(card["topic"])[:200]
    if "hint"       in card: safe_update["hint"]        = str(card["hint"])[:500]
    if "diagram"    in card: safe_update["diagram"]     = str(card["diagram"])[:MAX_FLASHCARD_DIAGRAM_LENGTH]
    if not safe_update:
        return jsonify({"error": "Keine gültigen Felder zum Aktualisieren"}), 400
    try:
        db.update_flashcard(session_id, card_id, safe_update)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("[Flashcard] Fehler beim Aktualisieren")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/flashcards/<card_id>", methods=["DELETE"])
@limiter.limit("60 per minute")
def delete_flashcard(session_id, card_id):
    """Löscht eine Flashcard und ihren SR-State."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    if len(card_id) > 64:
        return jsonify({"error": "Ungültige card_id"}), 400
    try:
        db.delete_flashcard(session_id, card_id)
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("[Flashcard] Fehler beim Löschen")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/flashcards/<card_id>", methods=["GET"])
def get_flashcard(session_id, card_id):
    """Gibt eine einzelne Flashcard zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Zugriff verweigert"}), 403
    card = db.get_flashcard(session_id, card_id)
    if card is None:
        return jsonify({"error": "Flashcard nicht gefunden"}), 404
    return jsonify({"card": card})


# ── Quiz ──────────────────────────────────────────────────────────────────────

@app.route("/api/quiz/generate", methods=["POST"])
@limiter.limit("3 per minute")
@limiter.limit("5 per minute", key_func=_get_rate_limit_key)
def generate_quiz():
    """
    Generiert Multiple-Choice-Fragen aus Flashcards (SSE-Streaming).
    Body: {cards: [...], limit: int (default 20)}
    SSE Events: progress {current, total, message} | result {questions} | error {message}
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    # Quota-Check: max. X Quiz-Generierungen pro Monat
    quota_err = _check_quota_or_abort(user, "quiz_gens")
    if quota_err:
        return quota_err
    db.increment_usage(user["uid"], "quiz_gens")
    data = request.get_json(force=True, silent=True) or {}
    cards = data.get("cards", [])
    if not isinstance(cards, list):
        return jsonify({"error": "cards muss eine Liste sein."}), 400
    try:
        limit = max(1, min(50, int(data.get("limit", 20))))
    except (TypeError, ValueError):
        return jsonify({"error": "limit muss eine Zahl sein."}), 400

    if not cards:
        return jsonify({"error": "Keine Karten übergeben."}), 400

    import queue

    q: queue.Queue = queue.Queue()

    def on_progress(current, total, message):
        q.put(("progress", {"current": current, "total": total, "message": message}))

    def worker():
        try:
            questions = quiz_agent.generate_questions(cards, num_questions=limit,
                                                      progress_callback=on_progress)
            q.put(("result", {"questions": questions, "total": len(questions)}))
        except Exception as exc:
            logger.exception("Fehler beim Quiz-Generieren")
            q.put(("error", {"message": str(exc)}))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                event_type, payload = q.get(timeout=120)
            except queue.Empty:
                yield "event: error\ndata: {\"message\": \"Timeout\"}\n\n"
                break
            yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if event_type in ("result", "error"):
                break

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Phase 5: Chat-Tutor ───────────────────────────────────────────────────────

@app.route("/api/sessions/<session_id>/chat", methods=["GET"])
def get_chat_history(session_id: str):
    """Gibt die Chat-History einer Session zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401

    session = db.load_session(session_id)
    if session is None or session.get("user_id") != user["uid"]:
        return jsonify({"error": "Session nicht gefunden"}), 404

    history = db.get_chat_history(session_id, user["uid"])
    return jsonify({"history": history})


@app.route("/api/sessions/<session_id>/chat", methods=["POST"])
@limiter.limit("30 per minute")
@limiter.limit("5 per minute", key_func=_get_rate_limit_key)
def chat_with_tutor(session_id: str):
    """
    Stellt eine Frage an den KI-Tutor und streamt die Antwort via SSE.
    Body: {question: str}
    SSE Events: chunk {text} | done {message_id} | error {message}
    """
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401

    session = db.load_session(session_id)
    if session is None or session.get("user_id") != user["uid"]:
        return jsonify({"error": "Session nicht gefunden"}), 404

    data     = request.get_json(force=True, silent=True) or {}
    question = (data.get("question") or "").strip()

    if not question:
        return jsonify({"error": "Frage darf nicht leer sein."}), 400
    if len(question) > 2000:
        return jsonify({"error": "Frage zu lang (max. 2000 Zeichen)."}), 400

    # Analyseergebnis + Flashcards für Kontext laden
    result     = session.get("result") or {}
    flashcards = session.get("flashcards") or []

    # Chat-History laden (für Gesprächs-Kontext)
    history = db.get_chat_history(session_id, user["uid"], limit=40)

    # User-Nachricht sofort persistieren
    db.add_chat_message(session_id, user["uid"], "user", question)

    # Billing-Callback für Token-Tracking
    uid = user["uid"]
    def token_cb(tokens_in, tokens_out):
        try:
            db.log_tokens(uid, session_id, "ChatAgent", tokens_in, tokens_out)
        except Exception:
            pass

    import queue as _queue

    q: _queue.Queue = _queue.Queue()

    def worker():
        answer_parts = []
        try:
            for chunk in chat_agent.stream_response(question, history, result, flashcards):
                answer_parts.append(chunk)
                q.put(("chunk", {"text": chunk}))
            # Vollständige Antwort persistieren
            full_answer = "".join(answer_parts)
            msg_id = db.add_chat_message(session_id, uid, "assistant", full_answer)
            q.put(("done", {"message_id": msg_id, "length": len(full_answer)}))
        except Exception as exc:
            logger.exception("[Chat] Fehler bei Tutor-Antwort")
            q.put(("error", {"message": str(exc)}))

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        while True:
            try:
                event_type, payload = q.get(timeout=120)
            except _queue.Empty:
                yield "event: error\ndata: {\"message\": \"Timeout\"}\n\n"
                break
            yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if event_type in ("done", "error"):
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/sessions/<session_id>/chat", methods=["DELETE"])
def delete_chat_history(session_id: str):
    """Löscht die gesamte Chat-History einer Session."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401

    session = db.load_session(session_id)
    if session is None or session.get("user_id") != user["uid"]:
        return jsonify({"error": "Session nicht gefunden"}), 404

    deleted = db.delete_chat_history(session_id, user["uid"])
    return jsonify({"deleted": deleted, "message": f"{deleted} Nachrichten gelöscht."})


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 6 – DECK-SHARING, GAMIFICATION, ADMIN, KI-KARTEN-VERBESSERUNG
# ═══════════════════════════════════════════════════════════════════════════════

# ── 6.1 Deck-Sharing ──────────────────────────────────────────────────────────

@app.route("/api/sessions/<session_id>/share", methods=["POST"])
@limiter.limit("20 per hour")
def create_share_link(session_id: str):
    """Erstellt oder erneuert einen öffentlichen Share-Link für ein Flashcard-Deck."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Session nicht gefunden"}), 404

    token = db.create_share_token(session_id, user["uid"], expires_days=30)
    # Badge-Check: Erstes geteiltes Deck
    new_badges = db.check_and_award_badges(user["uid"])
    base = request.host_url.rstrip("/")
    return jsonify({
        "token":      token,
        "share_url":  f"{base}/shared/{token}",
        "expires_in": "30 Tage",
        "new_badges": new_badges,
    })


@app.route("/api/sessions/<session_id>/share", methods=["GET"])
def get_share_link(session_id: str):
    """Gibt den aktiven Share-Token einer Session zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Session nicht gefunden"}), 404

    info = db.get_share_token(session_id, user["uid"])
    if not info:
        return jsonify({"token": None, "share_url": None})
    base = request.host_url.rstrip("/")
    return jsonify({
        "token":      info["token"],
        "share_url":  f"{base}/shared/{info['token']}",
        "view_count": info["view_count"],
        "expires_at": info["expires_at"],
    })


@app.route("/api/sessions/<session_id>/share", methods=["DELETE"])
def revoke_share_link(session_id: str):
    """Widerruft den Share-Token einer Session."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Session nicht gefunden"}), 404

    deleted = db.delete_share_token(session_id, user["uid"])
    return jsonify({"success": deleted})


@app.route("/shared/<token>")
@limiter.limit("120 per minute")
def shared_deck_view(token: str):
    """
    Öffentliche Deck-Ansicht (kein Login nötig).
    Gibt JSON mit Flashcards + Session-Metadaten zurück.
    """
    share_info = db.get_shared_deck(token)
    if not share_info:
        return jsonify({"error": "Deck nicht gefunden oder Link abgelaufen"}), 404

    session_id = share_info["session_id"]
    session    = db.load_session(session_id)
    if not session:
        return jsonify({"error": "Session nicht mehr verfügbar"}), 404

    # Nur öffentliche Felder zurückgeben (kein user_id, keine SR-States)
    return jsonify({
        "session_name":  session.get("name", "Unbenanntes Deck"),
        "created_at":    session.get("created_at", ""),
        "flashcards":    session.get("flashcards", []),
        "card_count":    len(session.get("flashcards", [])),
        "view_count":    share_info["view_count"],
        "expires_at":    share_info.get("expires_at"),
        "analysis_meta": {
            k: v for k, v in (session.get("analysis", {}) or {}).get("metadata", {}).items()
            if k in ("filename", "language", "total_pages", "summary")
        } if session.get("analysis") else {},
    })


# ── 6.2 KI-Karten-Verbesserung ───────────────────────────────────────────────

@app.route("/api/sessions/<session_id>/flashcards/<card_id>/improve", methods=["POST"])
@limiter.limit("30 per hour")
def improve_flashcard(session_id: str, card_id: str):
    """Verbessert eine Flashcard mit Claude (Phase 6)."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401
    if not session_belongs_to_user(session_id, user["uid"]):
        return jsonify({"error": "Session nicht gefunden"}), 404

    data = request.get_json(force=True, silent=True) or {}
    card = data.get("card")
    if not card or not isinstance(card, dict):
        return jsonify({"error": "card-Objekt fehlt"}), 400

    # Optionalen Kontext aus der Session holen (Topics für bessere Antworten)
    context = ""
    try:
        session = db.load_session(session_id)
        if session and session.get("analysis"):
            topics = session["analysis"].get("topics", [])[:5]
            context = "Themen: " + ", ".join(
                t.get("title", "") for t in topics if isinstance(t, dict)
            )
    except Exception:
        pass

    result = improve_agent.improve(card, context=context)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


# ── 6.3 Gamification – Streak + Badges ───────────────────────────────────────

@app.route("/api/gamification/stats", methods=["GET"])
def gamification_stats():
    """Gibt Streak, Total-Reviews, Total-Cards und alle Badges zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401

    streak    = db.get_streak(user["uid"])
    reviews   = db.get_total_reviews(user["uid"])
    cards     = db.get_total_cards(user["uid"])
    badges    = db.get_user_badges(user["uid"])

    return jsonify({
        "streak":        streak,
        "total_reviews": reviews,
        "total_cards":   cards,
        "badges":        badges,
    })


@app.route("/api/gamification/check", methods=["POST"])
@limiter.limit("60 per hour")
def gamification_check():
    """Prüft und vergibt neue Badges. Gibt neu verdiente Badges zurück."""
    user = get_current_user()
    if user is None:
        return jsonify({"error": "Nicht authentifiziert"}), 401

    new_badges = db.check_and_award_badges(user["uid"])
    return jsonify({"new_badges": new_badges})


# ── 6.4 Admin-Dashboard ───────────────────────────────────────────────────────

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    """
    Plattform-Statistiken für Admins.
    Zugriff: UIDs in ADMIN_UIDS-Env-Variable ODER localhost.
    """
    user = get_current_user()
    is_local = request.remote_addr in ("127.0.0.1", "::1", "localhost")

    # Zugriffskontrolle: Admin-UID oder Localhost
    if user and is_admin(user["uid"]):
        pass  # Admin-UID → erlaubt
    elif is_local and user is None:
        pass  # Lokaler Zugriff ohne Auth → erlaubt für Entwicklung
    else:
        return jsonify({"error": "Zugriff verweigert"}), 403

    stats = db.get_admin_stats()
    # Kosten-Schätzung hinzufügen
    stats["estimated_cost_usd"] = estimate_cost_usd(
        stats.get("total_tokens_in", 0),
        stats.get("total_tokens_out", 0),
    )
    stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify(stats)


# ── Start ─────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # GDPR Art. 5: Veraltete Daten im Hintergrund aufräumen
    threading.Thread(
        target=lambda: db.purge_inactive_data(months=24), daemon=True
    ).start()
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_ENV", "development") == "development"
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    logger.info(f"🚀 StudyAI Server startet auf http://localhost:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)
