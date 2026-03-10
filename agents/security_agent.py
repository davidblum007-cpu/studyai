"""
StudyAI – Security Agent
========================
Verantwortlich für:
- Validierung des Datei-Uploads (Typ, Größe, Seitenzahl)
- Schutz vor Path-Traversal-Angriffen
- Rate-Limiting-Prüfung
- PDF-Strukturprüfung auf Anomalien
"""

import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Konfiguration ────────────────────────────────────────────────────────────
MAX_PDF_SIZE_BYTES = int(os.getenv("MAX_PDF_SIZE_MB", 20)) * 1024 * 1024
MAX_PAGES = int(os.getenv("MAX_PAGES", 200))
ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_MIME_TYPES = {"application/pdf", "application/x-pdf"}

# Bekannte PDF-Magic-Bytes (Header)
PDF_MAGIC = b"%PDF-"


class SecurityError(Exception):
    """Wird ausgelöst, wenn eine Sicherheitsprüfung fehlschlägt."""
    pass


class SecurityAgent:
    """
    Coworker-Agent: Sicherheits- & Validierungsschicht.
    Muss IMMER als erster Agent im Pipeline aufgerufen werden.
    """

    def __init__(self):
        self.name = "SecurityAgent"
        logger.info(f"[{self.name}] initialisiert")

    def validate_upload(self, file_storage, filename: str) -> dict:
        """
        Führt alle Sicherheitsprüfungen für einen Upload durch.

        Args:
            file_storage: Werkzeug FileStorage-Objekt
            filename: Original-Dateiname des Uploads

        Returns:
            dict mit {'valid': True, 'sanitized_filename': str, 'file_bytes': bytes}

        Raises:
            SecurityError bei jeder Verletzung
        """
        logger.info(f"[{self.name}] Prüfe Upload: '{filename}'")

        # 1. Dateiname bereinigen (Path-Traversal-Schutz)
        sanitized = self._sanitize_filename(filename)

        # 2. Dateiendung prüfen
        self._check_extension(sanitized)

        # 3. Datei lesen & Größe prüfen
        file_bytes = file_storage.read()
        self._check_file_size(file_bytes)

        # 4. Magic-Bytes prüfen (wirklich ein PDF?)
        self._check_pdf_magic(file_bytes)

        # 5. Auf eingebettete Scripts prüfen (JavaScript in PDF)
        self._check_for_scripts(file_bytes)

        logger.info(f"[{self.name}] ✅ Upload validiert: '{sanitized}' ({len(file_bytes):,} Bytes)")
        return {
            "valid": True,
            "sanitized_filename": sanitized,
            "file_bytes": file_bytes,
        }

    def validate_page_count(self, num_pages: int):
        """Prüft ob die Seitenanzahl im erlaubten Bereich liegt."""
        if num_pages > MAX_PAGES:
            raise SecurityError(
                f"PDF hat {num_pages} Seiten – Maximum ist {MAX_PAGES}. "
                "Bitte teile das Dokument auf."
            )
        logger.info(f"[{self.name}] Seitenzahl OK: {num_pages} Seiten")

    def validate_review_logs(self, logs: list) -> list:
        """
        Validiert die ML-Review-Logs auf Struktur und Typsicherheit, 
        um Injection/Abstürze in scikit-learn zu verhindern.
        """
        if not isinstance(logs, list):
            raise SecurityError("Review-Logs müssen eine Liste sein.")
        
        if len(logs) > 10000:
            raise SecurityError("Zu viele Logs auf einmal (Max 10000).")

        validated = []
        for log in logs:
            if not isinstance(log, dict):
                continue
            
            try:
                # Nur numerische Felder durchlassen, Strings zu floats casten wo nötig
                valid_log = {
                    "rating": int(log.get("rating", 0)),
                    "repetitions": float(log.get("repetitions", 0)),
                    "interval": float(log.get("interval", 0)),
                    "last_rating": float(log.get("last_rating", 0)),
                }
                
                # Rating Checks
                if valid_log["rating"] not in [0, 1, 2, 3]:
                    continue
                    
                validated.append(valid_log)
            except (ValueError, TypeError):
                continue # Fehlerhafte Logs einfach ignorieren

        logger.info(f"[{self.name}] {len(validated)} von {len(logs)} Review-Logs validiert.")
        return validated

    # ── Private Hilfsmethoden ────────────────────────────────────────────────

    def _sanitize_filename(self, filename: str) -> str:
        """Entfernt gefährliche Zeichen und verhindert Path-Traversal."""
        # Nur Dateiname, kein Pfad
        name = Path(filename).name
        # Erlaubte Zeichen: Buchstaben, Ziffern, Bindestrich, Unterstrich, Punkt
        name = re.sub(r"[^\w\-_\.]", "_", name)
        # Mehrfache Punkte (z.B. für doppelte Endungen) reduzieren
        name = re.sub(r"\.{2,}", ".", name)
        if not name or name.startswith("."):
            name = "upload.pdf"
        return name

    def _check_extension(self, filename: str):
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise SecurityError(
                f"Dateityp '{ext}' nicht erlaubt. Nur PDF-Dateien werden akzeptiert."
            )

    def _check_file_size(self, file_bytes: bytes):
        size = len(file_bytes)
        if size == 0:
            raise SecurityError("Die hochgeladene Datei ist leer.")
        if size > MAX_PDF_SIZE_BYTES:
            size_mb = size / (1024 * 1024)
            max_mb = MAX_PDF_SIZE_BYTES / (1024 * 1024)
            raise SecurityError(
                f"Datei zu groß: {size_mb:.1f} MB (Maximum: {max_mb:.0f} MB)."
            )

    def _check_pdf_magic(self, file_bytes: bytes):
        if not file_bytes.startswith(PDF_MAGIC):
            raise SecurityError(
                "Die Datei ist kein gültiges PDF (fehlende PDF-Signatur)."
            )

    def _check_for_scripts(self, file_bytes: bytes):
        """Warnt vor eingebettetem JavaScript in PDFs (potentiell gefährlich)."""
        # Grobe Prüfung auf JS-Keywords im PDF-Stream
        suspicious_patterns = [b"/JavaScript", b"/JS", b"/AA", b"/OpenAction"]
        found = [p for p in suspicious_patterns if p in file_bytes]
        if found:
            logger.warning(
                f"[{self.name}] ⚠️  PDF enthält möglicherweise aktive Inhalte: "
                f"{[p.decode() for p in found]}. Analyse wird fortgesetzt."
            )
            # Keine Exception – nur Warnung, da legitime PDFs diese Tags haben können
