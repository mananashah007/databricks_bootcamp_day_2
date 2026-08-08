from weather_service import WeatherService

service = WeatherService()

count = service.sync_location("Chicago, IL")

print(f"Synced {count} documents")