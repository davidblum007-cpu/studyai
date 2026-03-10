"""
Test: Ruft /api/flashcards direkt am laufenden Flask-Server auf.
Verwendet echten Statistik-Text um Kartenqualität zu prüfen.
"""
import requests, json

CHUNK = {
    "chunks": [{
        "chunk_id": 1,
        "word_count": 280,
        "gesamtzusammenfassung": "Lagemaße und Streuungsmaße der deskriptiven Statistik.",
        "themen": [
            {"titel": "Arithmetisches Mittel", "kurzfassung": "Summe aller Werte dividiert durch Anzahl.", "wichtigkeit": 3},
            {"titel": "Median", "kurzfassung": "Mittlerer Wert nach Sortierung – robust gegen Ausreißer.", "wichtigkeit": 4},
            {"titel": "Standardabweichung", "kurzfassung": "Durchschnittliche Abweichung vom Mittelwert.", "wichtigkeit": 5},
        ],
        "text": """Deskriptive Statistik – Lagemaße und Streuungsmaße

Das arithmetische Mittel (Durchschnitt) errechnet sich als Summe aller Beobachtungswerte
dividiert durch die Anzahl der Werte. Formel: x̄ = (1/n) × Σxᵢ
Beispiel: Für 2, 4, 6, 8, 10 gilt: x̄ = (2+4+6+8+10)/5 = 6

Der Median ist der Wert, der eine sortierte Wertemenge in zwei gleich große Hälften teilt.
Bei gerader Anzahl: Durchschnitt der beiden mittleren Werte.
Vorteil: Robust gegenüber Ausreißern – daher bei Einkommensverteilungen bevorzugt.

Die Standardabweichung σ misst die durchschnittliche Abweichung der Werte vom Mittelwert.
Formel: σ = √( (1/n) × Σ(xᵢ - x̄)² )
Kleine σ: Werte dicht am Mittelwert. Große σ: Werte streuen stark.

Der Variationskoeffizient (CV = σ/x̄ × 100%) erlaubt Vergleiche zwischen Datensätzen
mit unterschiedlichen Einheiten oder Größenordnungen.

Die Schiefe (Skewness) beschreibt die Asymmetrie:
- Positive Schiefe (rechtsskew): langer rechter Ausläufer, Median < Mittelwert
- Negative Schiefe (linksskew): langer linker Ausläufer, Median > Mittelwert
Normalverteilung: Schiefe = 0, Mittelwert = Median = Modus"""
    }]
}

print("Sende Anfrage an http://localhost:5000/api/flashcards ...")
print("(Dies kann 15-30 Sekunden dauern)\n")

import sys
resp = requests.post(
    "http://localhost:5000/api/flashcards",
    json=CHUNK,
    stream=True,
    timeout=120
)

cards = []
for line in resp.iter_lines():
    line = line.decode("utf-8")
    if line.startswith("event: result"):
        pass
    elif line.startswith("data: ") and '"cards"' in line:
        data = json.loads(line[6:])
        cards = data.get("cards", [])
    elif line.startswith("data: ") and '"message"' in line:
        try:
            d = json.loads(line[6:])
            print(f"  Fortschritt: {d.get('message','')}")
        except: pass

print(f"\n✅ {len(cards)} Karten erhalten:\n" + "="*60)
generic = ["abschnitt", "inhalt konnte nicht", "was ist dieses"]
bad = 0
for i, c in enumerate(cards, 1):
    front = c.get("front","")
    back  = c.get("back","")
    is_bad = any(p in front.lower() for p in generic)
    if is_bad: bad += 1
    flag = " ⚠️  SCHLECHT" if is_bad else ""
    print(f"Karte {i:2d} [{c.get('typ','?')}] ({c.get('schwierigkeit','?')}/5){flag}")
    print(f"  F: {front}")
    print(f"  A: {back}\n")

print("="*60)
if bad == 0:
    print(f"✅ QUALITÄTSPRÜFUNG BESTANDEN: 0 generische Karten!")
else:
    print(f"⚠️  {bad} von {len(cards)} Karten sind generisch/schlecht")
