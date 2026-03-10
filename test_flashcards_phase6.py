import os
import json
import logging
from agents.flashcard_agent import FlashcardAgent
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

print("🚀 Teste Phase 6: Web-Augmented & Tiered Flashcard Agent...")

agent = FlashcardAgent()

# Dummy Chunk
test_chunks = [{
    "chunk_id": 1,
    "word_count": 350,
    "themen": [
        {"titel": "Kryptowährung", "kurzfassung": "Digitale Währung", "wichtigkeit": 5}
    ],
    "text": "Eine Kryptowährung ist ein digitales Zahlungsmittel. Das System basiert auf einer dezentralen Technologie, der sogenannten Blockchain."
}]

result = agent.generate_for_all_chunks(test_chunks)

total_cards = result.get('total_cards', 0)
cards = result.get('cards', [])

print(f"\nGenerierte Karten: {total_cards}")

if total_cards > 0:
    print(f"\nBeispiel-Karte 1: {json.dumps(cards[0], indent=2, ensure_ascii=False)}")
    print(f"\nBeispiel-Karte {total_cards}: {json.dumps(cards[-1], indent=2, ensure_ascii=False)}")
    
    tiers_found = set(c.get('tier') for c in cards)
    print(f"\nGefundene Tiers: {tiers_found}")
    
    if len(cards) >= 12:
        print("\n✅ Lautstärke/Anzahl der Karten ist gut!")
    else:
        print("\n⚠️ Eher wenig Karten generiert.")
        
    if "Beginner" in tiers_found and ("Intermediate" in tiers_found or "Advanced" in tiers_found):
        print("✅ Tier-Verteilung ist erfolgreich!")
    else:
        print("⚠️ Nicht alle Tiers vertreten.")
else:
    print("\n❌ Keine Karten generiert.")
