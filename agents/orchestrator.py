"""
StudyAI – Orchestrator Agent
============================
Koordiniert alle Coworker-Agents in der richtigen Reihenfolge:
  SecurityAgent → ExtractorAgent → AnalyzerAgent

Gibt Fortschrittsupdates per Callback zurück (für SSE-Streaming).
"""

import logging
import os
import threading
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Maximale parallele Chunk-Analyse-Worker (via Env konfigurierbar)
_MAX_WORKERS = int(os.getenv("ORCHESTRATOR_MAX_WORKERS", "4"))

from agents.security_agent import SecurityAgent, SecurityError
from agents.extractor_agent import ExtractorAgent
from agents.analyzer_agent import AnalyzerAgent

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    """
    Haupt-Koordinator: steuert SecurityAgent, ExtractorAgent und AnalyzerAgent.
    """

    def __init__(self):
        self.name = "OrchestratorAgent"
        self.security = SecurityAgent()
        self.extractor = ExtractorAgent()
        # AnalyzerAgent wird lazy initialisiert (API Key Check)
        self._analyzer: Optional[AnalyzerAgent] = None
        logger.info(f"[{self.name}] initialisiert – alle Agents bereit")

    @property
    def analyzer(self) -> AnalyzerAgent:
        if self._analyzer is None:
            self._analyzer = AnalyzerAgent()
        return self._analyzer

    def run(
        self,
        file_storage,
        filename: str,
        progress_callback: Optional[Callable[[dict], None]] = None,
        token_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> dict:
        """
        Führt die komplette Analyse-Pipeline aus.

        Args:
            file_storage: Werkzeug FileStorage aus dem Flask-Upload
            filename: Original-Dateiname
            progress_callback: Funktion die bei jedem Fortschritt aufgerufen wird
                               mit {'step': str, 'progress': 0.0-1.0, 'message': str}

        Returns:
            Vollständiges Analyseergebnis
        """
        def notify(step: str, progress: float, message: str):
            logger.info(f"[{self.name}] [{step}] {progress:.0%} – {message}")
            if progress_callback:
                progress_callback({"step": step, "progress": progress, "message": message})

        # ── Schritt 1: Sicherheitsprüfung ────────────────────────────────────
        notify("security", 0.05, "Sicherheitsprüfung läuft…")
        try:
            validated = self.security.validate_upload(file_storage, filename)
        except SecurityError as e:
            raise RuntimeError(f"Sicherheitsfehler: {e}") from e

        # ── Schritt 2: Text-Extraktion & Chunking ────────────────────────────
        notify("extraction", 0.10, "Extrahiere Text aus PDF…")
        extraction = self.extractor.extract_and_chunk(
            validated["file_bytes"],
            validated["sanitized_filename"],
        )

        # Seitenanzahl nachträglich prüfen
        self.security.validate_page_count(extraction["total_pages"])

        chunks = extraction["chunks"]
        total_chunks = len(chunks)

        if total_chunks == 0:
            raise RuntimeError(
                "Das PDF enthält keinen extrahierbaren Text. "
                "Bitte überprüfe, ob es sich um ein textbasiertes PDF handelt."
            )

        notify(
            "extraction",
            0.20,
            f"✅ {extraction['total_pages']} Seiten | "
            f"{extraction['total_words']:,} Wörter | "
            f"{total_chunks} Chunks erstellt",
        )

        # ── Schritt 3: Claude-Analyse (parallelisiert mit ThreadPoolExecutor) ────
        # Falls Token-Callback vorhanden, neuen Analyzer mit Callback erstellen
        active_analyzer = (
            AnalyzerAgent(token_callback=token_callback)
            if token_callback is not None
            else self.analyzer
        )
        analyses = [None] * total_chunks
        lock = threading.Lock()
        done_count = [0]  # Liste als Mutable-Trick für Closure
        max_workers = min(_MAX_WORKERS, total_chunks)

        def analyze_chunk_task(chunk_data):
            chunk, index = chunk_data
            return index, active_analyzer.analyze_chunk(chunk, total_chunks)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(analyze_chunk_task, (chunk, i)): i
                for i, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    index, result = future.result(timeout=120)
                    analyses[index] = result
                except Exception as e:
                    logger.error(f"[{self.name}] Fehler bei Chunk {idx + 1}: {e}")
                    analyses[idx] = active_analyzer._fallback_result(chunks[idx])

                with lock:
                    done_count[0] += 1
                    current_done = done_count[0]

                progress = 0.20 + (0.70 * (current_done / total_chunks))
                notify(
                    "analysis",
                    progress,
                    f"Analysiert: {current_done} von {total_chunks} Abschnitten…",
                )

        # Sicherheitsnetz: Falls ein Slot noch None ist → Fallback
        analyses = [
            a if a is not None else self.analyzer._fallback_result(chunks[i])
            for i, a in enumerate(analyses)
        ]

        # ── Schritt 4: Ergebnisse zusammenführen ─────────────────────────────
        notify("finalizing", 0.95, "Ergebnisse werden zusammengestellt…")
        final_result = self._merge_results(extraction, analyses)

        notify("done", 1.0, f"✅ Analyse abgeschlossen – {total_chunks} Abschnitte analysiert")
        return final_result

    def _merge_results(self, extraction: dict, analyses: list) -> dict:
        """Kombiniert Extraktions-Metadata mit allen Analyse-Ergebnissen."""
        # Durchschnittliche Schwierigkeit berechnen
        difficulties = [a.get("schwierigkeit", 5) for a in analyses]
        avg_difficulty = round(sum(difficulties) / len(difficulties), 1) if difficulties else 5

        # Alle Themen über alle Chunks sammeln
        all_themes = []
        for analysis in analyses:
            for theme in analysis.get("themen", []):
                all_themes.append({**theme, "chunk_id": analysis["chunk_id"]})

        # Index: chunk_id → original text (für FlashcardAgent)
        text_by_id = {
            c["chunk_id"]: {"text": c["text"], "word_count": c["word_count"]}
            for c in extraction["chunks"]
        }

        return {
            "metadata": {
                "filename"     : extraction["filename"],
                "total_pages"  : extraction["total_pages"],
                "total_words"  : extraction["total_words"],
                "total_chunks" : len(analyses),
                "avg_difficulty": avg_difficulty,
            },
            "chunks": [
                {
                    "chunk_id"           : analysis["chunk_id"],
                    # Text muss für Phase 3 (FlashcardAgent) enthalten sein
                    "text"               : text_by_id.get(analysis["chunk_id"], {}).get("text", ""),
                    "word_count"         : text_by_id.get(analysis["chunk_id"], {}).get("word_count", 0),
                    "schwierigkeit"      : analysis.get("schwierigkeit"),
                    "gesamtzusammenfassung": analysis.get("gesamtzusammenfassung"),
                    "themen"             : analysis.get("themen", []),
                    "fehler"             : analysis.get("fehler", False),
                }
                for analysis in analyses
            ],
            "alle_themen": all_themes,
        }

    @staticmethod
    def merge_results(results: list) -> dict:
        """
        Führt mehrere Analyse-Ergebnisse (von mehreren PDFs) zu einem zusammen.
        Chunks werden neu indexiert, source_file wird hinzugefügt.
        """
        if not results:
            return {}
        if len(results) == 1:
            return results[0]

        merged_chunks = []
        merged_themen = []
        total_pages   = 0
        total_words   = 0
        difficulty_sum = 0.0
        difficulty_count = 0
        chunk_counter = 1

        for result in results:
            filename = result.get("metadata", {}).get("filename", "Unbekannt")
            total_pages += result.get("metadata", {}).get("total_pages", 0)
            total_words += result.get("metadata", {}).get("total_words", 0)

            for chunk in result.get("chunks", []):
                chunk = dict(chunk)
                chunk["source_file"] = filename
                chunk["chunk_id"]    = chunk_counter
                chunk_counter += 1

                # Themen mit neuer chunk_id aktualisieren
                for thema in chunk.get("themen", []):
                    thema = dict(thema)
                    thema["chunk_id"] = chunk["chunk_id"]
                    merged_themen.append(thema)

                merged_chunks.append(chunk)

            avg = result.get("metadata", {}).get("avg_difficulty", 5.0)
            count = result.get("metadata", {}).get("total_chunks", 0)
            difficulty_sum   += avg * count
            difficulty_count += count

        avg_difficulty = round(difficulty_sum / difficulty_count, 1) if difficulty_count else 5.0
        filenames = [r.get("metadata", {}).get("filename", "?") for r in results]
        combined_name = filenames[0] if len(filenames) == 1 else f"{filenames[0]} & {len(filenames)-1} weitere"

        return {
            "metadata": {
                "filename":      combined_name,
                "filenames":     filenames,
                "total_pages":   total_pages,
                "total_words":   total_words,
                "total_chunks":  len(merged_chunks),
                "avg_difficulty": avg_difficulty,
            },
            "chunks":     merged_chunks,
            "alle_themen": merged_themen,
        }
