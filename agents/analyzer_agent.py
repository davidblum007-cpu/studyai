"""
StudyAI – Analyzer Agent
========================
Verantwortlich für:
- Kommunikation mit der Claude claude-3-5-sonnet API
- Strukturiertes Prompt-Engineering (KI-Professor-Persona)
- JSON-Parsing und Validierung der Claude-Antwort
- Fehlerbehandlung (Retry, Fallback)
"""

import os
import json
import time
import logging
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 2048
MAX_RETRIES = 2


def _backoff_delay(attempt: int, base: float = 5.0) -> float:
    """Exponential backoff: 5s, 10s, 20s, ..."""
    return base * (2 ** (attempt - 1))

# ── System-Prompt (KI-Professor) ─────────────────────────────────────────────
SYSTEM_PROMPT = """Du bist ein erfahrener KI-Professor mit umfassendem Wissen in 
Natur-, Geistes- und Ingenieurwissenschaften. Deine Aufgabe ist es, Textauszüge 
aus Vorlesungsskripten präzise, tiefgründig und didaktisch wertvoll zu analysieren.

Du antwortest IMMER und AUSSCHLIESSLICH mit gültigem JSON. Kein Fließtext, keine 
Erklärungen außerhalb des JSON-Formats."""

# ── User-Prompt-Template ─────────────────────────────────────────────────────
USER_PROMPT_TEMPLATE = """Analysiere den folgenden Textauszug aus einem Vorlesungsskript.

AUFGABE:
1. Identifiziere die 3 wichtigsten Fachbegriffe/Konzepte.
2. Bewerte die Schwierigkeit des Textes (1 = sehr einfach, 10 = Expertenniveau).
3. Erstelle eine präzise 2-Satz-Zusammenfassung des Abschnitts.
4. Gib für jedes Thema eine Wichtigkeit (1 = Randthema, 5 = absolut prüfungsrelevant) an.

TEXTAUSZUG (Chunk {chunk_id} von {total_chunks}, {word_count} Wörter):
---
{text}
---

ANTWORT (nur gültiges JSON, kein anderer Text):
{{
  "chunk_id": {chunk_id},
  "schwierigkeit": <Zahl 1-10>,
  "gesamtzusammenfassung": "<2 Sätze, die den Kerninhalt zusammenfassen>",
  "themen": [
    {{
      "titel": "<Fachbegriff oder Konzeptname>",
      "wichtigkeit": <Zahl 1-5>,
      "kurzfassung": "<1-2 Sätze Erklärung>",
      "schluesselwoerter": ["<Begriff1>", "<Begriff2>", "<Begriff3>"]
    }}
  ]
}}"""


class AnalyzerAgent:
    """
    Coworker-Agent: Claude claude-3-5-sonnet Analyse-Engine.
    Analysiert einzelne Chunks und gibt strukturierte Daten zurück.
    """

    def __init__(self, token_callback=None):
        self.name = "AnalyzerAgent"
        self._token_callback = token_callback  # Billing: Wird nach jedem API-Call aufgerufen
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key.startswith("sk-ant-DEIN"):
            raise EnvironmentError(
                "ANTHROPIC_API_KEY nicht gesetzt. Bitte .env.example → .env kopieren "
                "und den API Key eintragen."
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"[{self.name}] initialisiert (Modell: {MODEL})")

    def analyze_chunk(self, chunk: dict, total_chunks: int) -> dict:
        """
        Analysiert einen einzelnen Text-Chunk mit Claude.

        Args:
            chunk: {'chunk_id': int, 'text': str, 'word_count': int}
            total_chunks: Gesamtanzahl der Chunks (für Kontext im Prompt)

        Returns:
            Analysieergebnis als dict (validiertes JSON)
        """
        logger.info(
            f"[{self.name}] Analysiere Chunk {chunk['chunk_id']}/{total_chunks} "
            f"({chunk['word_count']} Wörter)"
        )

        user_prompt = USER_PROMPT_TEMPLATE.format(
            chunk_id=chunk["chunk_id"],
            total_chunks=total_chunks,
            word_count=chunk["word_count"],
            text=chunk["text"][:6000],  # Sicherheitslimit auf ~6000 Zeichen
        )

        for attempt in range(1, MAX_RETRIES + 2):
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
                        "analyzer",
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                    )
                raw_text = response.content[0].text.strip()
                result = self._parse_and_validate(raw_text, chunk["chunk_id"])
                logger.info(
                    f"[{self.name}] ✅ Chunk {chunk['chunk_id']} analysiert: "
                    f"{len(result.get('themen', []))} Themen, "
                    f"Schwierigkeit={result.get('schwierigkeit')}"
                )
                return result

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"[{self.name}] Parse-Fehler (Versuch {attempt}): {e}")
                if attempt <= MAX_RETRIES:
                    time.sleep(_backoff_delay(attempt))
                    continue
                return self._fallback_result(chunk)

            except anthropic.RateLimitError:
                logger.warning(f"[{self.name}] Rate Limit – warte exponentiell")
                time.sleep(_backoff_delay(attempt, base=10.0))
                if attempt > MAX_RETRIES:
                    return self._fallback_result(chunk)

            except anthropic.APIError as e:
                logger.error(f"[{self.name}] API-Fehler: {e}")
                return self._fallback_result(chunk)

        return self._fallback_result(chunk)

    # ── Private Methoden ─────────────────────────────────────────────────────

    def _parse_and_validate(self, raw: str, chunk_id: int) -> dict:
        """Parst JSON-Antwort von Claude und validiert die Struktur."""
        # JSON aus Markdown-Codeblöcken extrahieren, falls vorhanden
        if "```" in raw:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1).strip()

        data = json.loads(raw)

        # Pflichtfelder prüfen
        required = ["themen", "schwierigkeit", "gesamtzusammenfassung"]
        for field in required:
            if field not in data:
                raise ValueError(f"Fehlendes Pflichtfeld: '{field}'")

        # Schwierigkeit normalisieren
        data["schwierigkeit"] = max(1, min(10, int(data["schwierigkeit"])))
        data["chunk_id"] = chunk_id

        # Themen validieren
        for thema in data.get("themen", []):
            thema["wichtigkeit"] = max(1, min(5, int(thema.get("wichtigkeit", 3))))

        return data

    def _fallback_result(self, chunk: dict) -> dict:
        """Notfall-Rückgabe wenn Analyse fehlschlägt."""
        logger.warning(f"[{self.name}] Verwende Fallback für Chunk {chunk['chunk_id']}")
        return {
            "chunk_id": chunk["chunk_id"],
            "schwierigkeit": 5,
            "gesamtzusammenfassung": "Analyse konnte für diesen Abschnitt nicht abgeschlossen werden.",
            "themen": [
                {
                    "titel": f"Abschnitt {chunk['chunk_id']}",
                    "wichtigkeit": 3,
                    "kurzfassung": "Inhalt konnte nicht analysiert werden.",
                    "schluesselwoerter": [],
                }
            ],
            "fehler": True,
        }
