#!/usr/bin/env bash
# ============================================================
# StudyAI – Entwickler-Setup
# Aktiviert den Pre-commit-Hook für Secret-Detection.
#
# Ausführung (einmalig nach git clone):
#   bash setup.sh
# ============================================================

set -euo pipefail

echo "=========================================="
echo " StudyAI Entwickler-Setup"
echo "=========================================="

# ── Pre-commit Hook aktivieren ────────────────────────────────────────────────
echo "Aktiviere Pre-commit-Hook..."
git config core.hooksPath .github/hooks
chmod +x .github/hooks/pre-commit 2>/dev/null || true
echo "  [OK] git config core.hooksPath = .github/hooks"

# ── Prüfen ob gitleaks installiert ist ────────────────────────────────────────
if command -v gitleaks &>/dev/null; then
    echo "  [OK] gitleaks gefunden: $(gitleaks version 2>/dev/null || echo 'installiert')"
else
    echo "  [WARN] gitleaks nicht gefunden."
    echo "         Installation: https://github.com/gitleaks/gitleaks#installing"
    echo "         macOS:   brew install gitleaks"
    echo "         Linux:   curl -sSfL https://raw.githubusercontent.com/gitleaks/gitleaks/main/scripts/install.sh | sh"
fi

# ── Python-Abhängigkeiten installieren ────────────────────────────────────────
echo ""
echo "Installiere Python-Abhängigkeiten..."
if command -v pip3 &>/dev/null; then
    pip3 install -r requirements.txt --quiet
    echo "  [OK] requirements.txt installiert"
elif command -v pip &>/dev/null; then
    pip install -r requirements.txt --quiet
    echo "  [OK] requirements.txt installiert"
else
    echo "  [WARN] pip nicht gefunden – bitte manuell ausführen: pip install -r requirements.txt"
fi

# ── .env aus .env.example anlegen ─────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "  [OK] .env aus .env.example erstellt."
    echo "  --> Bitte ANTHROPIC_API_KEY und FLASK_SECRET_KEY in .env eintragen!"
else
    echo "  [OK] .env existiert bereits"
fi

echo ""
echo "=========================================="
echo " Setup abgeschlossen!"
echo " Naechste Schritte:"
echo "   1. .env oeffnen und API-Keys eintragen"
echo "   2. python server.py"
echo "   3. http://localhost:5000 aufrufen"
echo "=========================================="
