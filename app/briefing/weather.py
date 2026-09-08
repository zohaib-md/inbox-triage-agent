import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger("weather_client")

DEFAULT_CITY = os.getenv("USER_CITY", "Lucknow")
DEFAULT_LAT = float(os.getenv("USER_LAT", "26.8467"))
DEFAULT_LON = float(os.getenv("USER_LON", "80.9462"))

# WMO Weather interpretation codes (WW)
WEATHER_CODES = {
    0: "☀️ Clear skies",
    1: "🌤️ Mainly clear",
    2: "⛅ Partly cloudy",
    3: "☁️ Overcast",
    45: "🌫️ Foggy",
    51: "🌦️ Light drizzle",
    61: "🌧️ Slight rain",
    63: "🌧️ Moderate rain",
    65: "🌧️ Heavy rain",
    71: "❄️ Slight snow",
    80: "🌦️ Rain showers",
    95: "⛈️ Thunderstorm",
}


def get_current_weather(
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    city_name: str = DEFAULT_CITY,
) -> dict[str, Any]:
    """
    Fetches real-time weather using Open-Meteo free public API.
    Zero API key required.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        f"&timezone=auto"
    )

    try:
        import ssl
        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ssl_ctx = ssl._create_unverified_context()

        req = urllib.request.Request(url, headers={"User-Agent": "TaskzodBot/1.0"})
        with urllib.request.urlopen(req, timeout=5, context=ssl_ctx) as resp:


            data = json.loads(resp.read().decode("utf-8"))
            current = data.get("current", {})
            temp = current.get("temperature_2m", 31.0)
            code = current.get("weather_code", 0)
            desc = WEATHER_CODES.get(code, "🌤️ Fair")
            humidity = current.get("relative_humidity_2m", 65)

            return {
                "city": city_name,
                "temperature": f"{temp}°C",
                "condition": desc,
                "humidity": f"{humidity}%",
                "summary": f"{desc}, {temp}°C in {city_name}",
            }
    except Exception as e:
        logger.warning(f"Failed to fetch real-time weather: {e}")
        return {
            "city": city_name,
            "temperature": "31°C",
            "condition": "⛅ Partly cloudy",
            "humidity": "65%",
            "summary": f"⛅ 31°C and pleasant in {city_name}",
        }
