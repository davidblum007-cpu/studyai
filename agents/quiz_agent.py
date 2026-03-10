"""
StudyAI – Quiz Agent
====================
Generiert Multiple-Choice-Fragen aus bestehenden Flashcards.
Claude erstellt zu jeder Karte 3 plausible, aber falsche Distraktoren.
Batch-Verarbeitung: 5 Karten pro Claude-Call für Effizienz.
"""

import os
import json
import random
import logging
import time
from typing import List, Dict, Any

import anthropic

logger = logging.getLogger(__name__)

MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 2048
BATCH_SIZE = 5   # Karten pro Claude-Call
MAX_RETRIES = 2

SYSTEM_PROMPT = """Du bist ein Prüfer der Universitätsebene. Du erstellst Multiple-Choice-Fragen.

Deine Aufgabe: Für jede Karteikarte generiere 3 falsche, aber plausible Antwortoptionen (Distraktoren).
Die Distraktoren müssen:
- Zum Fachgebiet passen (nicht offensichtlich falsch)
- Ähnlich formuliert sein wie die richtige Antwort
- Prägnant sein (1-2 Sätze max)
- Klar falsch sein für jemanden der das Thema versteht

Antworte AUSSCHLIESSLICH mit validem JSON. Kein Markdown, keine Erklärungen."""


class QuizAgent:
    def __init__(self, token_callback=None):
        self.name = "QuizAgent"
        self._token_callback = token_callback  # Billing: Wird nach jedem API-Call aufgerufen
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key.startswith("sk-ant-DEIN"):
            raise EnvironmentError(
                "ANTHROPIC_API_KEY nicht gesetzt. Bitte .env.example → .env kopieren "
                "und den API Key eintragen."
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info("[%s] initialisiert", self.name)

    def generate_questions(self, cards: List[dict], num_questions: int = 20,
                           progress_callback=None) -> List[dict]:
        """
        Generiert MC-Fragen aus Flashcards.

        Args:
            cards: Liste von Flashcard-Dicts {id, front, back, typ, chunk_id, ...}
            num_questions: Maximale Anzahl Fragen (default 20)
            progress_callback: Optionale Funktion(current, total, message) für Fortschritts-Events

        Returns:
            Liste von {card_id, question, options, correct_index, typ, chunk_id}
        """
        if not cards:
            return []

        # Zufällige Auswahl falls mehr Karten als gewünscht
        pool = list(cards)
        random.shuffle(pool)
        selected = pool[:num_questions]

        # In Batches aufteilen
        batches = [selected[i:i+BATCH_SIZE] for i in range(0, len(selected), BATCH_SIZE)]

        all_questions = []
        for i, batch in enumerate(batches):
            logger.debug("[%s] Verarbeite Batch %d/%d (%d Karten)",
                        self.name, i+1, len(batches), len(batch))
            if progress_callback:
                progress_callback(i, len(batches),
                                  f"Generiere Fragen {i*BATCH_SIZE+1}–{min((i+1)*BATCH_SIZE, len(selected))} von {len(selected)}…")
            try:
                questions = self._generate_batch(batch)
                all_questions.extend(questions)
            except Exception as e:
                logger.error("[%s] Fehler in Batch %d: %s", self.name, i+1, e)
                # Fallback: Karten ohne Distraktoren überspringen
                continue

        return all_questions

    def _generate_batch(self, batch: List[dict]) -> List[dict]:
        """
        Sendet einen Batch an Claude und gibt MC-Fragen zurück.
        """
        # Karten für den Prompt aufbereiten
        cards_for_prompt = []
        for card in batch:
            cards_for_prompt.append({
                "card_id": str(card.get("id", "")),
                "frage": card.get("front", ""),
                "richtige_antwort": card.get("back", ""),
                "typ": card.get("typ", "Konzept"),
            })

        user_prompt = f"""Erstelle für jede dieser {len(batch)} Karteikarten genau 3 Distraktoren.

Karteikarten:
{json.dumps(cards_for_prompt, ensure_ascii=False, indent=2)}

Antworte mit einem JSON-Array. Jedes Objekt hat:
- "card_id": die card_id aus der Eingabe (String)
- "distraktoren": Array mit genau 3 Strings (falsche Antworten)

Beispiel-Format:
[
  {{
    "card_id": "42",
    "distraktoren": ["Falsche Antwort 1", "Falsche Antwort 2", "Falsche Antwort 3"]
  }}
]"""

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                # Token-Tracking für Billing
                if self._token_callback and hasattr(response, "usage"):
                    self._token_callback(
                        "quiz",
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                    )
                raw = response.content[0].text.strip()
                return self._parse_and_build(raw, batch)

            except anthropic.RateLimitError:
                wait = 15 * (attempt + 1)
                logger.warning("[%s] Rate Limit – warte %ds", self.name, wait)
                time.sleep(wait)
            except anthropic.APIError as e:
                if attempt < MAX_RETRIES:
                    time.sleep(5)
                else:
                    raise e

        raise RuntimeError("Maximale Versuche für Batch überschritten")

    def _parse_and_build(self, raw: str, batch: List[dict]) -> List[dict]:
        """
        Parst Claude-Antwort und baut vollständige MC-Fragen auf.
        """
        # JSON extrahieren (falls in Markdown-Blöcken)
        if "```" in raw:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            raw = raw[start:end] if start != -1 and end > 0 else raw

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("[%s] JSON-Parse-Fehler: %s | Raw: %s", self.name, e, raw[:200])
            return self._fallback_questions(batch)

        # Lookup-Map: card_id → distraktoren
        distractors_map: Dict[str, List[str]] = {}
        for item in parsed:
            cid = str(item.get("card_id", ""))
            dists = item.get("distraktoren", [])
            if cid and isinstance(dists, list) and len(dists) >= 3:
                distractors_map[cid] = [str(d) for d in dists[:3]]

        questions = []
        for card in batch:
            card_id = str(card.get("id", ""))
            dists = distractors_map.get(card_id)
            if not dists:
                logger.warning("[%s] Keine Distraktoren für Karte %s", self.name, card_id)
                dists = ["–", "–", "–"]  # Fallback

            correct_answer = card.get("back", "")

            # 4 Optionen zusammenstellen und mischen
            options = dists + [correct_answer]
            random.shuffle(options)
            correct_index = options.index(correct_answer)

            questions.append({
                "card_id":      card_id,
                "question":     card.get("front", ""),
                "options":      options,
                "correct_index": correct_index,
                "typ":          card.get("typ", "Konzept"),
                "chunk_id":     card.get("chunk_id"),
                "schwierigkeit": card.get("schwierigkeit", 3),
            })

        return questions

    def _fallback_questions(self, batch: List[dict]) -> List[dict]:
        """Fallback: Gibt Fragen ohne Distraktoren zurück (nur richtige Antwort)."""
        questions = []
        for card in batch:
            correct = card.get("back", "")
            options = [correct, "Keine der anderen Antworten", "Unbekannt", "Nicht zutreffend"]
            random.shuffle(options)
            questions.append({
                "card_id":       str(card.get("id", "")),
                "question":      card.get("front", ""),
                "options":       options,
                "correct_index": options.index(correct),
                "typ":           card.get("typ", "Konzept"),
                "chunk_id":      card.get("chunk_id"),
                "schwierigkeit": card.get("schwierigkeit", 3),
            })
        return questions
