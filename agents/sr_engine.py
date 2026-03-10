"""
StudyAI – Spaced Repetition Engine (SM-2)
==========================================
Reine Mathematik – kein Claude-API-Aufruf.

Algorithmus: SuperMemo SM-2 (erweitert mit benutzerfreundlichen Intervallen)
Bewertungsskala:
    0 – "Nochmal"  → sofort wiederholen
    1 – "Schwer"   → +10 Minuten
    2 – "Gut"      → +2 Tage
    3 – "Einfach"  → +4 Tage

Kartenstate (pro card_id):
    {
        "card_id":       str,
        "repetitions":   int,           # Wie oft hintereinander ≥ "Gut"
        "interval":      float,         # Aktuelles Intervall in Minuten
        "easiness":      float,         # Ease-Factor (EF), startet bei 2.5
        "next_review":   ISO-8601-str,  # Nächster Wiederholungszeitpunkt
        "last_rating":   int | None,    # Letzte Bewertung (0-3)
        "total_reviews": int,
    }
"""

from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

# ── Intervall-Tabelle (basierend auf User-Anforderung) ─────────────────────────
INTERVALS_MINUTES: Dict[int, float] = {
    0: 0,       # Nochmal  → sofort (0 min)
    1: 10,      # Schwer   → +10 min
    2: 2880,    # Gut      → +2 Tage (2 × 1440)
    3: 5760,    # Einfach  → +4 Tage (4 × 1440)
}

RATING_LABELS: Dict[int, str] = {
    0: "Nochmal",
    1: "Schwer",
    2: "Gut",
    3: "Einfach",
}

# SM-2 Quality-Mapping (0-3 → 0-5 Skala für EF-Berechnung)
SM2_QUALITY: Dict[int, int] = {0: 0, 1: 2, 2: 4, 3: 5}

DEFAULT_EF = 2.5
MIN_EF = 1.3


class SREngine:
    """
    Stateless SM-2-Berechnungen.
    Der State wird vom Client (localStorage) oder Server (Session-Dict) verwaltet.
    """

    @staticmethod
    def new_card_state(card_id: str) -> Dict[str, Any]:
        """Erstellt den initialen Lernstate für eine neue Karte."""
        return {
            "card_id"      : str(card_id),
            "repetitions"  : 0,
            "interval"     : 0.0,
            "easiness"     : DEFAULT_EF,
            "next_review"  : datetime.now(timezone.utc).isoformat(),
            "last_rating"  : None,
            "total_reviews": 0,
        }

    @staticmethod
    def rate(state: Dict[str, Any], rating: int) -> Dict[str, Any]:
        """
        Berechnet den neuen State nach einer Bewertung.

        Args:
            state:  Aktueller Kartenstate (aus new_card_state oder vorherigem rate()-Aufruf)
            rating: 0=Nochmal, 1=Schwer, 2=Gut, 3=Einfach

        Returns:
            Neuer State-Dict mit aktualisiertem next_review, interval, easiness, repetitions
        """
        if rating not in INTERVALS_MINUTES:
            raise ValueError(f"Ungültige Bewertung: {rating}. Muss 0-3 sein.")

        state = dict(state)  # Kopie – immutable approach
        quality = SM2_QUALITY[rating]
        now     = datetime.now(timezone.utc)

        # ── Neue Repetitions-Zahl ──────────────────────────────────────────────
        if rating < 2:  # Nochmal oder Schwer → Reset
            state["repetitions"] = 0
        else:
            state["repetitions"] = state.get("repetitions", 0) + 1

        # ── Neues Intervall (in Minuten) ───────────────────────────────────────
        base_minutes = INTERVALS_MINUTES[rating]

        if rating == 0:
            # Sofort wiederholen
            next_review = now
        elif rating == 1:
            # Schwer: 10 Minuten – keine EF-Anpassung für Langzeit
            next_review = now + timedelta(minutes=base_minutes)
        else:
            # Gut / Einfach: SM-2 Langzeit-Intervall
            reps     = state["repetitions"]
            ef       = state.get("easiness", DEFAULT_EF)
            prev_int = state.get("interval", 0)

            if reps <= 1:
                interval_days = 1
            elif reps == 2:
                interval_days = 3
            else:
                # SM-2: interval = prev_interval × EF
                interval_days = math.ceil(prev_int / 1440 * ef)

            # Minimum 2 Tage (Gut) oder 4 Tage (Einfach)
            min_days = 2 if rating == 2 else 4
            interval_days  = max(min_days, interval_days)
            base_minutes   = interval_days * 1440
            next_review    = now + timedelta(minutes=base_minutes)

        # ── Ease Factor anpassen (SM-2 Formel) ────────────────────────────────
        if rating >= 2:  # Nur bei "Gut" und "Einfach" EF anpassen
            ef  = state.get("easiness", DEFAULT_EF)
            ef += 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
            ef  = max(MIN_EF, round(ef, 4))
            state["easiness"] = ef

        state["interval"]      = base_minutes
        state["next_review"]   = next_review.isoformat()
        state["last_rating"]   = rating
        state["total_reviews"] = state.get("total_reviews", 0) + 1

        return state

    @staticmethod
    def is_due(state: Dict[str, Any]) -> bool:
        """Gibt True zurück wenn die Karte jetzt fällig ist."""
        try:
            next_review = datetime.fromisoformat(state["next_review"])
            now         = datetime.now(timezone.utc)
            # Falls next_review kein Timezone-Info hat, UTC annehmen
            if next_review.tzinfo is None:
                next_review = next_review.replace(tzinfo=timezone.utc)
            return now >= next_review
        except (KeyError, ValueError):
            return True

    @staticmethod
    def time_until_due(state: Dict[str, Any]) -> str:
        """Gibt eine menschenlesbare Zeit bis zur nächsten Fälligkeit zurück."""
        try:
            next_review = datetime.fromisoformat(state["next_review"])
            now         = datetime.now(timezone.utc)
            if next_review.tzinfo is None:
                next_review = next_review.replace(tzinfo=timezone.utc)
            delta = next_review - now
            if delta.total_seconds() <= 0:
                return "Jetzt fällig"
            minutes = int(delta.total_seconds() / 60)
            if minutes < 60:
                return f"in {minutes} Min."
            hours = minutes // 60
            if hours < 24:
                return f"in {hours} Std."
            days = hours // 24
            return f"in {days} Tag{'en' if days > 1 else ''}"
        except (KeyError, ValueError):
            return "Unbekannt"

    @staticmethod
    def batch_rate(states: Dict[str, Any], card_id: str, rating: int) -> Dict[str, Any]:
        """Bewertet eine Karte in einem State-Dict und gibt das aktualisierte Dict zurück."""
        card_state = states.get(str(card_id)) or SREngine.new_card_state(str(card_id))
        states[str(card_id)] = SREngine.rate(card_state, rating)
        return states
