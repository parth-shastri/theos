"""Weather tools with bounded responses."""

from harness import tool
from theos.services.http import request_json


def weather_tools(settings, http):
    """Build location lookup and forecast tools."""

    @tool
    async def get_weather(location: str, days: int = 3):
        """Get current weather and a daily forecast for a place."""
        places = await request_json(
            http,
            "GET",
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
        )
        if not places.get("results"):
            raise LookupError("Location not found. Add a region or country.")
        place = places["results"][0]
        forecast = await request_json(
            http,
            "GET",
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone": "auto",
                "forecast_days": min(16, max(1, days)),
            },
        )
        return {"location": place, "forecast": forecast}

    return [get_weather]
