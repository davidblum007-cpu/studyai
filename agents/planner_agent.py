"""
StudyAI – Planner Agent
=======================
Verantwortlich für:
- Empfang der Phase-1-Themen + Prüfungsdatum + tägliche Lernzeit
- Intelligente Gewichtung schwerer Themen (Schwierigkeit > 7 → mehr Zeit)
- Automatische 2-Puffertage vor der Prüfung für Wiederholungen
- Claude claude-3-5-sonnet Prompt-Engineering für den Lernplan
- JSON-Parsing & Validierung; lokaler Fallback wenn Claude-Ausgabe fehlerhaft
"""

import os
import json
import logging
import re
from datetime import date, timedelta, datetime
from typing import List, Dict

import anthropic

logger = logging.getLogger(__name__)

MODEL          = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

MAX_TOKENS     = 4096
PUFFER_TAGE    = 2   # Tage vor der Prüfung die als Wiederholung reserviert sind

# ── System-Prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Du bist ein erfahrener Lerncoach und Zeitplanungsexperte. 
Du erhältst eine Themenlist aus einem Vorlesungsskript und erstellst daraus 
einen optimierten, realistischen Lernplan.

Regeln:
- Schwere Themen (Schwierigkeit ≥ 7) bekommen proportional mehr Lerntage
- Einfache Themen (Schwierigkeit ≤ 3) können gebündelt werden
- Die letzten 2 Tage vor der Prüfung sind IMMER Puffertage für Wiederholungen
- Verteile Themen gleichmäßig über die verfügbaren Tage
- Jeder Tag hat GENAU einen Eintrag (kein Tag darf leer bleiben)

Du antwortest IMMER und AUSSCHLIESSLICH mit gültigem JSON. Kein Fließtext."""

# ── User-Prompt-Template ─────────────────────────────────────────────────────
USER_PROMPT_TEMPLATE = """Erstelle einen Lernplan mit folgenden Parametern:

PRÜFUNGSDATUM: {pruefungsdatum}
VERFÜGBARE LERNTAGE: {lerntage} (vom {start_datum} bis {letzter_lerntag})
TÄGLICHE LERNZEIT: {stunden_pro_tag} Stunden
PUFFERTAGE (Wiederholung): {puffer_start} und {puffer_ende}

THEMEN AUS DEM SKRIPT:
{themen_liste}

AUFGABE:
Verteile diese {anzahl_themen} Themen auf die {lerntage} Lerntage.
- Schwierige Themen (≥ 7/10) bekommen MEHR Tage
- Einfache Themen (≤ 3/10) können an einem Tag kombiniert werden
- Gib für jeden Tag einen konkreten Fokuspunkt an
- Die letzten 2 Tage ({puffer_start}, {puffer_ende}) sind Wiederholungstage

ANTWORT als JSON-Array (ein Eintrag pro Tag):
[
  {{
    "datum": "YYYY-MM-DD",
    "thema": "Thema-Titel oder 'Wiederholung: Thema1, Thema2'",
    "fokus_punkt": "Was genau heute geübt/gelernt wird (1 Satz)",
    "schwierigkeit": 1-10,
    "lernzeit_stunden": {stunden_pro_tag},
    "ist_puffertag": false,
    "tipps": "1 konkreter Lerntipp für heute"
  }}
]"""


class PlannerAgent:
    """
    Coworker-Agent: KI-Lernplan-Generator.
    Erzeugt aus Phase-1-Output einen tagesgenauen Lernkalender.
    """

    def __init__(self, token_callback=None):
        self.name = "PlannerAgent"
        self._token_callback = token_callback  # Billing: Wird nach jedem API-Call aufgerufen
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key.startswith("sk-ant-DEIN"):
            raise EnvironmentError("ANTHROPIC_API_KEY nicht gesetzt.")
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"[{self.name}] initialisiert (Modell: {MODEL})")

    def create_plan(
        self,
        alle_themen: List[Dict],
        pruefungsdatum: str,
        stunden_pro_tag: float,
    ) -> Dict:
        """
        Erstellt einen tagesgenauen Lernplan.

        Args:
            alle_themen: Liste aller Themen aus Phase-1-Output
                         [{'titel', 'wichtigkeit', 'schwierigkeit', 'kurzfassung', ...}]
            pruefungsdatum: 'YYYY-MM-DD' String
            stunden_pro_tag: Lernstunden pro Tag (z.B. 3.0)

        Returns:
            {
              'pruefungsdatum': str,
              'stunden_pro_tag': float,
              'gesamt_lerntage': int,
              'tage': [{'datum', 'thema', 'fokus_punkt', 'schwierigkeit',
                        'lernzeit_stunden', 'ist_puffertag', 'tipps'}]
            }
        """
        heute      = date.today()
        pruefung   = date.fromisoformat(pruefungsdatum)

        if pruefung <= heute:
            raise ValueError("Prüfungsdatum muss in der Zukunft liegen.")

        # Verfügbare Tage berechnen
        verfuegbare_tage = (pruefung - heute).days  # exkl. Prüfungstag
        if verfuegbare_tage <= PUFFER_TAGE:
            raise ValueError(
                f"Zu wenig Zeit: nur {verfuegbare_tage} Tag(e) bis zur Prüfung. "
                f"Mindestens {PUFFER_TAGE + 1} Tage benötigt."
            )

        lerntage      = verfuegbare_tage - PUFFER_TAGE
        puffer_start  = pruefung - timedelta(days=PUFFER_TAGE)
        puffer_ende   = pruefung - timedelta(days=1)
        start_datum   = heute + timedelta(days=1)

        logger.info(
            f"[{self.name}] Plan: {lerntage} Lerntage + {PUFFER_TAGE} Puffertage | "
            f"{len(alle_themen)} Themen | {stunden_pro_tag}h/Tag"
        )

        # Themen deduplizieren und nach Schwierigkeit+Wichtigkeit sortieren
        unique_themen = self._deduplicate_themen(alle_themen)

        # Claude-Prompt aufbauen
        themen_liste = self._format_themen_fuer_prompt(unique_themen)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            pruefungsdatum   = pruefungsdatum,
            lerntage         = lerntage,
            start_datum      = start_datum.isoformat(),
            letzter_lerntag  = (puffer_start - timedelta(days=1)).isoformat(),
            stunden_pro_tag  = stunden_pro_tag,
            puffer_start     = puffer_start.isoformat(),
            puffer_ende      = puffer_ende.isoformat(),
            themen_liste     = themen_liste,
            anzahl_themen    = len(unique_themen),
        )

        # Claude anfragen
        try:
            response = self.client.messages.create(
                model      = MODEL,
                max_tokens = MAX_TOKENS,
                system     = SYSTEM_PROMPT,
                messages   = [{"role": "user", "content": user_prompt}],
            )
            # Token-Tracking für Billing
            if self._token_callback and hasattr(response, "usage"):
                self._token_callback(
                    "planner",
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
            raw = response.content[0].text.strip()
            tage = self._parse_plan(raw)
            logger.info(f"[{self.name}] ✅ Plan mit {len(tage)} Tagen erstellt")
        except Exception as e:
            logger.warning(f"[{self.name}] Claude-Fehler: {e} – verwende Fallback")
            tage = self._fallback_plan(
                unique_themen, start_datum, puffer_start, puffer_ende, stunden_pro_tag
            )

        # Puffertage und Prüfungstag ergänzen, falls Claude sie weggelassen hat
        tage = self._ensure_puffer_and_pruefung(
            tage, puffer_start, puffer_ende, pruefung, stunden_pro_tag
        )

        return {
            "pruefungsdatum"   : pruefungsdatum,
            "stunden_pro_tag"  : stunden_pro_tag,
            "gesamt_lerntage"  : lerntage,
            "gesamt_tage_plan" : len(tage),
            "tage"             : tage,
        }

    # ── Private Methoden ──────────────────────────────────────────────────────

    def _deduplicate_themen(self, themen: List[Dict]) -> List[Dict]:
        """Entfernt Duplikate (gleicher Titel) und sortiert: schwer+wichtig zuerst."""
        seen = set()
        unique = []
        for t in themen:
            key = t.get("titel", "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(t)
        # Sortierung: absteigende Schwierigkeit, dann absteigende Wichtigkeit
        return sorted(
            unique,
            key=lambda x: (x.get("schwierigkeit", 5), x.get("wichtigkeit", 3)),
            reverse=True,
        )

    def _format_themen_fuer_prompt(self, themen: List[Dict]) -> str:
        lines = []
        for i, t in enumerate(themen, 1):
            diff  = t.get("schwierigkeit", 5)
            wich  = t.get("wichtigkeit", 3)
            titel = t.get("titel", f"Thema {i}")
            kurz  = t.get("kurzfassung", "")
            lines.append(
                f"{i}. [{titel}] Schwierigkeit: {diff}/10 | Wichtigkeit: {wich}/5\n"
                f"   Inhalt: {kurz[:120]}"
            )
        return "\n".join(lines)

    def _parse_plan(self, raw: str) -> List[Dict]:
        """Parst Claude-Ausgabe als JSON."""
        # JSON aus Markdown-Blöcken extrahieren
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1).strip()

        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Antwort ist keine Liste")

        validated = []
        for entry in data:
            validated.append({
                "datum"           : entry.get("datum", ""),
                "thema"           : entry.get("thema", "–"),
                "fokus_punkt"     : entry.get("fokus_punkt", ""),
                "schwierigkeit"   : max(1, min(10, int(entry.get("schwierigkeit", 5)))),
                "lernzeit_stunden": float(entry.get("lernzeit_stunden", 2)),
                "ist_puffertag"   : bool(entry.get("ist_puffertag", False)),
                "tipps"           : entry.get("tipps", ""),
            })
        return validated

    def _fallback_plan(
        self,
        themen: List[Dict],
        start: date,
        puffer_start: date,
        puffer_ende: date,
        stunden: float,
    ) -> List[Dict]:
        """Einfache Gleichverteilung als Fallback wenn Claude fehlschlägt."""
        lerntage_count = (puffer_start - start).days
        tage = []
        current = start

        # Gewichtete Tagesverteilung
        gewichte = [max(1, t.get("schwierigkeit", 5) // 3) for t in themen]
        gesamt_gewicht = sum(gewichte)

        tag_idx = 0
        for i, thema in enumerate(themen):
            tage_fuer_thema = max(1, round(gewichte[i] / gesamt_gewicht * lerntage_count))
            for _ in range(tage_fuer_thema):
                if current >= puffer_start:
                    break
                tage.append({
                    "datum"           : current.isoformat(),
                    "thema"           : thema.get("titel", "–"),
                    "fokus_punkt"     : thema.get("kurzfassung", "")[:100],
                    "schwierigkeit"   : thema.get("schwierigkeit", 5),
                    "lernzeit_stunden": stunden,
                    "ist_puffertag"   : False,
                    "tipps"           : "",
                })
                current += timedelta(days=1)

        # Restliche Tage mit letztem Thema füllen
        while current < puffer_start:
            last = tage[-1].copy() if tage else {}
            last["datum"] = current.isoformat()
            tage.append(last)
            current += timedelta(days=1)

        return tage

    def _ensure_puffer_and_pruefung(
        self,
        tage: List[Dict],
        puffer_start: date,
        puffer_ende: date,
        pruefung: date,
        stunden: float,
    ) -> List[Dict]:
        """Stellt sicher, dass Puffertage und Prüfungstag korrekt im Plan sind."""
        existing_dates = {t["datum"] for t in tage}

        for puffer_date in [puffer_start, puffer_ende]:
            if puffer_date.isoformat() not in existing_dates:
                tage.append({
                    "datum"           : puffer_date.isoformat(),
                    "thema"           : "🔁 Wiederholung",
                    "fokus_punkt"     : "Alle schwierigen Themen nochmals durchgehen, Karteikarten wiederholen",
                    "schwierigkeit"   : 5,
                    "lernzeit_stunden": stunden,
                    "ist_puffertag"   : True,
                    "tipps"           : "Fokus auf Lücken, nicht auf bereits Bekanntes",
                })

        # Alle Puffertage korrekt markieren
        for tag in tage:
            tag_date = date.fromisoformat(tag["datum"]) if tag.get("datum") else None
            if tag_date in (puffer_start, puffer_ende):
                tag["ist_puffertag"] = True
                if "Wiederholung" not in tag["thema"]:
                    tag["thema"] = f"🔁 Wiederholung: {tag['thema']}"

        # Nach Datum sortieren
        tage.sort(key=lambda x: x.get("datum", ""))
        return tage
