"""
StudyAI – Firebase Setup Helper
================================
Führe dieses Script NACH dem Download der Service-Account-JSON aus:
  python firebase_setup.py /pfad/zu/serviceAccountKey.json

Das Script:
  1. Prüft die JSON-Datei auf Gültigkeit
  2. Kopiert sie als 'firebase_credentials.json' in den Projektordner
  3. Liest die Projekt-ID aus der Datei
  4. Schreibt FIREBASE_CREDENTIALS_PATH und FIREBASE_PROJECT_ID in .env
  5. Startet einen Verbindungstest
"""

import sys
import json
import shutil
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"
CREDS_DEST = BASE_DIR / "firebase_credentials.json"


def main():
    if len(sys.argv) < 2:
        print("\n  Verwendung: python firebase_setup.py <pfad_zur_serviceAccountKey.json>\n")
        print("  Beispiel:   python firebase_setup.py C:/Users/daveb/Downloads/myproject-abc123.json\n")
        sys.exit(1)

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"\n  FEHLER: Datei nicht gefunden: {src}\n")
        sys.exit(1)

    # JSON einlesen und validieren
    try:
        with open(src, encoding="utf-8") as f:
            creds = json.load(f)
    except json.JSONDecodeError as e:
        print(f"\n  FEHLER: Keine gültige JSON-Datei: {e}\n")
        sys.exit(1)

    required = ["project_id", "private_key", "client_email", "type"]
    missing = [k for k in required if k not in creds]
    if missing:
        print(f"\n  FEHLER: Fehlende Felder in der JSON: {missing}")
        print("  Stelle sicher, dass du eine Service-Account-Datei verwendest.\n")
        sys.exit(1)

    if creds.get("type") != "service_account":
        print(f"\n  FEHLER: Falscher Credentials-Typ: {creds.get('type')}")
        print("  Benötigt wird 'service_account'.\n")
        sys.exit(1)

    project_id = creds["project_id"]
    print(f"\n  Projekt-ID erkannt: {project_id}")

    # Datei in Projektordner kopieren
    shutil.copy2(src, CREDS_DEST)
    print(f"  Credentials kopiert nach: {CREDS_DEST}")

    # .env lesen
    if ENV_PATH.exists():
        with open(ENV_PATH, encoding="utf-8") as f:
            env_content = f.read()
    else:
        env_content = ""

    # Bestehende Firebase-Einträge entfernen/aktualisieren
    lines = env_content.splitlines()
    new_lines = []
    firebase_written = False
    for line in lines:
        if line.startswith("FIREBASE_CREDENTIALS_PATH=") or line.startswith("FIREBASE_PROJECT_ID="):
            continue  # alte Werte überspringen
        if line.startswith("# FIREBASE_CREDENTIALS_PATH=") or line.startswith("# FIREBASE_PROJECT_ID="):
            if not firebase_written:
                new_lines.append(f"FIREBASE_CREDENTIALS_PATH={CREDS_DEST}")
                new_lines.append(f"FIREBASE_PROJECT_ID={project_id}")
                firebase_written = True
            continue
        new_lines.append(line)

    if not firebase_written:
        new_lines.append("")
        new_lines.append(f"FIREBASE_CREDENTIALS_PATH={CREDS_DEST}")
        new_lines.append(f"FIREBASE_PROJECT_ID={project_id}")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")

    print(f"  .env aktualisiert mit Firebase-Konfiguration")

    # Verbindungstest
    print("\n  Teste Firebase-Verbindung...")
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        cred = credentials.Certificate(str(CREDS_DEST))
        firebase_admin.initialize_app(cred, {"projectId": project_id})
        db = firestore.client()
        # Einfacher Test: Collection abfragen
        list(db.collection("_ping").limit(1).stream())
        print(f"  Verbindung zu Firebase erfolgreich!")
        print(f"\n  Starte jetzt den Server neu: python server.py\n")
    except Exception as e:
        print(f"  Verbindungstest: {e}")
        print(f"  (Das kann ignoriert werden wenn Firestore noch nicht aktiviert ist)")
        print(f"\n  Gehe zu: https://console.firebase.google.com/project/{project_id}/firestore")
        print(f"  Klicke 'Create database' und wähle einen Standort.")
        print(f"\n  Dann Server neu starten: python server.py\n")


if __name__ == "__main__":
    main()
