"""
StudyAI – Flashcard Agent
=========================
Verantwortlich für:
- Generierung hochwertiger Anki-Flashcards pro Text-Chunk (Phase-1-Output)
- Drei Karten-Typen: Konzept, Formel, Ursache-Wirkung + Definition
- Claude claude-3-5-sonnet mit Anki-Prinzip-Prompt (1 Info pro Karte)
- JSON-Parsing, Validierung, Retry-Logik
- Batch-Verarbeitung aller Chunks ohne Doppelungen
"""

import os
import json
import re
import time
import logging
from typing import List, Dict

import anthropic
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096
MAX_RETRIES = 2

VALID_TYPES = {"Konzept", "Definition", "Formel", "Ursache-Wirkung", "Beispiel"}


def _backoff_delay(attempt: int, base: float = 3.0) -> float:
    """Exponential backoff: 3s, 6s, 12s, ..."""
    return base * (2 ** (attempt - 1))

# ── System-Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Du bist ein Lernexperte und erstellst präzise Flashcards nach dem Anki-Minimum-Information-Prinzip.

Eiserne Regeln:
- 1 Karte = 1 einzige Information (nie mehrere Fakten pro Karte)
- Fragen sind KONKRET und SPEZIFISCH (nie generisch wie "Was ist X?" ohne Kontext)
- Antworten sind KURZ: 1-2 Sätze oder eine Formel/Liste mit max. 4 Punkten
- Erstelle IMMER zwischen 15-25 Karten pro Abschnitt. Schöpfe alle Details aus!
- Jede Karte erhält zwingend ein Feld "tier" mit einem der Werte: "Beginner", "Intermediate", "Advanced"
- Wenn es sich anbietet (Abläufe, Ursache-Wirkung, Hierarchien), füge ein optionales Feld "diagram" hinzu, das einen gültigen Mermaid.js String (z.B. flowchart TD) enthält.
- Du antwortest AUSSCHLIEßLICH mit einem gültigen JSON-Array, ohne Kommentar"""

# ── Prompt-Template ───────────────────────────────────────────────────────────
USER_PROMPT_TEMPLATE = """Erstelle präzise Flashcards aus dem Text und dem Zusatzkontext.

WICHTIG – QUALITÄTSREGELN:
1. Jede Frage muss KONKRET sein: Nenne immer den Fachbegriff beim Namen.
2. Die Antwort erklärt nur EINE Sache.
3. Erstelle 15-25 Karten. Nutze den Originaltext sowie den Web-Zusatzkontext für Tiefe!
4. Unterteile die Karten in das Feld "tier":
   - "Beginner"     : Grundbegriffe und Definitionen
   - "Intermediate" : Zusammenhänge, Ursache-Wirkung, Formeln
   - "Advanced"     : Tiefe Details, Beispiele, Edge-Cases aus dem Zusatzkontext
5. Typen: "Definition", "Konzept", "Formel", "Ursache-Wirkung", "Beispiel"
6. Schwierigkeit 1-5 als separate Metrik.
7. Wenn eine Karte einen Ablauf, eine Struktur oder Ursache-Wirkung abbildet, füge zwingend ein Feld "diagram" mit syntaktisch korrektem Mermaid Code hinzu (ohne Markdown Codeblocks).

BEITE THEMEN AUS DIESEM ABSCHNITT (Chunk {chunk_id}, ca. {word_count} Wörter):
{themen}

ZUSAMMENFASSUNG:
{zusammenfassung}

VOLLSTÄNDIGER TEXTABSCHNITT:
---
{text}
---

WEB-ZUSATZKONTEXT (Aus dem Internet recherchiert zur Ergänzung):
---
{web_context}
---

ANTWORT (nur JSON-Array, kein anderer Text):
[
  {{
    "front": "Konkrete, präzise Frage mit Fachbegriff?",
    "back":  "Knappe, vollständige Antwort (1-2 Sätze)",
    "typ":   "Definition",
    "schwierigkeit": 1,
    "tier": "Beginner",
    "diagram": "flowchart TD\\n  A[Ursache] --> B[Wirkung]"
  }}
]"""


class FlashcardAgent:
    """
    Coworker-Agent: Anki-Flashcard-Generator.
    Verarbeitet Phase-1-Chunks und generiert strukturierte Lernkarten.
    """

    _search_cache: Dict[str, tuple] = {}  # key -> (result, timestamp)
    _SEARCH_CACHE_TTL = 3600  # 1 Stunde

    def __init__(self, token_callback=None):
        self.name = "FlashcardAgent"
        self._token_callback = token_callback  # Billing: Wird nach jedem API-Call aufgerufen
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key.startswith("sk-ant-DEIN"):
            raise EnvironmentError("ANTHROPIC_API_KEY nicht gesetzt.")
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"[{self.name}] initialisiert (Modell: {MODEL})")

    def generate_for_all_chunks(
        self,
        chunks: List[Dict],
        progress_callback=None,
    ) -> Dict:
        """
        Generiert Flashcards für alle Chunks aus Phase 1.

        Args:
            chunks: Liste der Chunks [{'chunk_id', 'text', 'word_count', 'themen'}]
            progress_callback: Funktion mit (current, total, message) → None

        Returns:
            {
              'total_cards': int,
              'cards': [{'id', 'front', 'back', 'typ', 'schwierigkeit', 'chunk_id'}],
              'by_type': {'Konzept': [...], ...},
              'by_chunk': {chunk_id: [...]}
            }
        """
        all_cards = []
        total = len(chunks)

        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback(i, total, f"Erstelle Karten für Abschnitt {i+1} von {total}…")

            cards = self.generate_for_chunk(chunk)
            # Jede Karte bekommt eine globale ID und chunk_id
            for j, card in enumerate(cards):
                card["id"]       = len(all_cards) + j + 1
                card["chunk_id"] = chunk.get("chunk_id", i + 1)
            all_cards.extend(cards)

        logger.info(f"[{self.name}] ✅ {len(all_cards)} Karten aus {total} Chunks generiert")

        # Nach Typ und Chunk gruppieren
        by_type  = {}
        by_chunk = {}
        for card in all_cards:
            typ = card.get("typ", "Konzept")
            cid = str(card.get("chunk_id", "?"))
            by_type.setdefault(typ, []).append(card)
            by_chunk.setdefault(cid, []).append(card)

        return {
            "total_cards" : len(all_cards),
            "cards"       : all_cards,
            "by_type"     : by_type,
            "by_chunk"    : by_chunk,
        }

    def generate_for_chunk(self, chunk: Dict) -> List[Dict]:
        """Generiert Flashcards für einen einzelnen Chunk."""
        chunk_id = chunk.get("chunk_id", "?")
        text     = chunk.get("text", "").strip()

        # Kein Text → sofort Fallback (keine API-Anfrage)
        if not text:
            logger.warning(f"[{self.name}] Chunk {chunk_id}: kein Text vorhanden, verwende Fallback")
            return self._fallback_cards(chunk)

        # Themensuche im Web via DuckDuckGo generieren
        web_context = ""
        try:
            # Durchsuche das wichtigste Thema aus diesem Chunk
            themen_list = chunk.get("themen", [])
            primary_theme = themen_list[0].get("titel") if themen_list else ""
            if primary_theme:
                search_query = f"{primary_theme} akademisch definition"

                # Cache-Check VOR dem API-Call (mit TTL)
                cached = FlashcardAgent._search_cache.get(search_query)
                if cached and (time.time() - cached[1]) < FlashcardAgent._SEARCH_CACHE_TTL:
                    web_context = cached[0]
                    logger.info(f"[{self.name}] Cache-Treffer für: '{search_query}'")
                else:
                    # DDG-Suche wie bisher
                    logger.info(f"[{self.name}] DDG Suche nach: '{search_query}'")
                    ddgs = DDGS()
                    results = ddgs.text(search_query, max_results=2)
                    web_context = "\n".join([r.get('body', '') for r in results])
                    # Nach erfolgreicher Suche speichern (mit Timestamp)
                    FlashcardAgent._search_cache[search_query] = (web_context, time.time())
                    # Cache-Größe begrenzen (max 100 Einträge)
                    if len(FlashcardAgent._search_cache) > 100:
                        oldest_key = min(
                            FlashcardAgent._search_cache,
                            key=lambda k: FlashcardAgent._search_cache[k][1],
                        )
                        del FlashcardAgent._search_cache[oldest_key]
        except Exception as e:
            logger.warning(f"[{self.name}] Web-Suchen-Fehler für Chunk {chunk_id}: {e}")
            web_context = "Kein Web-Kontext verfügbar."

        themen_str = ", ".join(
            t.get("titel", "") for t in chunk.get("themen", [])
        ) or "Allgemein"

        prompt = USER_PROMPT_TEMPLATE.format(
            chunk_id        = chunk_id,
            word_count      = chunk.get("word_count", 0),
            themen          = themen_str,
            zusammenfassung = chunk.get("gesamtzusammenfassung", "") or themen_str,
            text            = text[:6000],
            web_context     = web_context,
        )

        for attempt in range(1, MAX_RETRIES + 2):
            try:
                logger.debug(f"[{self.name}] Chunk {chunk_id}: API-Aufruf (Versuch {attempt}), Modell={MODEL}")
                resp = self.client.messages.create(
                    model      = MODEL,
                    max_tokens = MAX_TOKENS,
                    system     = SYSTEM_PROMPT,
                    messages   = [{"role": "user", "content": prompt}],
                )
                # Token-Tracking für Billing
                if self._token_callback and hasattr(resp, "usage"):
                    self._token_callback(
                        "flashcard",
                        resp.usage.input_tokens,
                        resp.usage.output_tokens,
                    )
                raw   = resp.content[0].text.strip()
                cards = self._parse_cards(raw)
                logger.debug(
                    f"[{self.name}] Chunk {chunk_id}: "
                    f"{len(cards)} Karten ({', '.join(set(c.get('typ','?') for c in cards))})"
                )
                return cards

            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[{self.name}] Parse-Fehler (Versuch {attempt}): {e}")
                if attempt <= MAX_RETRIES:
                    time.sleep(_backoff_delay(attempt))
                    continue
                return self._fallback_cards(chunk)

            except anthropic.RateLimitError:
                logger.warning(f"[{self.name}] Rate Limit – warte {_backoff_delay(attempt, base=10.0):.1f}s")
                time.sleep(_backoff_delay(attempt, base=10.0))
                if attempt > MAX_RETRIES:
                    return self._fallback_cards(chunk)

            except anthropic.APIError as e:
                logger.error(f"[{self.name}] API-Fehler (Versuch {attempt}): {type(e).__name__}: {e}")
                if attempt <= MAX_RETRIES:
                    time.sleep(_backoff_delay(attempt))
                    continue
                return self._fallback_cards(chunk)

            except Exception as e:
                # Catch-all: alle anderen Fehler (z.B. Netzwerk, Encoding)
                import traceback
                logger.error(
                    f"[{self.name}] Unerwarteter Fehler (Versuch {attempt}): "
                    f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                )
                if attempt <= MAX_RETRIES:
                    time.sleep(_backoff_delay(attempt))
                    continue
                return self._fallback_cards(chunk)

        return self._fallback_cards(chunk)

    # ── Private ───────────────────────────────────────────────────────────────

    def _parse_cards(self, raw: str) -> List[Dict]:
        """Parst Claude-Ausgabe als JSON-Array."""
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if match:
                raw = match.group(1).strip()

        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Antwort ist keine Liste")

        cards = []
        for item in data:
            front = str(item.get("front", "")).strip()
            back  = str(item.get("back", "")).strip()
            typ   = str(item.get("typ", "Konzept")).strip()
            diff  = max(1, min(5, int(item.get("schwierigkeit", 3))))
            tier  = str(item.get("tier", "Beginner")).strip()
            diagram = item.get("diagram", None)

            if not front or not back:
                continue
            if typ not in VALID_TYPES:
                typ = "Konzept"
            if tier not in {"Beginner", "Intermediate", "Advanced"}:
                tier = "Intermediate"

            card_dict = {
                "front"       : front,
                "back"        : back,
                "typ"         : typ,
                "schwierigkeit": diff,
                "tier"        : tier,
            }
            if diagram and isinstance(diagram, str) and len(diagram.strip()) > 0:
                card_dict["diagram"] = diagram.strip()
                
            cards.append(card_dict)
        return cards

    def _fallback_cards(self, chunk: Dict) -> List[Dict]:
        """
        Fallback wenn Claude-Generierung fehlschlägt.
        Erstellt sinnvolle Karten aus Theme-Titeln und Zusammenfassungen.
        Erzeugt KEINE generischen 'Was ist Abschnitt X?'-Fragen.
        """
        logger.warning(f"[{self.name}] Fallback für Chunk {chunk.get('chunk_id')}")
        themen = chunk.get("themen", [])
        cards  = []

        for t in themen[:5]:  # max 5 Fallback-Karten pro Chunk
            titel      = t.get("titel", "").strip()
            kurzfassung = t.get("kurzfassung", "").strip()
            wichtigkeit = t.get("wichtigkeit", 3)

            if not titel or not kurzfassung:
                continue  # Überspringe Themen ohne Inhalt

            cards.append({
                "front"        : f"Erkläre das Konzept: {titel}",
                "back"         : kurzfassung,
                "typ"          : "Definition",
                "schwierigkeit": max(1, min(5, wichtigkeit)),
                "tier"         : "Beginner"
            })

        # Wenn gar keine Themen vorhanden, überspringe den Chunk
        # (lieber keine Karte als eine sinnlose)
        return cards
