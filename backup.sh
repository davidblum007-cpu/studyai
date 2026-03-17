#!/usr/bin/env bash
# ============================================================
# StudyAI – Datenbank-Backup-Skript
# Erstellt tägliche SQLite-Backups mit automatischer Rotation.
#
# Empfohlene Cron-Ausführung (täglich 03:00 Uhr):
#   0 3 * * * /app/backup.sh >> /var/log/studyai_backup.log 2>&1
#
# Umgebungsvariablen (optional, sonst Defaults):
#   STUDYAI_DB        – Pfad zur SQLite-Datenbank  (Default: /app/data/studyai.db)
#   BACKUP_DIR        – Zielordner für Backups      (Default: /app/data/backups)
#   BACKUP_KEEP_DAYS  – Aufbewahrungsdauer in Tagen (Default: 30)
#   ML_MODELS_DIR     – Pfad zu ML-Modellen         (Default: /app/ml_models)
# ============================================================

set -euo pipefail

# ── Konfiguration ─────────────────────────────────────────────────────────────
DB_PATH="${STUDYAI_DB:-/app/data/studyai.db}"
BACKUP_DIR="${BACKUP_DIR:-/app/data/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
ML_DIR="${ML_MODELS_DIR:-/app/ml_models}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_NAME="studyai_backup_${TIMESTAMP}"

# ── Farben für Logs ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err()  { echo -e "${RED}[ERR]${NC}  $*"; }

echo "========================================================"
echo " StudyAI Backup – $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"

# ── Backup-Verzeichnis anlegen ────────────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
mkdir -p "${BACKUP_PATH}"

# ── Schritt 1: SQLite-Backup (hot-copy via .backup) ──────────────────────────
if [ -f "${DB_PATH}" ]; then
    echo "Erstelle SQLite-Backup von: ${DB_PATH}"

    # sqlite3 .backup ist transaction-safe und funktioniert auch bei laufender DB
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "${DB_PATH}" ".backup '${BACKUP_PATH}/studyai.db'"
        log_ok "SQLite-Backup abgeschlossen: ${BACKUP_PATH}/studyai.db"
    else
        # Fallback: cp (weniger sicher bei aktiver Schreib-Last)
        log_warn "sqlite3 nicht gefunden – nutze cp als Fallback"
        cp "${DB_PATH}" "${BACKUP_PATH}/studyai.db"
        log_ok "SQLite cp-Backup: ${BACKUP_PATH}/studyai.db"
    fi

    # Dateigröße loggen
    DB_SIZE="$(du -sh "${BACKUP_PATH}/studyai.db" | cut -f1)"
    echo "  Backup-Größe: ${DB_SIZE}"
else
    log_warn "Datenbank nicht gefunden: ${DB_PATH} – kein DB-Backup"
fi

# ── Schritt 2: ML-Modelle sichern ─────────────────────────────────────────────
if [ -d "${ML_DIR}" ]; then
    ML_COUNT="$(find "${ML_DIR}" -name "sr_model_*.pkl" 2>/dev/null | wc -l)"
    if [ "${ML_COUNT}" -gt 0 ]; then
        cp -r "${ML_DIR}" "${BACKUP_PATH}/ml_models"
        log_ok "ML-Modelle gesichert: ${ML_COUNT} Modelle"
    else
        log_warn "Keine ML-Modelle in ${ML_DIR} gefunden"
    fi
else
    log_warn "ML-Modell-Verzeichnis nicht gefunden: ${ML_DIR}"
fi

# ── Schritt 3: Komprimieren ───────────────────────────────────────────────────
echo "Komprimiere Backup..."
ARCHIVE="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
tar -czf "${ARCHIVE}" -C "${BACKUP_DIR}" "${BACKUP_NAME}"
rm -rf "${BACKUP_PATH}"  # Temporäres Verzeichnis entfernen

ARCHIVE_SIZE="$(du -sh "${ARCHIVE}" | cut -f1)"
log_ok "Backup-Archiv: ${ARCHIVE} (${ARCHIVE_SIZE})"

# ── Schritt 4: Alte Backups rotieren ─────────────────────────────────────────
echo "Rotiere Backups älter als ${KEEP_DAYS} Tage..."
DELETED_COUNT=0
while IFS= read -r old_backup; do
    rm -f "${old_backup}"
    log_warn "Gelöscht (zu alt): $(basename "${old_backup}")"
    DELETED_COUNT=$((DELETED_COUNT + 1))
done < <(find "${BACKUP_DIR}" -name "studyai_backup_*.tar.gz" -mtime "+${KEEP_DAYS}" 2>/dev/null)

if [ "${DELETED_COUNT}" -eq 0 ]; then
    log_ok "Keine alten Backups zu rotieren"
else
    log_ok "${DELETED_COUNT} alte Backup(s) gelöscht"
fi

# ── Schritt 5: Backup-Inventar ────────────────────────────────────────────────
TOTAL_BACKUPS="$(find "${BACKUP_DIR}" -name "studyai_backup_*.tar.gz" 2>/dev/null | wc -l)"
TOTAL_SIZE="$(du -sh "${BACKUP_DIR}" 2>/dev/null | cut -f1)"
echo ""
echo "========================================================"
log_ok "Backup erfolgreich abgeschlossen"
echo "  Archiv:         ${ARCHIVE}"
echo "  Archiv-Größe:   ${ARCHIVE_SIZE}"
echo "  Gesamt-Backups: ${TOTAL_BACKUPS}"
echo "  Gesamt-Größe:   ${TOTAL_SIZE}"
echo "  Aufbewahrung:   ${KEEP_DAYS} Tage"
echo "========================================================"

exit 0
