"""
StudyAI – Firebase Firestore Sync (optional)
=============================================
Optionale Cloud-Synchronisation via Google Firebase Firestore.
Aktiv nur wenn FIREBASE_CREDENTIALS_PATH + FIREBASE_PROJECT_ID gesetzt sind.
Ohne Konfiguration: No-Op – App funktioniert weiterhin nur mit SQLite.

Setup:
  1. Firebase-Projekt: https://console.firebase.google.com
  2. Project Settings → Service Accounts → "Generate new private key"
  3. JSON speichern und Pfad in .env eintragen:
       FIREBASE_CREDENTIALS_PATH=C:/pfad/zu/serviceAccountKey.json
       FIREBASE_PROJECT_ID=dein-projekt-id
  4. pip install firebase-admin

Firestore-Kollektion: studyai_sessions/{session_id}
"""

import os
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class FirebaseSync:
    """
    Optionale Firestore-Sync-Schicht.
    Alle Methoden sind stille No-Ops wenn Firebase nicht konfiguriert ist.
    """

    COLLECTION = "studyai_sessions"

    def __init__(self):
        self.enabled = False
        self._db = None
        self._try_init()

    def _try_init(self):
        creds_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "").strip()
        project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()

        if not creds_path or not project_id:
            logger.info(
                "[FirebaseSync] Nicht konfiguriert – Cloud-Sync deaktiviert. "
                "Setze FIREBASE_CREDENTIALS_PATH + FIREBASE_PROJECT_ID in .env."
            )
            return

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore as fs

            if not firebase_admin._apps:
                cred = credentials.Certificate(creds_path)
                firebase_admin.initialize_app(cred, {"projectId": project_id})

            self._db = fs.client()
            self.enabled = True
            logger.info("[FirebaseSync] ✅ Verbunden: %s", project_id)

        except ImportError:
            logger.warning(
                "[FirebaseSync] firebase-admin fehlt. Installieren: pip install firebase-admin"
            )
        except FileNotFoundError:
            logger.error("[FirebaseSync] Credentials nicht gefunden: %s", creds_path)
        except Exception as e:
            logger.error("[FirebaseSync] Initialisierungsfehler: %s", e)

    # ── Sync ─────────────────────────────────────────────────────────────────

    def sync_session(self, session_id: str, payload: dict):
        """Synchronisiert Session asynchron zu Firestore (non-blocking)."""
        if not self.enabled:
            return
        threading.Thread(
            target=self._sync_bg, args=(session_id, payload), daemon=True
        ).start()

    def _sync_bg(self, session_id: str, payload: dict):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._db.collection(self.COLLECTION).document(session_id).set(
                    payload, merge=True
                )
                logger.debug("[FirebaseSync] Session %s synchronisiert", session_id)
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        "[FirebaseSync] Sync-Versuch %d fehlgeschlagen für %s: %s – retry in %ds",
                        attempt + 1, session_id, e, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "[FirebaseSync] Sync endgültig fehlgeschlagen für %s nach %d Versuchen: %s",
                        session_id, max_retries, e,
                    )

    def delete_session(self, session_id: str):
        """Löscht Session aus Firestore (non-blocking)."""
        if not self.enabled:
            return
        threading.Thread(
            target=self._delete_bg, args=(session_id,), daemon=True
        ).start()

    def _delete_bg(self, session_id: str):
        try:
            self._db.collection(self.COLLECTION).document(session_id).delete()
        except Exception as e:
            logger.error("[FirebaseSync] Delete-Fehler %s: %s", session_id, e)

    def load_session(self, session_id: str) -> Optional[dict]:
        """Lädt Session aus Firestore (synchron, als Fallback)."""
        if not self.enabled:
            return None
        try:
            doc = self._db.collection(self.COLLECTION).document(session_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error("[FirebaseSync] Load-Fehler %s: %s", session_id, e)
            return None

    def list_sessions(self) -> list:
        """Listet alle Cloud-Sessions auf."""
        if not self.enabled:
            return []
        try:
            return [
                {"id": doc.id, **doc.to_dict()}
                for doc in self._db.collection(self.COLLECTION).stream()
            ]
        except Exception as e:
            logger.error("[FirebaseSync] List-Fehler: %s", e)
            return []

    def delete_all_user_sessions(self, user_id: str):
        """GDPR Art. 17: Löscht alle Firestore-Dokumente eines Users (non-blocking)."""
        if not self.enabled:
            return
        threading.Thread(
            target=self._delete_user_sessions_bg, args=(user_id,), daemon=True
        ).start()

    def _delete_user_sessions_bg(self, user_id: str):
        try:
            docs = (
                self._db.collection(self.COLLECTION)
                .where("user_id", "==", user_id)
                .stream()
            )
            deleted = 0
            for doc in docs:
                doc.reference.delete()
                deleted += 1
            logger.info(
                "[FirebaseSync] GDPR: %d Dokumente gelöscht für User %s", deleted, user_id
            )
        except Exception as e:
            logger.error(
                "[FirebaseSync] Bulk-Delete fehlgeschlagen für User %s: %s", user_id, e
            )

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self.enabled

    def status(self) -> dict:
        return {
            "firebase_sync": self.enabled,
            "project": os.getenv("FIREBASE_PROJECT_ID") if self.enabled else None,
        }
