"""
StudyAI – Stripe Billing Integration
=====================================
Verwaltet Stripe Checkout Sessions, Customer Portal und Webhook-Verarbeitung.

Konfiguration via .env:
  STRIPE_SECRET_KEY       = sk_live_... (oder sk_test_... für Tests)
  STRIPE_PRICE_PRO_MONTHLY= price_xxx   (aus Stripe Dashboard)
  STRIPE_WEBHOOK_SECRET   = whsec_...   (aus Stripe Webhook-Einstellung)

Setup:
  1. pip install stripe>=8.0.0
  2. Stripe Dashboard → Produkte → Preis erstellen (€9,99/Monat)
  3. Stripe Dashboard → Webhooks → Endpoint hinzufügen:
       URL: https://deine-domain.de/api/webhooks/stripe
       Events: customer.subscription.created, .updated, .deleted,
               invoice.payment_failed, invoice.payment_succeeded
"""

import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Stripe lazy import – App startet auch ohne stripe-Paket (degraded mode)
_stripe = None


def _get_stripe():
    global _stripe
    if _stripe is None:
        try:
            import stripe as _s
            _s.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            if not _s.api_key:
                logger.warning("[Stripe] STRIPE_SECRET_KEY nicht gesetzt – Billing deaktiviert.")
            _stripe = _s
        except ImportError:
            logger.warning(
                "[Stripe] stripe-Paket fehlt. Installieren: pip install stripe>=8.0.0"
            )
    return _stripe


def is_configured() -> bool:
    """True wenn Stripe-Key gesetzt und stripe-Paket installiert ist."""
    return bool(os.getenv("STRIPE_SECRET_KEY", "")) and _get_stripe() is not None


# ── Checkout & Portal ─────────────────────────────────────────────────────────

def create_checkout_session(uid: str, email: str, success_url: str, cancel_url: str) -> str:
    """
    Erstellt eine Stripe Checkout Session für Pro-Abo.
    Gibt die Checkout-URL zurück (Redirect im Browser).
    """
    stripe = _get_stripe()
    if not stripe:
        raise RuntimeError("Stripe nicht konfiguriert")
    price_id = os.getenv("STRIPE_PRICE_PRO_MONTHLY", "")
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_PRO_MONTHLY nicht gesetzt")

    customer = _get_or_create_customer(uid, email)
    session = stripe.checkout.Session.create(
        customer=customer.id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        metadata={"firebase_uid": uid},
        allow_promotion_codes=True,
    )
    logger.info("[Stripe] Checkout Session erstellt für uid=%s", uid)
    return session.url


def create_portal_session(uid: str, return_url: str) -> str:
    """
    Erstellt eine Stripe Customer Portal Session (Abo-Verwaltung).
    Gibt die Portal-URL zurück.
    """
    stripe = _get_stripe()
    if not stripe:
        raise RuntimeError("Stripe nicht konfiguriert")
    from database import db
    conn = db._get_conn()
    row = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE uid = ?", (uid,)
    ).fetchone()
    if not row or not row["stripe_customer_id"]:
        raise ValueError("Kein Stripe-Kundenkonto gefunden. Bitte zuerst ein Abo abschließen.")
    portal = stripe.billing_portal.Session.create(
        customer=row["stripe_customer_id"],
        return_url=return_url,
    )
    return portal.url


# ── Webhook-Verarbeitung ──────────────────────────────────────────────────────

def handle_webhook(payload: bytes, sig_header: str) -> bool:
    """
    Verarbeitet Stripe-Webhook-Events (Signaturprüfung + State-Update in DB).
    Gibt True bei Erfolg, False bei ungültiger Signatur zurück.
    """
    stripe = _get_stripe()
    if not stripe:
        return False
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.warning("[Stripe] STRIPE_WEBHOOK_SECRET fehlt – Webhooks unsicher!")
        return False
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning("[Stripe] Ungültiger Webhook: %s", e)
        return False

    etype = event["type"]
    data  = event["data"]["object"]
    logger.info("[Stripe] Webhook empfangen: %s", etype)

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        _update_subscription(data, data.get("status", "active"))
    elif etype == "customer.subscription.deleted":
        _update_subscription(data, "canceled")
    elif etype == "invoice.payment_failed":
        _handle_payment_failed(data)
    elif etype == "invoice.payment_succeeded":
        _handle_payment_succeeded(data)
    else:
        logger.debug("[Stripe] Unbehandelter Event-Typ: %s", etype)

    return True


# ── Interne Hilfsfunktionen ───────────────────────────────────────────────────

def _get_or_create_customer(uid: str, email: str):
    """Gibt existierenden Stripe-Kunden zurück oder erstellt neuen."""
    stripe = _get_stripe()
    from database import db
    conn = db._get_conn()
    row = conn.execute(
        "SELECT stripe_customer_id FROM users WHERE uid = ?", (uid,)
    ).fetchone()
    if row and row["stripe_customer_id"]:
        try:
            return stripe.Customer.retrieve(row["stripe_customer_id"])
        except stripe.error.InvalidRequestError:
            pass  # Kunde gelöscht → neu erstellen

    customer = stripe.Customer.create(
        email=email,
        metadata={"firebase_uid": uid},
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE users SET stripe_customer_id = ?, updated_at = ? WHERE uid = ?",
        (customer.id, now, uid),
    )
    conn.commit()
    logger.info("[Stripe] Neuer Kunde erstellt: %s für uid=%s", customer.id, uid)
    return customer


def _resolve_uid_from_subscription(sub_data: dict) -> str | None:
    """Ermittelt firebase_uid aus Subscription-Metadata (Fallback: Customer-Lookup)."""
    uid = sub_data.get("metadata", {}).get("firebase_uid")
    if uid:
        return uid
    # Fallback: Customer-Metadata abfragen
    stripe = _get_stripe()
    if stripe:
        try:
            customer = stripe.Customer.retrieve(sub_data["customer"])
            return customer.metadata.get("firebase_uid")
        except Exception as e:
            logger.warning("[Stripe] Customer-Lookup fehlgeschlagen: %s", e)
    return None


def _update_subscription(sub_data: dict, status: str):
    """Aktualisiert Tier und Sub-Status in der DB basierend auf Stripe-Event."""
    uid = _resolve_uid_from_subscription(sub_data)
    if not uid:
        logger.error("[Stripe] Kein firebase_uid in Subscription %s", sub_data.get("id"))
        return

    tier = "pro" if status == "active" else "free"
    period_end_ts = sub_data.get("current_period_end", 0)
    period_end = datetime.fromtimestamp(
        period_end_ts, tz=timezone.utc
    ).isoformat() if period_end_ts else None
    now = datetime.now(timezone.utc).isoformat()

    from database import db
    conn = db._get_conn()
    conn.execute("""
        UPDATE users SET tier = ?, sub_status = ?, stripe_sub_id = ?,
                         sub_period_end = ?, updated_at = ?
        WHERE uid = ?
    """, (tier, status, sub_data.get("id"), period_end, now, uid))
    conn.commit()
    logger.info("[Stripe] Sub-Update: uid=%s tier=%s status=%s", uid, tier, status)


def _handle_payment_failed(invoice_data: dict):
    """Setzt sub_status auf 'past_due' wenn Zahlung fehlschlägt."""
    customer_id = invoice_data.get("customer")
    if not customer_id:
        return
    from database import db
    conn = db._get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE users SET sub_status = 'past_due', updated_at = ? WHERE stripe_customer_id = ?",
        (now, customer_id),
    )
    conn.commit()
    logger.warning("[Stripe] Zahlung fehlgeschlagen für Kunde %s", customer_id)


def _handle_payment_succeeded(invoice_data: dict):
    """Stellt aktiven Status wieder her nach erfolgreicher Zahlung."""
    customer_id = invoice_data.get("customer")
    if not customer_id:
        return
    from database import db
    conn = db._get_conn()
    now = datetime.now(timezone.utc).isoformat()
    # Nur wenn Tier = pro → Sub wieder aktivieren
    conn.execute("""
        UPDATE users SET sub_status = 'active', updated_at = ?
        WHERE stripe_customer_id = ? AND tier = 'pro'
    """, (now, customer_id))
    conn.commit()
    logger.info("[Stripe] Zahlung erfolgreich für Kunde %s", customer_id)
