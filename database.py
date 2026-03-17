"""
StudyAI – SQLite Datenbankschicht
==================================
Persistiert Sessions, Analyse-Ergebnisse, Flashcards, SR-States und Quiz-Logs.
Nutzt Python's eingebautes sqlite3 – keine externe Dependency nötig.
"""

import sqlite3
import json
import logging
import os
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("STUDYAI_DB", "studyai.db")


class Database:
    """Singleton-artiger SQLite-Zugriff. Thread-safe durch threading.local() + WAL-Modus."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._local = threading.local()  # NEU: thread-lokaler Storage
        self.init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def init_db(self):
        """Erstellt alle Tabellen falls sie nicht existieren. Migriert alte Schemas."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                user_id     TEXT NOT NULL DEFAULT 'local'
            );

            CREATE TABLE IF NOT EXISTS analysis_results (
                session_id  TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS flashcards (
                id          TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                data        TEXT NOT NULL,
                PRIMARY KEY (id, session_id),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sr_states (
                card_id     TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                data        TEXT NOT NULL,
                PRIMARY KEY (card_id, session_id),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sr_review_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                card_id     TEXT NOT NULL,
                rating      INTEGER,
                repetitions INTEGER,
                interval    REAL,
                last_rating INTEGER,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS learning_plans (
                session_id  TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at);
            CREATE INDEX IF NOT EXISTS idx_flashcards_session_id ON flashcards(session_id);
            CREATE INDEX IF NOT EXISTS idx_sr_states_session_id ON sr_states(session_id);
            CREATE INDEX IF NOT EXISTS idx_sr_logs_session_id ON sr_review_logs(session_id);
            CREATE INDEX IF NOT EXISTS idx_sr_logs_created_at ON sr_review_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_updated ON sessions(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sr_logs_session_created ON sr_review_logs(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_session ON analysis_results(session_id);
            CREATE INDEX IF NOT EXISTS idx_plans_session ON learning_plans(session_id);
            CREATE INDEX IF NOT EXISTS idx_flashcards_session ON flashcards(session_id);

            -- ── Monetarisierung / Billing ──────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS users (
                uid                 TEXT PRIMARY KEY,
                email               TEXT UNIQUE,
                tier                TEXT    NOT NULL DEFAULT 'free',
                stripe_customer_id  TEXT,
                stripe_sub_id       TEXT,
                sub_status          TEXT    DEFAULT 'inactive',
                sub_period_end      TEXT,
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS usage_tracking (
                uid             TEXT    NOT NULL,
                period          TEXT    NOT NULL,
                analyses        INTEGER DEFAULT 0,
                flashcard_gens  INTEGER DEFAULT 0,
                quiz_gens       INTEGER DEFAULT 0,
                api_tokens_in   INTEGER DEFAULT 0,
                api_tokens_out  INTEGER DEFAULT 0,
                PRIMARY KEY (uid, period),
                FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS token_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                uid             TEXT    NOT NULL,
                session_id      TEXT,
                agent           TEXT    NOT NULL,
                input_tokens    INTEGER DEFAULT 0,
                output_tokens   INTEGER DEFAULT 0,
                created_at      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_usage_uid_period ON usage_tracking(uid, period);
            CREATE INDEX IF NOT EXISTS idx_token_logs_uid   ON token_logs(uid);
            CREATE INDEX IF NOT EXISTS idx_users_stripe     ON users(stripe_customer_id);

            -- ── Phase 5: Chat-Tutor ────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS chat_messages (
                id          TEXT    PRIMARY KEY,
                session_id  TEXT    NOT NULL,
                user_id     TEXT    NOT NULL,
                role        TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_chat_session_id  ON chat_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_chat_created_at  ON chat_messages(session_id, created_at);

            -- ── Phase 6: Deck-Sharing ──────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS shared_decks (
                token       TEXT    PRIMARY KEY,
                session_id  TEXT    NOT NULL,
                uid         TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                expires_at  TEXT,
                view_count  INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_shared_decks_session ON shared_decks(session_id);
            CREATE INDEX IF NOT EXISTS idx_shared_decks_uid     ON shared_decks(uid);

            -- ── Phase 6: Badges / Achievements ────────────────────────────────
            CREATE TABLE IF NOT EXISTS user_badges (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                uid         TEXT    NOT NULL,
                badge_key   TEXT    NOT NULL,
                earned_at   TEXT    NOT NULL,
                UNIQUE(uid, badge_key)
            );
            CREATE INDEX IF NOT EXISTS idx_badges_uid ON user_badges(uid);
        """)
        conn.commit()
        # Migration: user_id-Spalte zu bestehenden Datenbanken hinzufügen
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'")
            conn.commit()
            logger.info("[Database] Migration: user_id-Spalte hinzugefügt")
        except Exception:
            pass  # Spalte existiert bereits
        logger.info("[Database] Initialisiert: %s", self.db_path)

    # ── Sessions ──────────────────────────────────────────────────────────────

    def create_session(self, name: str, user_id: str = "local") -> str:
        """Erstellt eine neue Session und gibt die ID zurück."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sessions (id, name, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?)",
            (session_id, name, now, now, user_id)
        )
        conn.commit()
        logger.info("[Database] Session erstellt: %s (%s) für User %s", name, session_id, user_id)
        return session_id

    def list_sessions(self, user_id: str = "local", limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Gibt Sessions eines Users mit Statistiken zurück, neueste zuerst. Unterstützt Paginierung."""
        limit  = min(max(int(limit), 1), 200)   # 1–200
        offset = max(int(offset), 0)
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                s.id,
                s.name,
                s.created_at,
                s.updated_at,
                COUNT(DISTINCT f.id) AS card_count,
                COUNT(DISTINCT r.id) AS review_count
            FROM sessions s
            LEFT JOIN flashcards f ON f.session_id = s.id
            LEFT JOIN sr_review_logs r ON r.session_id = s.id
            WHERE s.user_id = ?
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def touch_session(self, session_id: str):
        """Aktualisiert updated_at der Session."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()

    def get_session_owner(self, session_id: str) -> Optional[str]:
        """Gibt die user_id des Session-Besitzers zurück, oder None wenn nicht gefunden."""
        conn = self._get_conn()
        row = conn.execute("SELECT user_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row["user_id"] if row else None

    def rename_session(self, session_id: str, new_name: str):
        """Benennt eine Session um."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
            (new_name, now, session_id)
        )
        conn.commit()
        logger.info("[Database] Session umbenannt: %s → %s", session_id, new_name)

    def delete_session(self, session_id: str):
        """Löscht Session und alle zugehörigen Daten (CASCADE)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        logger.info("[Database] Session gelöscht: %s", session_id)

    # ── Analyse-Ergebnisse ────────────────────────────────────────────────────

    def save_analysis(self, session_id: str, data: dict):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO analysis_results (session_id, data) VALUES (?, ?)",
            (session_id, json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
        self.touch_session(session_id)

    def load_analysis(self, session_id: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data FROM analysis_results WHERE session_id = ?", (session_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    # ── Flashcards ────────────────────────────────────────────────────────────

    def save_flashcards(self, session_id: str, cards: List[dict]):
        """Speichert alle Flashcards einer Session (ersetzt vorhandene)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM flashcards WHERE session_id = ?", (session_id,))
        data = [
            (str(card.get("id", uuid.uuid4())), session_id, json.dumps(card, ensure_ascii=False))
            for card in cards
        ]
        conn.executemany(
            "INSERT INTO flashcards (id, session_id, data) VALUES (?, ?, ?)",
            data
        )
        conn.commit()
        self.touch_session(session_id)

    def load_flashcards(self, session_id: str) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT data FROM flashcards WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def get_flashcard(self, session_id: str, card_id: str) -> Optional[dict]:
        """Gibt eine einzelne Flashcard zurück, oder None wenn nicht gefunden."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data FROM flashcards WHERE id = ? AND session_id = ?",
            (card_id, session_id)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def add_flashcard(self, session_id: str, data: dict) -> str:
        """
        Fügt eine neue Flashcard zu einer Session hinzu.
        Gibt die neue card_id zurück.
        Wenn data kein 'id' enthält, wird automatisch eine generiert.
        """
        card_id = str(data.get("id", str(uuid.uuid4())[:8]))
        data = dict(data)
        data["id"] = card_id
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO flashcards (id, session_id, data) VALUES (?, ?, ?)",
            (card_id, session_id, json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
        self.touch_session(session_id)
        logger.info("[Database] Flashcard hinzugefügt: %s in Session %s", card_id, session_id)
        return card_id

    def update_flashcard(self, session_id: str, card_id: str, data: dict):
        """
        Aktualisiert die Daten einer einzelnen Flashcard.
        Merged die neuen Felder mit den vorhandenen (Partial-Update).
        """
        existing = self.get_flashcard(session_id, card_id)
        if existing is None:
            raise ValueError(f"Flashcard {card_id} nicht in Session {session_id} gefunden")
        merged = {**existing, **data, "id": card_id}   # id kann nicht überschrieben werden
        conn = self._get_conn()
        conn.execute(
            "UPDATE flashcards SET data = ? WHERE id = ? AND session_id = ?",
            (json.dumps(merged, ensure_ascii=False), card_id, session_id)
        )
        conn.commit()
        self.touch_session(session_id)
        logger.info("[Database] Flashcard aktualisiert: %s in Session %s", card_id, session_id)

    def delete_flashcard(self, session_id: str, card_id: str):
        """
        Löscht eine Flashcard und ihren SR-State.
        """
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM flashcards WHERE id = ? AND session_id = ?",
            (card_id, session_id)
        )
        conn.execute(
            "DELETE FROM sr_states WHERE card_id = ? AND session_id = ?",
            (card_id, session_id)
        )
        conn.commit()
        self.touch_session(session_id)
        logger.info("[Database] Flashcard gelöscht: %s aus Session %s", card_id, session_id)

    # ── Lernplan ──────────────────────────────────────────────────────────────

    def save_plan(self, session_id: str, data: dict):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO learning_plans (session_id, data) VALUES (?, ?)",
            (session_id, json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
        self.touch_session(session_id)

    def load_plan(self, session_id: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data FROM learning_plans WHERE session_id = ?", (session_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    # ── SR-States ─────────────────────────────────────────────────────────────

    def save_sr_states(self, session_id: str, states: Dict[str, dict]):
        """Speichert alle SR-States (Upsert)."""
        conn = self._get_conn()
        for card_id, state in states.items():
            conn.execute(
                "INSERT OR REPLACE INTO sr_states (card_id, session_id, data) VALUES (?, ?, ?)",
                (card_id, session_id, json.dumps(state, ensure_ascii=False))
            )
        conn.commit()
        self.touch_session(session_id)

    def load_sr_states(self, session_id: str) -> Dict[str, dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT card_id, data FROM sr_states WHERE session_id = ?", (session_id,)
        ).fetchall()
        return {r["card_id"]: json.loads(r["data"]) for r in rows}

    # ── SR Review Logs ────────────────────────────────────────────────────────

    def save_sr_logs(self, session_id: str, logs: List[dict]):
        """Hängt neue Review-Logs an (kein Replace – historisch)."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        for log in logs:
            conn.execute(
                """INSERT INTO sr_review_logs
                   (session_id, card_id, rating, repetitions, interval, last_rating, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    str(log.get("card_id", "")),
                    int(log.get("rating", 0)),
                    int(log.get("repetitions", 0)),
                    float(log.get("interval", 0)),
                    int(log.get("last_rating", 0)),
                    now,
                )
            )
        conn.commit()

    def load_sr_logs(self, session_id: str) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT card_id, rating, repetitions, interval, last_rating
               FROM sr_review_logs WHERE session_id = ? ORDER BY id""",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Komplette Session laden ───────────────────────────────────────────────

    def load_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Lädt alle Daten einer Session in ein Dict. Wenn user_id angegeben, wird Besitz geprüft."""
        conn = self._get_conn()
        if user_id is not None:
            session_row = conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
            ).fetchone()
        else:
            session_row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if not session_row:
            return None
        return {
            "session":    dict(session_row),
            "analysis":   self.load_analysis(session_id),
            "flashcards": self.load_flashcards(session_id),
            "plan":       self.load_plan(session_id),
            "sr_states":  self.load_sr_states(session_id),
            "sr_logs":    self.load_sr_logs(session_id),
        }

    # ── Komplett-Speichern ────────────────────────────────────────────────────

    def save_session_state(self, session_id: str, payload: dict):
        """
        Speichert den kompletten App-State einer Session.
        Payload: {analysis?, flashcards?, plan?, sr_states?, sr_logs?}
        """
        if "analysis" in payload and payload["analysis"]:
            self.save_analysis(session_id, payload["analysis"])
        if "flashcards" in payload and payload["flashcards"]:
            self.save_flashcards(session_id, payload["flashcards"])
        if "plan" in payload and payload["plan"]:
            self.save_plan(session_id, payload["plan"])
        if "sr_states" in payload and payload["sr_states"]:
            self.save_sr_states(session_id, payload["sr_states"])
        if "sr_logs" in payload and payload["sr_logs"]:
            self.save_sr_logs(session_id, payload["sr_logs"])
        self.touch_session(session_id)
        logger.info("[Database] Session gespeichert: %s", session_id)

    # ── GDPR / Datenschutz ────────────────────────────────────────────────────

    def delete_all_user_data(self, user_id: str) -> dict:
        """
        GDPR Art. 17 – Löscht ALLE Daten eines Users.
        Gibt Übersicht der gelöschten Datensätze zurück.
        Sessions-Kinder werden via ON DELETE CASCADE entfernt.
        """
        conn = self._get_conn()
        session_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchall()]
        for sid in session_ids:
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        conn.commit()
        deleted = {"sessions": len(session_ids)}
        logger.info("[GDPR] Alle Daten gelöscht für User %s: %s", user_id, deleted)
        return deleted

    def export_all_user_data(self, user_id: str) -> dict:
        """
        GDPR Art. 20 – Portabilität: Alle User-Daten als strukturiertes Dict.
        Enthält alle Sessions mit Analyse, Flashcards, SR-States und Lernplänen.
        """
        sessions = self.list_sessions(user_id=user_id, limit=200)
        export = {
            "user_id":     user_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "sessions":    [],
        }
        for s in sessions:
            full = self.load_session(s["id"], user_id=user_id)
            if full:
                export["sessions"].append(full)
        return export

    def purge_inactive_data(self, months: int = 24) -> int:
        """
        GDPR Art. 5 Speicherbegrenzung: Löscht Sessions die X Monate nicht
        verwendet wurden. Sollte regelmäßig (täglich/wöchentlich) ausgeführt werden.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).isoformat()
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id FROM sessions WHERE updated_at < ?", (cutoff,)
        ).fetchall()
        count = 0
        for row in rows:
            conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
            count += 1
        conn.commit()
        logger.info("[DB] Purge: %d Sessions älter als %d Monate gelöscht", count, months)
        return count

    # ── Monetarisierung / Billing ─────────────────────────────────────────────

    # Tier-Grenzen: -1 = unbegrenzt
    TIER_LIMITS: Dict[str, Dict[str, int]] = {
        "free":       {"analyses": 3,  "flashcard_gens": 3,  "quiz_gens": 5},
        "pro":        {"analyses": 50, "flashcard_gens": 50, "quiz_gens": 999},
        "university": {"analyses": -1, "flashcard_gens": -1, "quiz_gens": -1},
    }

    def ensure_user(self, uid: str, email: Optional[str] = None):
        """Erstellt User-Eintrag falls noch nicht vorhanden (idempotent)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute("""
            INSERT OR IGNORE INTO users (uid, email, tier, created_at, updated_at)
            VALUES (?, ?, 'free', ?, ?)
        """, (uid, email, now, now))
        conn.commit()

    def get_user_tier(self, uid: str) -> str:
        """Gibt den aktuellen Tier zurück. Pro nur wenn Abo aktiv."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT tier, sub_status FROM users WHERE uid = ?", (uid,)
        ).fetchone()
        if not row:
            return "free"
        if row["tier"] == "pro" and row["sub_status"] != "active":
            return "free"   # Abo abgelaufen → Auto-Downgrade auf Free
        return row["tier"]

    def increment_usage(self, uid: str, metric: str, amount: int = 1):
        """Erhöht Usage-Counter für den aktuellen Monat (Upsert)."""
        if metric not in ("analyses", "flashcard_gens", "quiz_gens",
                          "api_tokens_in", "api_tokens_out"):
            logger.warning("[DB] Unbekannte Metrik: %s", metric)
            return
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        conn = self._get_conn()
        conn.execute(f"""
            INSERT INTO usage_tracking (uid, period, {metric})
            VALUES (?, ?, ?)
            ON CONFLICT(uid, period) DO UPDATE SET {metric} = {metric} + ?
        """, (uid, period, amount, amount))
        conn.commit()

    def get_usage(self, uid: str) -> Dict[str, Any]:
        """Gibt die Usage-Zahlen für den aktuellen Monat zurück."""
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM usage_tracking WHERE uid = ? AND period = ?", (uid, period)
        ).fetchone()
        return dict(row) if row else {
            "analyses": 0, "flashcard_gens": 0, "quiz_gens": 0,
            "api_tokens_in": 0, "api_tokens_out": 0,
        }

    def check_quota(self, uid: str, metric: str) -> tuple:
        """
        Prüft ob User sein Kontingent noch nicht ausgeschöpft hat.
        Gibt (allowed: bool, used: int, limit: int) zurück.
        """
        tier  = self.get_user_tier(uid)
        limit = self.TIER_LIMITS.get(tier, self.TIER_LIMITS["free"]).get(metric, 0)
        if limit == -1:
            return True, 0, -1   # Unbegrenzt
        usage = self.get_usage(uid)
        used  = usage.get(metric, 0)
        return used < limit, used, limit

    def log_tokens(self, uid: str, session_id: Optional[str], agent: str,
                   tokens_in: int, tokens_out: int):
        """Protokolliert API-Token-Verbrauch und aktualisiert Usage-Tracking."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO token_logs (uid, session_id, agent, input_tokens, output_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (uid, session_id, agent, tokens_in, tokens_out,
              datetime.now(timezone.utc).isoformat()))
        conn.commit()
        # Usage-Tracking asynchron nicht blockieren – direkt aktualisieren
        self.increment_usage(uid, "api_tokens_in",  tokens_in)
        self.increment_usage(uid, "api_tokens_out", tokens_out)

    # ── Phase 5: Chat-Tutor ────────────────────────────────────────────────────

    def get_chat_history(self, session_id: str, user_id: str,
                         limit: int = 50) -> List[Dict[str, Any]]:
        """Gibt die Chat-History einer Session zurück (älteste zuerst)."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT id, role, content, created_at
            FROM   chat_messages
            WHERE  session_id = ? AND user_id = ?
            ORDER  BY created_at ASC
            LIMIT  ?
        """, (session_id, user_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def add_chat_message(self, session_id: str, user_id: str,
                         role: str, content: str) -> str:
        """Speichert eine Chat-Nachricht und gibt ihre ID zurück."""
        msg_id = str(uuid.uuid4())
        now    = datetime.now(timezone.utc).isoformat()
        conn   = self._get_conn()
        conn.execute("""
            INSERT INTO chat_messages (id, session_id, user_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (msg_id, session_id, user_id, role, content, now))
        conn.commit()
        return msg_id

    def delete_chat_history(self, session_id: str, user_id: str) -> int:
        """Löscht die gesamte Chat-History einer Session. Gibt Anzahl gelöschter Rows zurück."""
        conn = self._get_conn()
        cur  = conn.execute(
            "DELETE FROM chat_messages WHERE session_id = ? AND user_id = ?",
            (session_id, user_id)
        )
        conn.commit()
        return cur.rowcount

    # ── Phase 6: Deck-Sharing ──────────────────────────────────────────────────

    def create_share_token(self, session_id: str, uid: str, expires_days: int = 30) -> str:
        """Erstellt einen öffentlichen Share-Token für ein Flashcard-Deck."""
        import secrets
        from datetime import timedelta
        token = secrets.token_urlsafe(12)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=expires_days)).isoformat()
        conn = self._get_conn()
        # Alten Token für dieselbe Session löschen
        conn.execute("DELETE FROM shared_decks WHERE session_id = ? AND uid = ?",
                     (session_id, uid))
        conn.execute("""
            INSERT INTO shared_decks (token, session_id, uid, created_at, expires_at, view_count)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (token, session_id, uid, now.isoformat(), expires))
        conn.commit()
        return token

    def get_share_token(self, session_id: str, uid: str) -> Optional[Dict]:
        """Gibt den aktiven Share-Token einer Session zurück (oder None)."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM shared_decks WHERE session_id = ? AND uid = ?",
            (session_id, uid)
        ).fetchone()
        return dict(row) if row else None

    def get_shared_deck(self, token: str) -> Optional[Dict]:
        """Lädt ein geteiltes Deck per Token. Erhöht View-Count. Prüft Ablauf."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM shared_decks WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return None
        # Ablauf prüfen
        if row["expires_at"]:
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if exp < datetime.now(timezone.utc):
                    return None  # Abgelaufen
            except Exception:
                pass
        # View-Count erhöhen
        conn.execute("UPDATE shared_decks SET view_count = view_count + 1 WHERE token = ?",
                     (token,))
        conn.commit()
        return dict(row)

    def delete_share_token(self, session_id: str, uid: str) -> bool:
        """Widerruft den Share-Token einer Session."""
        conn = self._get_conn()
        cur = conn.execute(
            "DELETE FROM shared_decks WHERE session_id = ? AND uid = ?",
            (session_id, uid)
        )
        conn.commit()
        return cur.rowcount > 0

    # ── Phase 6: Gamification – Streak ────────────────────────────────────────

    def get_streak(self, uid: str) -> int:
        """Berechnet die aktuelle Lernstreak in Tagen (aufeinanderfolgende Tage mit Reviews)."""
        from datetime import date, timedelta
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT DISTINCT date(r.created_at) AS day
            FROM   sr_review_logs r
            JOIN   sessions s ON r.session_id = s.id
            WHERE  s.user_id = ?
            ORDER  BY day DESC
            LIMIT  365
        """, (uid,)).fetchall()
        if not rows:
            return 0
        streak = 0
        today  = date.today()
        for i, row in enumerate(rows):
            expected = today - timedelta(days=i)
            if row["day"] == str(expected):
                streak += 1
            else:
                break
        return streak

    def get_total_reviews(self, uid: str) -> int:
        """Gibt die Gesamtzahl abgeschlossener Reviews zurück."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT COUNT(*) AS cnt
            FROM   sr_review_logs r
            JOIN   sessions s ON r.session_id = s.id
            WHERE  s.user_id = ?
        """, (uid,)).fetchone()
        return row["cnt"] if row else 0

    def get_total_cards(self, uid: str) -> int:
        """Gibt die Gesamtzahl erstellter Flashcards zurück."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT COUNT(*) AS cnt
            FROM   flashcards f
            JOIN   sessions s ON f.session_id = s.id
            WHERE  s.user_id = ?
        """, (uid,)).fetchone()
        return row["cnt"] if row else 0

    # ── Phase 6: Badges ───────────────────────────────────────────────────────

    # Badge-Definitionen: key → (label, icon, description, condition_fn(stats))
    BADGES = {
        "first_review":    ("Erste Review",      "🎯", "Erste Lernkarte bewertet",       lambda s: s["total_reviews"] >= 1),
        "streak_3":        ("3-Tage-Streak",      "🔥", "3 Tage in Folge gelernt",        lambda s: s["streak"] >= 3),
        "streak_7":        ("Wochenchampion",     "🏆", "7 Tage in Folge gelernt",        lambda s: s["streak"] >= 7),
        "streak_30":       ("Monatsmarathon",     "💪", "30 Tage in Folge gelernt",       lambda s: s["streak"] >= 30),
        "cards_10":        ("Kartensammler",      "📚", "10 Karten erstellt",             lambda s: s["total_cards"] >= 10),
        "cards_100":       ("Kartenproffi",       "🃏", "100 Karten erstellt",            lambda s: s["total_cards"] >= 100),
        "reviews_50":      ("Fleißig",            "⚡", "50 Reviews abgeschlossen",       lambda s: s["total_reviews"] >= 50),
        "reviews_500":     ("Ausdauer",           "🚀", "500 Reviews abgeschlossen",      lambda s: s["total_reviews"] >= 500),
        "first_share":     ("Teilen ist Lernen",  "🔗", "Erstes Deck geteilt",            lambda s: s.get("shared", 0) >= 1),
    }

    def check_and_award_badges(self, uid: str) -> List[Dict]:
        """Prüft alle Badge-Bedingungen und vergibt neue Badges. Gibt neue Badges zurück."""
        stats = {
            "streak":        self.get_streak(uid),
            "total_reviews": self.get_total_reviews(uid),
            "total_cards":   self.get_total_cards(uid),
            "shared":        self._get_share_count(uid),
        }
        conn = self._get_conn()
        existing = {r["badge_key"] for r in conn.execute(
            "SELECT badge_key FROM user_badges WHERE uid = ?", (uid,)
        ).fetchall()}

        new_badges = []
        now = datetime.now(timezone.utc).isoformat()
        for key, (label, icon, desc, condition) in self.BADGES.items():
            if key not in existing and condition(stats):
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO user_badges (uid, badge_key, earned_at) VALUES (?, ?, ?)",
                        (uid, key, now)
                    )
                    new_badges.append({"key": key, "label": label, "icon": icon, "description": desc})
                except Exception:
                    pass
        conn.commit()
        return new_badges

    def get_user_badges(self, uid: str) -> List[Dict]:
        """Gibt alle Badges eines Users zurück."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT badge_key, earned_at FROM user_badges WHERE uid = ? ORDER BY earned_at ASC",
            (uid,)
        ).fetchall()
        result = []
        for row in rows:
            key = row["badge_key"]
            meta = self.BADGES.get(key, (key, "🏅", "", lambda _: True))
            result.append({
                "key":         key,
                "label":       meta[0],
                "icon":        meta[1],
                "description": meta[2],
                "earned_at":   row["earned_at"],
            })
        return result

    def _get_share_count(self, uid: str) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM shared_decks WHERE uid = ?", (uid,)
        ).fetchone()
        return row["cnt"] if row else 0

    # ── Phase 6: Admin-Stats ───────────────────────────────────────────────────

    def get_admin_stats(self) -> Dict:
        """Gibt aggregierte Plattform-Statistiken zurück (nur für Admins)."""
        conn = self._get_conn()
        stats = {}
        # User-Zähler
        stats["total_sessions"] = (conn.execute(
            "SELECT COUNT(*) AS c FROM sessions"
        ).fetchone() or {}).get("c", 0)
        stats["unique_users"] = (conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM sessions WHERE user_id != 'local'"
        ).fetchone() or {}).get("c", 0)
        stats["total_flashcards"] = (conn.execute(
            "SELECT COUNT(*) AS c FROM flashcards"
        ).fetchone() or {}).get("c", 0)
        stats["total_reviews"] = (conn.execute(
            "SELECT COUNT(*) AS c FROM sr_review_logs"
        ).fetchone() or {}).get("c", 0)
        stats["total_chat_messages"] = (conn.execute(
            "SELECT COUNT(*) AS c FROM chat_messages"
        ).fetchone() or {}).get("c", 0)
        stats["shared_decks_active"] = (conn.execute(
            "SELECT COUNT(*) AS c FROM shared_decks"
        ).fetchone() or {}).get("c", 0)
        # Pro-User
        stats["pro_users"] = (conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE tier = 'pro' AND sub_status = 'active'"
        ).fetchone() or {}).get("c", 0)
        # Aktivste Sessions der letzten 7 Tage
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        stats["active_sessions_7d"] = (conn.execute(
            "SELECT COUNT(DISTINCT session_id) AS c FROM sr_review_logs WHERE created_at >= ?",
            (since,)
        ).fetchone() or {}).get("c", 0)
        # API-Token-Verbrauch gesamt
        row = conn.execute(
            "SELECT SUM(input_tokens) AS inp, SUM(output_tokens) AS out FROM token_logs"
        ).fetchone()
        stats["total_tokens_in"]  = row["inp"] or 0 if row else 0
        stats["total_tokens_out"] = row["out"] or 0 if row else 0
        return stats
