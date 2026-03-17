"""
StudyAI – Phase 7: Push-Notification Agent
==========================================
Versendet Web-Push-Benachrichtigungen (VAPID) und optional E-Mails
wenn Karteikarten zur Wiederholung fällig sind.

Abhängigkeiten:
    pip install pywebpush flask-mail

Umgebungsvariablen:
    VAPID_PRIVATE_KEY  – Base64-URL-kodierter privater VAPID-Key
    VAPID_PUBLIC_KEY   – Base64-URL-kodierter öffentlicher VAPID-Key
    VAPID_CLAIMS_EMAIL – Absender-E-Mail für VAPID-Claims (z.B. mailto:admin@example.com)
    MAIL_SERVER        – SMTP-Server (z.B. smtp.gmail.com)
    MAIL_PORT          – SMTP-Port (Standard: 587)
    MAIL_USERNAME      – SMTP-Benutzername / E-Mail-Adresse
    MAIL_PASSWORD      – SMTP-Passwort oder App-Passwort
    MAIL_DEFAULT_SENDER– Absender-Adresse (Standard: MAIL_USERNAME)

VAPID-Keys generieren (einmalig):
    python -c "from py_vapid import Vapid; v = Vapid(); v.generate_keys(); print('Private:', v.private_pem().decode()); print('Public:', v.public_key.public_bytes_raw().hex())"
    Oder einfacher:
    python agents/notification_agent.py --generate-keys
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── VAPID-Konfiguration ───────────────────────────────────────────────────────
VAPID_PRIVATE_KEY    = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY     = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS_EMAIL   = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@studyai.app")

# ── Mail-Konfiguration ────────────────────────────────────────────────────────
MAIL_SERVER          = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT            = int(os.getenv("MAIL_PORT", "587"))
MAIL_USERNAME        = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD        = os.getenv("MAIL_PASSWORD", "")
MAIL_DEFAULT_SENDER  = os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
MAIL_USE_TLS         = os.getenv("MAIL_USE_TLS", "true").lower() == "true"


def _push_enabled() -> bool:
    """True wenn VAPID-Keys konfiguriert sind."""
    return bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)


def _mail_enabled() -> bool:
    """True wenn SMTP konfiguriert ist."""
    return bool(MAIL_USERNAME and MAIL_PASSWORD)


def get_vapid_public_key() -> str:
    """Gibt den öffentlichen VAPID-Key zurück (für den Browser)."""
    return VAPID_PUBLIC_KEY


def send_push_notification(
    subscription: dict,
    title: str,
    body: str,
    url: str = "/",
    badge_count: int = 0,
) -> bool:
    """
    Sendet eine einzelne Web-Push-Notification an eine Subscription.

    subscription: { endpoint, p256dh, auth }
    Gibt True bei Erfolg zurück, False wenn Subscription ungültig/abgelaufen.
    """
    if not _push_enabled():
        logger.warning("[Push] VAPID-Keys nicht konfiguriert – Push übersprungen")
        return False

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.error("[Push] pywebpush nicht installiert. `pip install pywebpush`")
        return False

    payload = json.dumps({
        "title":      title,
        "body":       body,
        "url":        url,
        "badge":      badge_count,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })

    try:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {
                    "p256dh": subscription["p256dh"],
                    "auth":   subscription["auth"],
                },
            },
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={
                "sub": VAPID_CLAIMS_EMAIL,
                "aud": _get_audience(subscription["endpoint"]),
            },
        )
        logger.debug("[Push] Benachrichtigung gesendet an %s…", subscription["endpoint"][:40])
        return True

    except Exception as exc:
        # 410 Gone = Subscription ungültig / User hat Notifications deaktiviert
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            logger.info("[Push] Subscription abgelaufen (HTTP %s) – wird entfernt", status)
            return False
        logger.warning("[Push] Fehler beim Senden: %s", exc)
        return False


def _get_audience(endpoint: str) -> str:
    """Extrahiert Origin aus dem Endpoint für VAPID-Claims."""
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    return f"{parsed.scheme}://{parsed.netloc}"


def send_reminder_email(to_email: str, due_count: int, streak: int) -> bool:
    """
    Sendet eine Erinnerungs-E-Mail.
    Gibt True bei Erfolg zurück, False wenn Mail-Versand nicht konfiguriert.
    """
    if not _mail_enabled():
        logger.warning("[Mail] SMTP nicht konfiguriert – E-Mail übersprungen")
        return False

    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        streak_info = f"🔥 {streak}-Tage-Streak!" if streak > 0 else "Starte deinen Lern-Streak!"

        html = f"""
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lern-Erinnerung</title></head>
<body style="font-family:sans-serif;background:#f0f4ff;padding:24px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:32px;box-shadow:0 4px 20px rgba(0,0,0,.08)">
  <h1 style="font-size:28px;margin:0 0 8px">📚 StudyAI</h1>
  <p style="color:#6b7280;margin:0 0 24px">Deine Lern-Erinnerung</p>
  <div style="background:#f0f4ff;border-radius:12px;padding:20px;margin-bottom:24px;text-align:center">
    <div style="font-size:40px;margin-bottom:8px">🃏</div>
    <div style="font-size:32px;font-weight:700;color:#4f46e5">{due_count}</div>
    <div style="color:#6b7280">Karten zur Wiederholung fällig</div>
  </div>
  <div style="background:#fff7ed;border-radius:12px;padding:16px;margin-bottom:24px;text-align:center">
    <div style="font-size:24px">{streak_info}</div>
  </div>
  <a href="https://studyai.app" style="display:block;background:#4f46e5;color:#fff;text-align:center;padding:14px 24px;border-radius:10px;text-decoration:none;font-weight:600;font-size:16px">
    Jetzt lernen →
  </a>
  <p style="color:#9ca3af;font-size:12px;text-align:center;margin-top:24px">
    Du erhältst diese E-Mail weil du Lern-Erinnerungen aktiviert hast.<br>
    <a href="https://studyai.app" style="color:#9ca3af">Einstellungen ändern</a>
  </p>
</div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📚 {due_count} Karten warten auf dich!"
        msg["From"]    = MAIL_DEFAULT_SENDER
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS:
                server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_DEFAULT_SENDER, to_email, msg.as_string())

        logger.info("[Mail] Erinnerung gesendet an %s (%d fällige Karten)", to_email, due_count)
        return True

    except Exception as exc:
        logger.error("[Mail] Fehler beim Senden: %s", exc)
        return False


def send_reminders_for_all_users(db) -> dict:
    """
    Hauptfunktion für den Cron-Job: Prüft alle User mit Push-Subscriptions
    und sendet Erinnerungen wenn Karten fällig sind.

    Returns: { sent: int, skipped: int, errors: int, removed_stale: int }
    """
    from agents.ml_sr_engine import MLSpacedRepetitionEngine

    stats = {"sent": 0, "skipped": 0, "errors": 0, "removed_stale": 0}

    # Alle Subscriptions laden
    all_subs = db.get_all_push_subscriptions()
    if not all_subs:
        logger.info("[Reminder] Keine Push-Subscriptions vorhanden")
        return stats

    # Nach uid gruppieren
    by_uid: dict = {}
    for sub in all_subs:
        by_uid.setdefault(sub["uid"], []).append(sub)

    for uid, subs in by_uid.items():
        try:
            # Fällige Karten zählen
            due_count = _count_due_cards(db, uid)
            if due_count == 0:
                stats["skipped"] += 1
                continue

            streak = db.get_streak(uid)
            title  = "📚 Lernzeit!"
            body   = f"{due_count} Karte{'n' if due_count != 1 else ''} warten auf dich"
            if streak > 1:
                body += f" – 🔥 {streak}-Tage-Streak am Laufen!"

            # Push-Benachrichtigungen senden
            for sub in subs:
                ok = send_push_notification(
                    subscription=sub,
                    title=title,
                    body=body,
                    url="/",
                    badge_count=due_count,
                )
                if ok:
                    stats["sent"] += 1
                    db.update_push_last_used(uid, sub["endpoint"])
                else:
                    # Abgelaufene Subscription entfernen
                    db.delete_push_subscription(uid, sub["endpoint"])
                    stats["removed_stale"] += 1

        except Exception as exc:
            logger.error("[Reminder] Fehler für uid=%s: %s", uid, exc)
            stats["errors"] += 1

    logger.info("[Reminder] Fertig: %s", stats)
    return stats


def _count_due_cards(db, uid: str) -> int:
    """Zählt fällige Karten über alle Sessions eines Users."""
    from agents.ml_sr_engine import MLSpacedRepetitionEngine
    conn = db._get_conn()
    # Alle SR-States des Users laden
    rows = conn.execute("""
        SELECT ss.data
        FROM   sr_states ss
        JOIN   sessions s ON ss.session_id = s.id
        WHERE  s.user_id = ?
    """, (uid,)).fetchall()

    due = 0
    for row in rows:
        try:
            state = json.loads(row["data"])
            if MLSpacedRepetitionEngine.is_due(state):
                due += 1
        except Exception:
            pass
    return due


# ── CLI: VAPID-Keys generieren ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--generate-keys" in sys.argv:
        try:
            from py_vapid import Vapid
            import base64
            v = Vapid()
            v.generate_keys()
            priv = base64.urlsafe_b64encode(
                v.private_key.private_bytes(
                    encoding=__import__("cryptography.hazmat.primitives.serialization",
                                        fromlist=["Encoding"]).Encoding.Raw,
                    format=__import__("cryptography.hazmat.primitives.serialization",
                                      fromlist=["PrivateFormat"]).PrivateFormat.Raw,
                    encryption_algorithm=__import__(
                        "cryptography.hazmat.primitives.serialization",
                        fromlist=["NoEncryption"]).NoEncryption(),
                )
            ).decode().rstrip("=")
            pub = base64.urlsafe_b64encode(
                v.public_key.public_bytes(
                    encoding=__import__("cryptography.hazmat.primitives.serialization",
                                        fromlist=["Encoding"]).Encoding.X962,
                    format=__import__("cryptography.hazmat.primitives.serialization",
                                      fromlist=["PublicFormat"]).PublicFormat.UncompressedPoint,
                )
            ).decode().rstrip("=")
            print("Füge folgendes in deine .env ein:\n")
            print(f"VAPID_PRIVATE_KEY={priv}")
            print(f"VAPID_PUBLIC_KEY={pub}")
            print(f"VAPID_CLAIMS_EMAIL=mailto:deine@email.com")
        except ImportError:
            print("pywebpush nicht installiert. Führe zuerst aus: pip install pywebpush")
    else:
        print("Verwendung: python agents/notification_agent.py --generate-keys")
