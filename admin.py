"""
StudyAI – Admin-Dashboard Helpers (Phase 6)
============================================
Enthält Hilfsfunktionen für das Admin-Dashboard.
Endpoints sind in server.py definiert.
Zugriff nur für UIDs in der ADMIN_UIDS-Umgebungsvariable.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Komma-getrennte Liste erlaubter Admin-UIDs aus .env
_ADMIN_UIDS = set(
    uid.strip()
    for uid in os.getenv("ADMIN_UIDS", "").split(",")
    if uid.strip()
)


def is_admin(uid: str) -> bool:
    """Gibt True zurück wenn der User ein Admin ist."""
    if not _ADMIN_UIDS:
        # Kein Admin konfiguriert → nur localhost-Zugriff (server.py prüft das)
        return False
    return uid in _ADMIN_UIDS


def format_tokens(n: int) -> str:
    """Formatiert Token-Zahlen lesbar: 1234567 → '1.23M'"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def estimate_cost_usd(tokens_in: int, tokens_out: int) -> float:
    """
    Schätzt API-Kosten in USD für claude-sonnet-4-5.
    Preise: $3/MTok Input, $15/MTok Output (Stand 2025).
    """
    cost_in  = (tokens_in  / 1_000_000) * 3.0
    cost_out = (tokens_out / 1_000_000) * 15.0
    return round(cost_in + cost_out, 4)
