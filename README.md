# StudyAI – Intelligente Skript-Analyse

KI-gestützter Lernassistent für Vorlesungsskripte. Lade ein PDF hoch und erhalte sofort Fachbegriffe, Schwierigkeitsbewertungen, Zusammenfassungen, Flashcards, einen Lernplan und ein Spaced-Repetition-System.

---

## Features

| Phase | Funktion |
|-------|----------|
| 1 – Analyse | PDF-Upload (einzeln oder mehrere), KI-Analyse via Claude, Chunk-Karten mit Themen, Schwierigkeit, Schlüsselwörtern |
| 2 – Lernplan | KI-generierter Kalender mit Puffertagen vor der Prüfung |
| 3 – Flashcards | Automatisch generierte Anki-Karten · Typ-/Level-Filter · **Volltextsuche** · Anki-Export (.apkg) |
| 4 – Spaced Repetition | SM-2-Algorithmus mit ML-Optimierung · Streak-Tracking · **Schwächen-Dashboard** |
| 5 – Quiz | Multiple-Choice mit Claude-generierten Distraktoren · Echtzeit-Fortschritt · Fehlerwiederholung |

**Weitere Features:**
- Persistente Sessions (SQLite) mit optionalem Cloud-Sync (Firebase Firestore)
- Session-Export/-Import als JSON · Session umbenennen
- Keyboard-Shortcuts (1–4, Leertaste, Enter, `?` für Hilfe)
- SecurityManager-Middleware mit HTTP-Audit-Log
- Mobile-optimiertes Layout

---

## Technologie-Stack

- **Backend:** Python 3.11+ · Flask 3.1 · SQLite · Firebase Admin SDK
- **KI:** Anthropic Claude API (`claude-sonnet-4-6`)
- **ML:** scikit-learn (Spaced-Repetition-Optimierung)
- **Frontend:** Vanilla JS (ES2022) · CSS Custom Properties · SSE-Streaming
- **PDF:** pdfplumber · PyPDF2
- **Anki:** genanki

---

## Schnellstart

### Voraussetzungen
- Python 3.11+
- Anthropic API Key: https://console.anthropic.com

### Installation

```bash
# 1. Abhängigkeiten installieren
pip install -r requirements.txt

# 2. Umgebungsvariablen konfigurieren
cp .env.example .env
# .env öffnen und ANTHROPIC_API_KEY eintragen

# 3. Server starten
python server.py
```

Öffne http://localhost:5000 im Browser.

### Firebase einrichten (optional – Cloud-Sync)

```bash
# 1. Firebase-Projekt erstellen: https://console.firebase.google.com
# 2. Firestore in Native Modus aktivieren
# 3. Project Settings → Service Accounts → "Neuen privaten Schlüssel generieren"
# 4. Heruntergeladene JSON-Datei mit dem Setup-Script einrichten:
python firebase_setup.py /pfad/zur/serviceAccountKey.json

# 5. Server neu starten
python server.py
```

---

## Projektstruktur

```
StudyAI/
├── server.py                 # Flask API Server (alle Endpoints)
├── database.py               # SQLite-Persistenz
├── firebase_sync.py          # Firebase Firestore Sync (optional)
├── firebase_setup.py         # Firebase-Einrichtungs-Script
├── index.html                # Single-Page-App
├── app.js                    # Frontend-Logik (~2500 Zeilen)
├── styles.css                # Dark-Mode CSS (~3400 Zeilen)
├── requirements.txt
├── .env.example
└── agents/
    ├── orchestrator.py       # Multi-PDF-Koordination
    ├── security_agent.py     # Input-Validierung & Sicherheit
    ├── extractor_agent.py    # PDF-Text-Extraktion
    ├── analyzer_agent.py     # Claude KI-Analyse
    ├── planner_agent.py      # Lernplan-Generierung
    ├── flashcard_agent.py    # Flashcard-Generierung
    ├── ml_sr_engine.py       # ML-Spaced-Repetition-Engine
    ├── quiz_agent.py         # MC-Quiz-Generierung
    └── security_manager.py   # HTTP-Audit-Middleware
```

---

## API-Endpoints

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| GET | `/api/health` | Health-Check (Modell, Firebase-Status) |
| POST | `/api/analyze` | PDF-Analyse (SSE-Streaming) |
| POST | `/api/plan` | Lernplan erstellen |
| POST | `/api/flashcards` | Flashcards generieren (SSE-Streaming) |
| POST | `/api/export/anki` | Anki-Deck (.apkg) herunterladen |
| POST | `/api/sr/rate` | Karte bewerten (SM-2) |
| POST | `/api/sr/due` | Fällige Karten abfragen |
| POST | `/api/sr/train` | ML-Modell auf Review-Logs trainieren |
| POST | `/api/quiz/generate` | MC-Quiz generieren (SSE-Streaming) |
| POST | `/api/sessions` | Session erstellen |
| GET | `/api/sessions` | Alle Sessions auflisten |
| GET | `/api/sessions/<id>` | Session laden |
| PATCH | `/api/sessions/<id>` | Session umbenennen |
| DELETE | `/api/sessions/<id>` | Session löschen |
| POST | `/api/sessions/<id>/save` | Session-State speichern |
| GET | `/api/sessions/<id>/export` | Session als JSON exportieren |
| POST | `/api/sessions/import` | Session aus JSON importieren |
| GET | `/api/security/audit` | Audit-Logs (nur localhost) |
| GET | `/api/security/stats` | Security-Statistiken (nur localhost) |

---

## Tastaturkürzel

| Taste | Aktion |
|-------|--------|
| `?` | Hilfe-Overlay öffnen/schließen |
| `Esc` | Modals schließen |
| `Leertaste` / `Enter` | SR-Karte aufdecken |
| `1` `2` `3` `4` | SR bewerten / Quiz-Option wählen |
| `Enter` nach Quiz-Auswahl | Nächste Frage |

---

## Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API Key | – (Pflicht) |
| `FLASK_SECRET_KEY` | Flask Session-Key | dev-secret |
| `FLASK_PORT` | Server-Port | 5000 |
| `CLAUDE_MODEL` | Modell-ID | claude-sonnet-4-6 |
| `CHUNK_SIZE_WORDS` | Wörter pro Analyse-Chunk | 2000 |
| `MAX_PDF_SIZE_MB` | Max. PDF-Größe in MB | 20 |
| `MAX_PAGES` | Max. PDF-Seiten | 200 |
| `STUDYAI_DB` | SQLite-Datenbankpfad | studyai.db |
| `FIREBASE_CREDENTIALS_PATH` | Pfad zur Service-Account-JSON | – (optional) |
| `FIREBASE_PROJECT_ID` | Firebase-Projekt-ID | – (optional) |

---

## Setup für Entwickler

Nach dem Klonen des Repositories einmalig ausführen, um den Pre-commit-Hook für Secret-Detection zu aktivieren:

```bash
# Linux / macOS
chmod +x .github/hooks/pre-commit
git config core.hooksPath .github/hooks

# Windows (PowerShell)
git config core.hooksPath .github/hooks
```

Oder einfach das mitgelieferte Setup-Script verwenden:

```bash
# Linux / macOS
bash setup.sh

# Windows (PowerShell)
git config core.hooksPath .github/hooks
```

Der Hook scannt vor jedem Commit automatisch nach hardcodierten Secrets (API-Keys, Passwörter etc.) via [gitleaks](https://github.com/gitleaks/gitleaks).

---

## Sicherheitshinweise

- Rate-Limiting auf allen Endpoints via flask-limiter
- Input-Validierung auf Typ, Länge und Wertebereich auf allen Endpoints
- Anki-Export race-condition-frei (tmpfile + BytesIO)
- `firebase_credentials.json` und `.env` sind in `.gitignore` – nie committen!
- SecurityManager-Middleware loggt alle HTTP-Requests in SQLite
- `X-Content-Type-Options`, `X-Frame-Options` Security-Header gesetzt
- Security-Audit-Endpoint nur von localhost (`127.0.0.1`) erreichbar
