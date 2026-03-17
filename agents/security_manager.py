"""
StudyAI – Security Manager
===========================
HTTP-Request-Monitoring, Audit-Logging und Anomalie-Erkennung.
Läuft als Flask-Middleware und überwacht alle API-Anfragen automatisch.

Features:
  - Audit-Log aller Requests in SQLite (security_audit_log Tabelle)
  - Rate-Anomalie-Erkennung pro IP (Auto-Block bei > 200 req/min)
  - Payload-Größenprüfung (max. 10 MB)
  - Verdächtige Status-Codes markieren (400, 403, 429, 500)
  - GET /api/security/audit  → aktuelle Logs
  - GET /api/security/stats  → Zusammenfassung
"""

import time
import sqlite3
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from flask import request, g, jsonify

logger = logging.getLogger(__name__)

MAX_REQUESTS_PER_MINUTE = 200
MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
SUSPICIOUS_STATUS = {400, 403, 413, 422, 429, 500}


class SecurityManager:
    """
    Flask-Middleware für HTTP-Monitoring und Sicherheits-Audit.

    Verwendung in server.py:
        from agents.security_manager import SecurityManager
        sec_mgr = SecurityManager(db_path="studyai.db")
        sec_mgr.init_app(app)
    """

    def __init__(self, db_path: str = "studyai.db"):
        self.db_path = db_path
        self._ip_log: dict = defaultdict(deque)
        self._blocked_ips: set = set()
        self._init_table()

        # Blockierte IPs aus DB laden (nicht abgelaufene)
        try:
            now = datetime.now(timezone.utc).isoformat()
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT ip FROM blocked_ips WHERE expires_at > ? OR expires_at IS NULL",
                    (now,)
                ).fetchall()
                for row in rows:
                    self._blocked_ips.add(row[0])
            logger.info("[SecurityManager] %d blockierte IPs aus DB geladen", len(rows))
        except Exception as e:
            logger.error("[SecurityManager] Laden blockierter IPs fehlgeschlagen: %s", e)

        logger.info("[SecurityManager] initialisiert – Audit-DB: %s", db_path)

    # ── Setup ────────────────────────────────────────────────────────────────

    def _init_table(self):
        conn = sqlite3.connect(self.db_path)

        # Haupt-Audit-Log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT    NOT NULL,
                ip           TEXT,
                method       TEXT,
                endpoint     TEXT,
                status_code  INTEGER,
                duration_ms  REAL,
                payload_size INTEGER,
                suspicious   INTEGER DEFAULT 0,
                reason       TEXT
            )
        """)

        # Auth-Event-Log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                ip          TEXT,
                event       TEXT NOT NULL,
                success     INTEGER NOT NULL DEFAULT 0,
                uid         TEXT,
                details     TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_log_timestamp ON auth_audit_log(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_log_ip ON auth_audit_log(ip)")

        # Blockierte IPs
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_ips (
                ip          TEXT PRIMARY KEY,
                blocked_at  TEXT NOT NULL,
                reason      TEXT,
                expires_at  TEXT
            )
        """)

        conn.commit()
        conn.close()

    def init_app(self, app):
        """Registriert Before/After-Request-Hooks in Flask."""
        app.before_request(self._before_request)
        app.after_request(self._after_request)
        logger.info("[SecurityManager] Flask-Hooks registriert")

    # ── Middleware ────────────────────────────────────────────────────────────

    def _before_request(self):
        g._sec_start = time.perf_counter()
        ip = request.remote_addr or "unknown"

        if ip in self._blocked_ips:
            logger.warning("[SecurityManager] Blockierte IP: %s", ip)
            return jsonify({"error": "Zugriff verweigert"}), 403

        now = time.time()
        log = self._ip_log[ip]
        while log and now - log[0] > 60:
            log.popleft()
        log.append(now)

        if len(log) > MAX_REQUESTS_PER_MINUTE:
            self._blocked_ips.add(ip)
            reason = f"Rate exceeded: {len(log)} req/60s"
            self._write_audit(ip, request.method, request.endpoint or request.path,
                              429, 0, 0, True, reason)
            # In DB persistieren
            try:
                now = datetime.now(timezone.utc).isoformat()
                expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO blocked_ips (ip, blocked_at, reason, expires_at) VALUES (?, ?, ?, ?)",
                        (ip, now, reason, expires)
                    )
                    conn.commit()
            except Exception as e:
                logger.error("[SecurityManager] IP-Block-Persist fehlgeschlagen: %s", e)
            logger.warning("[SecurityManager] IP blockiert: %s – %s", ip, reason)
            return jsonify({"error": "Rate-Limit überschritten – IP blockiert"}), 429

        size = request.content_length or 0
        if size > MAX_PAYLOAD_BYTES:
            reason = f"Payload zu groß: {size} Bytes"
            self._write_audit(ip, request.method, request.endpoint or request.path,
                              413, 0, size, True, reason)
            logger.warning("[SecurityManager] %s – %s", ip, reason)
            return jsonify({"error": "Payload-Größe überschritten (max. 10 MB)"}), 413

    def _after_request(self, response):
        ip = request.remote_addr or "unknown"
        duration = (time.perf_counter() - getattr(g, "_sec_start", time.perf_counter())) * 1000
        size = request.content_length or 0
        suspicious = response.status_code in SUSPICIOUS_STATUS
        reason = f"HTTP {response.status_code}" if suspicious else None
        self._write_audit(ip, request.method, request.endpoint or request.path,
                          response.status_code, duration, size, suspicious, reason)
        return response

    # ── Audit-DB ─────────────────────────────────────────────────────────────

    def _write_audit(self, ip, method, endpoint, status, duration_ms, payload_size,
                     suspicious, reason):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO security_audit_log
                   (timestamp, ip, method, endpoint, status_code, duration_ms,
                    payload_size, suspicious, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(), ip, method, endpoint,
                 status, round(duration_ms, 2), payload_size,
                 1 if suspicious else 0, reason),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error("[SecurityManager] Audit-Schreibfehler: %s", e)

    # ── Abfragen ──────────────────────────────────────────────────────────────

    def get_recent_logs(self, limit: int = 100) -> list:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM security_audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("[SecurityManager] Lese-Fehler: %s", e)
            return []

    def get_suspicious_logs(self, limit: int = 50) -> list:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM security_audit_log WHERE suspicious=1 ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("[SecurityManager] Lese-Fehler: %s", e)
            return []

    def get_stats(self) -> dict:
        try:
            conn = sqlite3.connect(self.db_path)
            total = conn.execute("SELECT COUNT(*) FROM security_audit_log").fetchone()[0]
            suspicious = conn.execute(
                "SELECT COUNT(*) FROM security_audit_log WHERE suspicious=1"
            ).fetchone()[0]
            avg_ms = conn.execute(
                "SELECT AVG(duration_ms) FROM security_audit_log WHERE duration_ms > 0"
            ).fetchone()[0] or 0
            top_ips = conn.execute(
                """SELECT ip, COUNT(*) as cnt FROM security_audit_log
                   GROUP BY ip ORDER BY cnt DESC LIMIT 5"""
            ).fetchall()
            conn.close()
            return {
                "total_requests": total,
                "suspicious_events": suspicious,
                "avg_response_ms": round(avg_ms, 1),
                "blocked_ips": list(self._blocked_ips),
                "top_ips": [{"ip": r[0], "count": r[1]} for r in top_ips],
            }
        except Exception as e:
            logger.error("[SecurityManager] Stats-Fehler: %s", e)
            return {}

    def log_auth_event(self, ip: str, event: str, success: bool, uid: str = None, details: str = None):
        """
        Loggt ein Auth-Event in die Datenbank.

        Args:
            ip: Client-IP-Adresse
            event: Event-Typ (z.B. 'token_valid', 'token_invalid', 'login_attempt')
            success: True wenn Auth erfolgreich
            uid: Firebase-UID (optional, nur bei Erfolg)
            details: Zusatzinfos (optional)
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO auth_audit_log
                       (timestamp, ip, event, success, uid, details)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (now, ip, event, int(success), uid, details)
                )
                conn.commit()
        except Exception as e:
            logger.error("[SecurityManager] Auth-Log fehlgeschlagen: %s", e)

    def purge_old_audit_logs(self, days: int = 90) -> int:
        """
        GDPR Art. 5 – Löscht Audit-Log-Einträge die älter als X Tage sind.
        Wird beim App-Start aufgerufen um die DB-Größe zu begrenzen.

        Returns: Anzahl gelöschter Einträge
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                result = conn.execute(
                    "DELETE FROM security_audit_log "
                    "WHERE datetime(timestamp) < datetime('now', ?)",
                    (f"-{days} days",)
                )
                deleted = result.rowcount
                conn.commit()
            if deleted > 0:
                logger.info("[SecurityManager] Purge: %d Audit-Logs älter als %d Tage gelöscht",
                            deleted, days)
            return deleted
        except Exception as e:
            logger.error("[SecurityManager] Purge fehlgeschlagen: %s", e)
            return 0

    def unblock_ip(self, ip: str):
        self._blocked_ips.discard(ip)
        self._ip_log[ip].clear()
        logger.info("[SecurityManager] IP entsperrt: %s", ip)
