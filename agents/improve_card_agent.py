"""
StudyAI – KI-Karten-Verbesserungs-Agent (Phase 6)
===================================================
Verbessert eine bestehende Flashcard via Claude:
  - Präzisiert Vorderseite (klarere Frage)
  - Erweitert Rückseite (vollständigere Antwort + Eselsbrücke)
  - Schlägt optionalen Tipp vor
Gibt immer strukturiertes JSON zurück – kein Streaming nötig.
"""

import os
import json
import logging
import anthropic

logger = logging.getLogger(__name__)

_api_key = os.getenv("ANTHROPIC_API_KEY", "")
_model   = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

IMPROVE_SYSTEM = """\
Du bist ein erfahrener Didaktik-Experte und verbesserst Lernkarteikarten (Flashcards).

REGELN:
1. Vorderseite: Eine klare, präzise Frage oder ein Begriff. Max. 200 Zeichen.
2. Rückseite: Vollständige, lernförderliche Antwort. Füge wenn sinnvoll hinzu:
   - Eselsbrücke oder Merkregel
   - Kontext oder Beispiel
   - Formel / Struktur (falls relevant)
   Max. 600 Zeichen.
3. Tipp (hint): Optionaler kurzer Denkanstoß. Max. 150 Zeichen. Leer lassen wenn nicht hilfreich.
4. Behalte den Kartentyp (type) und das Thema (topic) bei.
5. Antworte NUR mit validem JSON – kein Kommentar, kein Markdown.

JSON-Format:
{
  "front": "...",
  "back": "...",
  "hint": "...",
  "improvement_note": "Kurze Erklärung was verbessert wurde (max 100 Zeichen)"
}
"""


class ImproveCardAgent:
    """Verbessert eine Flashcard mit Claude. Gibt dict zurück."""

    def __init__(self, token_callback=None):
        self._client = anthropic.Anthropic(api_key=_api_key)
        self._token_callback = token_callback

    def improve(self, card: dict, context: str = "") -> dict:
        """
        Verbessert eine Flashcard.

        Args:
            card: Dict mit front, back, type, topic, hint (optional)
            context: Optionaler Lernmaterial-Kontext (z.B. Themen-Summary)

        Returns:
            Dict mit front, back, hint, improvement_note
            oder {"error": "..."} bei Fehler
        """
        front = str(card.get("front", "")).strip()[:500]
        back  = str(card.get("back",  "")).strip()[:2000]
        hint  = str(card.get("hint",  "")).strip()[:500]
        topic = str(card.get("topic", card.get("thema", ""))).strip()[:200]
        ctype = str(card.get("type",  "")).strip()[:100]

        if not front or not back:
            return {"error": "Karte hat keine Vorder- oder Rückseite"}

        user_msg = f"""Verbessere diese Flashcard:

**Vorderseite:** {front}
**Rückseite:** {back}
**Tipp:** {hint or '(keiner)'}
**Kartentyp:** {ctype or 'Allgemein'}
**Thema:** {topic or 'Unbekannt'}
"""
        if context:
            user_msg += f"\n**Lernmaterial-Kontext (kurz):**\n{context[:1500]}\n"

        try:
            response = self._client.messages.create(
                model=_model,
                max_tokens=512,
                system=IMPROVE_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
            if self._token_callback and hasattr(response, "usage"):
                self._token_callback(
                    "improve_card",
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )

            raw = response.content[0].text.strip()
            # JSON aus der Antwort extrahieren (falls Markdown-Wrapper)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            # Felder validieren
            for field in ("front", "back"):
                if field not in result or not result[field]:
                    return {"error": f"KI hat Feld '{field}' nicht zurückgegeben"}
            result.setdefault("hint", "")
            result.setdefault("improvement_note", "Karte wurde verbessert")
            return result

        except json.JSONDecodeError as e:
            logger.warning("[ImproveCard] JSON-Parse-Fehler: %s", e)
            return {"error": "KI-Antwort konnte nicht verarbeitet werden"}
        except Exception as e:
            logger.exception("[ImproveCard] Unerwarteter Fehler")
            return {"error": str(e)}
