"""Weather tools with bounded responses."""

from harness import tool
from theos.services.http import request_json


def weather_tools(settings, http):
    """Build location lookup and forecast tools."""

    # @tool reads this function's name, docstring, and annotations to give the model a
    # validated JSON schema. The function body is the real service action.
    @tool
    async def get_weather(location: str, days: int = 3):
        """Get current weather and a daily forecast for a place."""
        # The forecast API needs coordinates, so first turn the user's place name into
        # one location result.
        places = await request_json(
            http,
            "GET",
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
        )
        if not places.get("results"):
            raise LookupError("Location not found. Add a region or country.")
        place = places["results"][0]
        # Ask for both current and daily data. Clamp days so a model cannot request an
        # unbounded forecast response.
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
        # Return structured data; the harness serializes it as a tool result for the model.
        return {"location": place, "forecast": forecast}

    # Runtime adds this list to the tools available in a particular conversation.
    return [get_weather]
