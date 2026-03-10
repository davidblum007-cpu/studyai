"""
Debug: Was passiert genau beim FlashcardAgent-API-Aufruf?
"""
import requests, json

# Erst: server logs abfragen durch direkten Agent-Test via Minimal-Chunk
# Wir rufen generate_for_chunk direkt auf und geben den echten Fehler aus

CHUNK = {
    "chunks": [{
        "chunk_id": 1,
        "word_count": 50,
        "gesamtzusammenfassung": "Test",
        "themen": [{"titel": "Mittelwert", "kurzfassung": "Durchschnitt aller Werte", "wichtigkeit": 3}],
        "text": "Das arithmetische Mittel ist die Summe aller Werte dividiert durch ihre Anzahl."
    }]
}

# Direkt den SSE-Stream abfangen und raw ausgeben
resp = requests.post("http://localhost:5000/api/flashcards", json=CHUNK, stream=True, timeout=60)
print("Status:", resp.status_code)
for line in resp.iter_lines():
    s = line.decode("utf-8")
    if s:
        print("RAW:", s[:300])
