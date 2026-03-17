"""
StudyAI – ML-Enhanced Spaced Repetition Engine
==============================================
Ersetzt den statischen SM-2 Algorithmus durch ein Machine Learning Modell.
Das Modell (Logistic Regression) lernt aus den Review-Logs des Users, um 
persönliche Vergessenskurven vorherzusagen.

Logik:
Features: [repetitions, letzes_intervall_minuten, letzte_bewertung]
Target: 1 (Erinnert: Gut/Einfach) oder 0 (Vergessen: Nochmal/Schwer)

Wenn p(Erinnert) > 0.9, wird das Intervall vergrößert.
"""

from __future__ import annotations
import math
import os
import joblib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
from sklearn.linear_model import SGDClassifier

logger = logging.getLogger(__name__)

# Basisverzeichnis für per-User-Modelle (kann via Env überschrieben werden)
_MODELS_DIR = Path(os.getenv("ML_MODELS_DIR", str(Path(__file__).parent.parent / "ml_models")))
_MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Fallback-Intervalle wie beim SM-2 zum Start
BASE_INTERVALS_MIN = {
    0: 0,       # Nochmal
    1: 10,      # Schwer
    2: 2880,    # Gut (2 Tage)
    3: 5760,    # Einfach (4 Tage)
}

# In-Memory Cache: uid → MLSpacedRepetitionEngine  (LRU über max. 100 User)
_engine_cache: Dict[str, "MLSpacedRepetitionEngine"] = {}
_CACHE_MAX = 100

def get_engine_for_user(uid: str) -> "MLSpacedRepetitionEngine":
    """
    Gibt die per-User-ML-Engine zurück (lazy-loaded, gecacht).
    Jeder User hat sein eigenes Modell – keine Cross-Contamination.
    """
    if uid not in _engine_cache:
        if len(_engine_cache) >= _CACHE_MAX:
            # Ältesten Eintrag entfernen (Simple LRU via dict ordering)
            oldest = next(iter(_engine_cache))
            del _engine_cache[oldest]
        _engine_cache[uid] = MLSpacedRepetitionEngine(uid=uid)
    return _engine_cache[uid]


class MLSpacedRepetitionEngine:
    def __init__(self, uid: str = "global"):
        # uid="global" nur als Fallback – produktiv immer uid des eingeloggten Users
        self.uid  = uid
        self.name = f"MLSpacedRepetitionEngine[{uid[:8]}]"
        self._unsaved_samples = 0
        self._model_path = _MODELS_DIR / f"sr_model_{uid}.pkl"
        self.model = self._load_model()
        logger.info(f"[{self.name}] initialisiert (model_path={self._model_path})")

    def _load_model(self) -> SGDClassifier:
        if self._model_path.exists():
            try:
                return joblib.load(self._model_path)
            except Exception as e:
                logger.warning(f"[{self.name}] Modell konnte nicht geladen werden, erstelle neues: {e}")

        # Neues Modell initialisieren. `loss="log_loss"` für Wahrscheinlichkeiten.
        model = SGDClassifier(loss="log_loss", learning_rate="optimal")
        # Dummy-Fit damit das Modell `predict_proba` kann, auch ohne Logs
        # Features: [reps, interval, last_rating, success_rate, log_interval]
        X_dummy = np.array([[0, 0, 0, 0.0, math.log1p(0)], [1, 2880, 2, 1.0, math.log1p(2880)]])
        y_dummy = np.array([0, 1])
        model.partial_fit(X_dummy, y_dummy, classes=np.array([0, 1]))
        return model

    def _save_model(self):
        try:
            joblib.dump(self.model, self._model_path)
        except Exception as e:
            logger.error(f"[{self.name}] Modell konnte nicht gespeichert werden: {e}")

    @staticmethod
    def new_card_state(card_id: str) -> Dict[str, Any]:
        """Initialer State für eine Karte."""
        return {
            "card_id": str(card_id),
            "repetitions": 0,
            "interval": 0.0,
            "next_review": datetime.now(timezone.utc).isoformat(),
            "last_rating": 0, # Default: 0
            "total_reviews": 0,
        }

    def train(self, logs: List[Dict[str, Any]]):
        """Trainiert das Modell inkrementell mit neuen Logs."""
        if not logs:
            return

        # success_rate aus allen Logs vorberechnen
        success_rate_all = sum(1 for l in logs if l.get("rating", 0) >= 2) / max(len(logs), 1)

        X = []
        y = []
        for log in logs:
            reps = float(log.get("repetitions", 0))
            interv = float(log.get("interval", 0))
            last_r = float(log.get("last_rating", 0))
            log_interval = math.log1p(interv)

            rating = log.get("rating", 0)

            target = 1 if rating >= 2 else 0  # 2 (Gut), 3 (Einfach) = erinnert

            X.append([reps, interv, last_r, success_rate_all, log_interval])
            y.append(target)

        if len(X) < 2:
            return  # Nicht genug Daten für Training

        # NaN/Inf check
        X_arr = np.array(X)
        y_arr = np.array(y)
        if not np.all(np.isfinite(X_arr)):
            logger.warning("[ML_SR] Training-Daten enthalten NaN/Inf – übersprungen")
            return

        self.model.partial_fit(X_arr, y_arr)
        self._unsaved_samples += len(X)
        if self._unsaved_samples >= 10:
            self._save_model()
            self._unsaved_samples = 0
            logger.info(f"[{self.name}] Modell mit {len(X)} Logs trainiert und gespeichert.")
        else:
            logger.info(f"[{self.name}] Modell mit {len(X)} Logs trainiert ({self._unsaved_samples}/10 bis zum Speichern).")

    def rate(self, state: Dict[str, Any], rating: int) -> Dict[str, Any]:
        """
        Berechnet das neue Intervall auf Basis einer Einzelbewertung.
        Nutzt das ML-Modell für Gut/Einfach, fällt für Nochmal/Schwer auf statisch zurück.
        """
        state = dict(state)
        now = datetime.now(timezone.utc)
        
        reps = state.get("repetitions", 0)
        prev_interval = state.get("interval", 0.0)
        last_rating = state.get("last_rating", 0)

        # Repetitions aktualisieren
        if rating < 2:
            state["repetitions"] = 0
        else:
            state["repetitions"] = reps + 1

        # Intervall berechnen
        if rating == 0:
            next_interval_min = 0.0
        elif rating == 1:
            next_interval_min = 10.0
        else:
            # Für Gut (2) und Einfach (3) nutzen wir das ML-Modell um The Multiplier abzugleichen.
            # Zuerst Basismultiplikator definieren
            base_multiplier = 2.0 if rating == 2 else 3.0
            
            if reps == 0:
                next_interval_min = BASE_INTERVALS_MIN[rating]
            else:
                # Vorhersagen, wie hoch die Erinnerungswahrscheinlichkeit beim aktuellen Intervall wäre
                success_rate_est = 1.0 if last_rating >= 2 else 0.0
                log_interval = math.log1p(prev_interval)
                features = np.array([[reps, prev_interval, last_rating, success_rate_est, log_interval]])
                prob = self.model.predict_proba(features)[0][1] # Wahrscheinlichkeit für "erinnert"
                
                # ML-Anpassung: Wenn Wahrscheinlichkeit sehr hoch, Intervall stärker wachsen lassen
                # Wenn niedrig, Intervall konservativer vergrößern
                if prob > 0.90:
                    ml_boost = 1.3
                elif prob > 0.75:
                    ml_boost = 1.0
                elif prob > 0.50:
                    ml_boost = 0.8
                else:
                    ml_boost = 0.5
                
                # Neues Intervall berechnen
                next_interval_min = prev_interval * base_multiplier * ml_boost
                
                # Minimum Checks
                min_min = BASE_INTERVALS_MIN[rating]
                next_interval_min = max(min_min, next_interval_min)

        state["interval"] = next_interval_min
        state["next_review"] = (now + timedelta(minutes=next_interval_min)).isoformat()
        state["last_rating"] = rating
        state["total_reviews"] = state.get("total_reviews", 0) + 1

        return state

    @staticmethod
    def is_due(state: Dict[str, Any]) -> bool:
        """Gibt True zurück wenn die Karte jetzt fällig ist."""
        try:
            next_review = datetime.fromisoformat(state["next_review"])
            now = datetime.now(timezone.utc)
            if next_review.tzinfo is None:
                next_review = next_review.replace(tzinfo=timezone.utc)
            return now >= next_review
        except (KeyError, ValueError):
            return True

    @staticmethod
    def time_until_due(state: Dict[str, Any]) -> str:
        """Menschenlesbare Fälligkeit."""
        try:
            next_review = datetime.fromisoformat(state["next_review"])
            now = datetime.now(timezone.utc)
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
