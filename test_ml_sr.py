import os
import json
import logging
from agents.ml_sr_engine import MLSpacedRepetitionEngine

logging.basicConfig(level=logging.INFO)

print("🚀 Teste ML-Enhanced Spaced Repetition Engine...")

engine = MLSpacedRepetitionEngine()

# 1. State initialisieren
state = engine.new_card_state("test-card-1")
print(f"Initialer State: {json.dumps(state, indent=2)}")

# 2. Ohne Training bewerten (Einfach = Rating 3) -> erwartetes Basis-Intervall 4 Tage (5760 Min)
print("\n--- Bewertung 1 (Einfach) ---")
state = engine.rate(state, 3)
print(f"State nach 'Einfach': {json.dumps(state, indent=2)}")
print(f"Intervall: {state['interval']} Minuten (Erwartet: 5760)")

# 3. Dummy-Logs trainieren, die zeigen, dass die Karte gut gemerkt wird
print("\n--- ML-Training mit Dummy Logs ---")
logs = []
for i in range(10):
    logs.append({
        "rating": 3,
        "repetitions": 1,
        "interval": 5760,
        "last_rating": 3
    })
engine.train(logs)
print("Modell trainiert!")

# 4. Nach Training bewerten (wieder Einfach) -> Intervall sollte durch ML-Boost > 17280 (5760 * 3) sein
print("\n--- Bewertung 2 (Einfach nach Training) ---")
state = engine.rate(state, 3)
print(f"State nach weiterem 'Einfach': {json.dumps(state, indent=2)}")
print(f"Neues Intervall: {state['interval']} Minuten")

if state['interval'] > 17280:
    print("✅ ML-Boost funktioniert! Intervall wurde durch hohes p(recall) vergrößert.")
else:
    print("⚠️ ML-Boost hat nicht den erwarteten Effekt gehabt.")

print("\nAlle Tests abgeschlossen.")
