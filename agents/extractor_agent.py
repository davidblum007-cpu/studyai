"""
StudyAI – Extractor Agent
=========================
Verantwortlich für:
- Text-Extraktion aus PDF-Binärdaten (via pdfplumber als Primär, PyPDF2 als Fallback)
- Bereinigung des Rohtexts (Bindestriche, Sonderzeichen, Seitenumbrüche)
- Aufteilung in ~2000-Wort-Chunks (auf Satzgrenzen)
"""

import io
import os
import re
import logging
from typing import List, Dict

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    from PyPDF2 import PdfReader
    _PYPDF2_AVAILABLE = True
except ImportError:
    _PYPDF2_AVAILABLE = False

logger = logging.getLogger(__name__)

CHUNK_SIZE_WORDS = int(os.getenv("CHUNK_SIZE_WORDS", 2000))
MIN_CHUNK_WORDS = 100  # Chunks kürzer als 100 Wörter werden ignoriert


class ExtractorAgent:
    """
    Coworker-Agent: PDF-Text-Extraktion & Chunking.
    """

    def __init__(self):
        self.name = "ExtractorAgent"
        logger.info(f"[{self.name}] initialisiert")

    def extract_and_chunk(self, file_bytes: bytes, filename: str) -> Dict:
        """
        Extrahiert Text aus PDF-Bytes und schneidet ihn in Chunks.

        Returns:
            {
                'filename': str,
                'total_pages': int,
                'total_words': int,
                'chunks': [{'chunk_id': int, 'text': str, 'word_count': int}]
            }
        """
        logger.info(f"[{self.name}] Starte Extraktion: '{filename}'")

        raw_text, total_pages = self._extract_text(file_bytes)

        if not raw_text.strip():
            raise ValueError(
                "Aus diesem PDF konnte kein Text extrahiert werden. "
                "Möglicherweise handelt es sich um ein gescanntes Dokument (Bild-PDF). "
                "Bitte verwende ein textbasiertes PDF."
            )

        cleaned = self._clean_text(raw_text)
        chunks = self._split_into_chunks(cleaned)

        total_words = sum(c["word_count"] for c in chunks)
        logger.info(
            f"[{self.name}] ✅ {total_pages} Seiten | {total_words:,} Wörter | "
            f"{len(chunks)} Chunks"
        )

        return {
            "filename": filename,
            "total_pages": total_pages,
            "total_words": total_words,
            "chunks": chunks,
        }

    # ── Private Methoden ─────────────────────────────────────────────────────

    def _extract_text(self, file_bytes: bytes) -> tuple[str, int]:
        """Probiert pdfplumber zuerst, fällt auf PyPDF2 zurück."""
        text, pages = self._try_pdfplumber(file_bytes)
        if not text.strip():
            logger.warning(f"[{self.name}] pdfplumber lieferte keinen Text – versuche PyPDF2")
            text, pages = self._try_pypdf2(file_bytes)
        return text, pages

    def _try_pdfplumber(self, file_bytes: bytes) -> tuple[str, int]:
        if not _PDFPLUMBER_AVAILABLE:
            return "", 0
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages = len(pdf.pages)
                texts = []
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    texts.append(f"[Seite {i+1}]\n{page_text}")
            return "\n\n".join(texts), pages
        except Exception as e:
            logger.warning(f"[{self.name}] pdfplumber Fehler: {e}")
            return "", 0

    def _try_pypdf2(self, file_bytes: bytes) -> tuple[str, int]:
        if not _PYPDF2_AVAILABLE:
            return "", 0
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            pages = len(reader.pages)
            texts = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                texts.append(f"[Seite {i+1}]\n{page_text}")
            return "\n\n".join(texts), pages
        except Exception as e:
            logger.error(f"[{self.name}] PyPDF2 Fehler: {e}")
            return "", 0

    def _clean_text(self, raw: str) -> str:
        """Bereinigt Rohtext für die Analyse."""
        # Silbentrennung am Zeilenende auflösen (z.B. "Vor-\nlesung" → "Vorlesung")
        text = re.sub(r"-\n(\w)", r"\1", raw)
        # Mehrfache Leerzeilen auf zwei reduzieren
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Sonstige Steuerzeichen entfernen (außer Newlines und Tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # Leerzeichen normalisieren
        text = re.sub(r" {2,}", " ", text)
        # [Seite X]-Marker entfernen (stören die KI-Analyse)
        text = re.sub(r"\[Seite \d+\]\n?", "", text)
        return text.strip()

    def _split_into_chunks(self, text: str) -> List[Dict]:
        """
        Schneidet Text in ~CHUNK_SIZE_WORDS-Wort-Chunks.
        Schneidet bevorzugt an Satzgrenzen (. ! ?).
        """
        # Text in Sätze aufteilen (grob)
        sentences = re.split(r"(?<=[.!?])\s+", text)

        chunks = []
        current_words = []
        current_count = 0
        chunk_id = 1

        for sentence in sentences:
            words = sentence.split()
            word_count = len(words)

            if current_count + word_count > CHUNK_SIZE_WORDS and current_count >= MIN_CHUNK_WORDS:
                # Aktuellen Chunk abschließen
                chunk_text = " ".join(current_words).strip()
                if chunk_text:
                    chunks.append({
                        "chunk_id": chunk_id,
                        "text": chunk_text,
                        "word_count": current_count,
                    })
                    chunk_id += 1
                current_words = words
                current_count = word_count
            else:
                current_words.extend(words)
                current_count += word_count

        # Letzten Chunk hinzufügen
        if current_words and current_count >= MIN_CHUNK_WORDS:
            chunk_text = " ".join(current_words).strip()
            chunks.append({
                "chunk_id": chunk_id,
                "text": chunk_text,
                "word_count": current_count,
            })

        logger.debug(f"[{self.name}] {len(chunks)} Chunks erstellt")
        return chunks
