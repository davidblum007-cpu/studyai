"""
StudyAI – Chat-Tutor Agent
Beantwortet Fragen basierend auf dem analysierten Lernmaterial einer Session.
Nutzt SSE-Streaming für Echtzeit-Antworten.
"""

import os
import logging
import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bist ein hilfreicher KI-Lernassistent (StudyAI-Tutor).
Du hilfst Studierenden dabei, ihr Lernmaterial zu verstehen.
Dir wurde das analysierte Lernmaterial einer Studierenden-Session zur Verfügung gestellt.

WICHTIGE REGELN:
- Beantworte Fragen ausschließlich auf Basis des bereitgestellten Lernmaterials
- Wenn eine Frage nicht durch das Material beantwortet werden kann, sage das klar
- Antworte auf Deutsch, außer die Nutzerin/der Nutzer schreibt in einer anderen Sprache
- Sei präzise, lehrreich und ermutigend
- Verwende Markdown-Formatierung für bessere Lesbarkeit (Fettschrift, Listen, Code-Blöcke)
- Verweise auf konkrete Themen oder Konzepte aus dem Material wenn möglich
- Erkläre komplexe Konzepte mit einfachen Worten und Beispielen
- Maximal 600 Wörter pro Antwort"""


class ChatAgent:
    """KI-Tutor der Fragen zum Lernmaterial via SSE-Streaming beantwortet."""

    MAX_HISTORY = 20      # Maximale Anzahl Nachrichten im Kontext (user+assistant je 1)
    MAX_CONTEXT_CHARS = 40_000  # Maximale Zeichen für den Materialkontext

    def __init__(self, token_callback=None):
        self.name = "ChatAgent"
        self._token_callback = token_callback
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY nicht gesetzt.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self._model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
        logger.info("[%s] initialisiert (Modell: %s)", self.name, self._model)

    # ── Kontext aus Session-Analyse aufbauen ──────────────────────────────────

    def _build_context(self, session_result: dict, flashcards: list) -> str:
        """Erstellt einen kompakten Lernmaterial-Kontext aus der Session-Analyse."""
        parts = []

        if not session_result:
            return "(Kein analysiertes Lernmaterial verfügbar)"

        # Metadaten
        meta = session_result.get("metadata", {})
        if meta.get("title"):
            parts.append(f"# Dokument: {meta['title']}")
        if meta.get("subject"):
            parts.append(f"Fachgebiet: {meta['subject']}")
        if meta.get("total_pages"):
            parts.append(f"Seiten: {meta['total_pages']}")

        # Gesamtzusammenfassung
        if session_result.get("overall_summary"):
            parts.append(f"\n## Gesamtzusammenfassung\n{session_result['overall_summary']}")

        # Haupt-Topics
        topics = session_result.get("topics", [])
        if topics:
            parts.append("\n## Themen und Konzepte")
            for topic in topics[:20]:  # Max 20 Topics
                topic_text = f"\n### {topic.get('title', 'Thema')}"
                if topic.get("summary"):
                    topic_text += f"\n{topic['summary']}"
                if topic.get("key_concepts"):
                    topic_text += f"\nKonzepte: {', '.join(topic['key_concepts'][:8])}"
                parts.append(topic_text)

        # Chunks (komprimiert)
        chunks = session_result.get("chunks", [])
        if chunks and len("".join(parts)) < self.MAX_CONTEXT_CHARS // 2:
            parts.append("\n## Detaillierter Inhalt")
            for chunk in chunks[:30]:  # Max 30 Chunks
                chunk_text = ""
                if chunk.get("themen"):
                    chunk_text += f"**Themen:** {', '.join(chunk['themen'][:5])}\n"
                if chunk.get("zusammenfassung"):
                    chunk_text += chunk["zusammenfassung"]
                if chunk_text:
                    parts.append(chunk_text)

        # Flashcards als Lernziele
        if flashcards:
            parts.append(f"\n## Lernkarten ({len(flashcards)} Stück)")
            for card in flashcards[:30]:  # Max 30 Karten
                front = card.get("front", "")
                back = card.get("back", "")
                if front and back:
                    parts.append(f"F: {front}\nA: {back}")

        context = "\n".join(parts)
        # Kürzen wenn zu lang – an Absatz- oder Satzgrenze, nicht mitten im Text
        if len(context) > self.MAX_CONTEXT_CHARS:
            original_len = len(context)
            truncated = context[:self.MAX_CONTEXT_CHARS]
            # Versuch 1: An letztem doppelten Zeilenumbruch (Absatzgrenze) trennen
            last_para = truncated.rfind("\n\n")
            # Versuch 2: An letztem einfachen Zeilenumbruch trennen
            last_line = truncated.rfind("\n")
            # Versuch 3: An letztem Satzende trennen (. ! ?)
            last_sent = max(
                truncated.rfind(". "),
                truncated.rfind("! "),
                truncated.rfind("? "),
            )
            # Beste Trennstelle wählen (mindestens 80% des Limits nutzen)
            min_pos = self.MAX_CONTEXT_CHARS * 8 // 10
            cut_pos = self.MAX_CONTEXT_CHARS  # Fallback: harte Grenze
            for pos in [last_para, last_line, last_sent]:
                if pos > min_pos:
                    cut_pos = pos
                    break
            context = context[:cut_pos] + "\n\n[...Material gekürzt...]"
            logger.warning(
                "[%s] Kontext gekürzt von %d auf %d Zeichen (Trennstelle: %d)",
                self.name, original_len, len(context), cut_pos
            )

        return context

    # ── Streaming Chat ────────────────────────────────────────────────────────

    def stream_response(self, question: str, history: list,
                        session_result: dict, flashcards: list):
        """
        Streamt eine Tutor-Antwort auf eine Nutzerfrage.

        Args:
            question:       Aktuelle Nutzerfrage
            history:        Liste von {"role": "user"|"assistant", "content": "..."}
            session_result: Analyseergebnis der Session (aus DB)
            flashcards:     Flashcards der Session (aus DB)

        Yields:
            str-Chunks der Antwort (via anthropic streaming)
        """
        context = self._build_context(session_result, flashcards)

        system = f"{SYSTEM_PROMPT}\n\n---\n\n## LERNMATERIAL DER SESSION:\n\n{context}"

        # Chat-History aufbauen (letzte MAX_HISTORY Nachrichten)
        messages = []
        recent = history[-(self.MAX_HISTORY):]
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # Aktuelle Frage anhängen
        messages.append({"role": "user", "content": question})

        logger.info("[%s] Streaming-Antwort für Frage: %s…", self.name, question[:60])

        input_tokens = 0
        output_tokens = 0

        with self.client.messages.stream(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text

            # Token-Tracking für Billing
            final_msg = stream.get_final_message()
            if final_msg and final_msg.usage:
                input_tokens  = final_msg.usage.input_tokens
                output_tokens = final_msg.usage.output_tokens

        if self._token_callback and (input_tokens or output_tokens):
            try:
                self._token_callback(input_tokens, output_tokens)
            except Exception:
                pass

        logger.info("[%s] Antwort fertig (%d in / %d out Tokens)",
                    self.name, input_tokens, output_tokens)
