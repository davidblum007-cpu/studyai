import requests
import json
import os

print("Teste POST /api/export/anki via requests...")

url = "http://localhost:5000/api/export/anki"
payload = {
    "cards": [
        {
            "front": "Front of Card 1",
            "back": "Back of Card 1",
            "typ": "Konzept",
            "tier": "Beginner",
            "diagram": "flowchart TD\n A --> B"
        },
        {
            "front": "Front of Card 2",
            "back": "Back of Card 2",
            "typ": "Definition",
            "tier": "Advanced",
            "diagram": ""
        }
    ]
}

response = requests.post(url, json=payload)

if response.status_code == 200:
    content_disp = response.headers.get("Content-Disposition", "")
    print(f"✅ Success! Status: {response.status_code}, Headers: {content_disp}")
    with open("test_export.apkg", "wb") as f:
        f.write(response.content)
    print("✅ File saved to test_export.apkg, size:", os.path.getsize("test_export.apkg"), "bytes")
else:
    print(f"❌ Failed! Status: {response.status_code}, Body: {response.text}")
