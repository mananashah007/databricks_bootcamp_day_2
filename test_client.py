from weather_client import WeatherClient

client = WeatherClient()

documents = client.harvest_location("Chicago, IL")

print(f"Documents returned: {len(documents)}")

for doc in documents[:3]:
    print("\n-----")
    print("ID:", doc["id"])
    print("Location:", doc["location"])
    print("Title:", doc["title"])
    print("Text:", doc["narrative_text"][:300])