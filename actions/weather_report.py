# actions/weather_report.py
# Real weather data via wttr.in API -- no API key needed.

import logging  # migrated from print()
import contextlib
import json
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None

BASE_DIR = get_base_dir()

def _get_api_key() -> str:
    if _get_gemini_key is not None:
        return _get_gemini_key()
    with open(BASE_DIR / "config" / "api_keys.json", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _fetch_weather(city: str) -> dict | None:
    """
    Fetches real weather data from wttr.in.
    Returns dict with: location, temp_c, temp_f, condition, humidity,
    wind_kph, feels_like_c, feels_like_f, uv_index, visibility_km,
    forecast (list of daily summaries), sunrise, sunset.
    Returns None on failure.
    """
    if not _REQUESTS_OK:
        return None

    try:
        url = f"https://wttr.in/{quote_plus(city)}?format=j1"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "curl/7.68.0"})
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current_condition", [{}])[0]
        nearest = data.get("nearest_area", [{}])[0]

        result = {
            "location":    nearest.get("areaName", [{}])[0].get("value", city.title()),
            "region":      nearest.get("region",    [{}])[0].get("value", ""),
            "country":     nearest.get("country",   [{}])[0].get("value", ""),
            "temp_c":      int(current.get("temp_C", 0)),
            "temp_f":      int(current.get("temp_F", 32)),
            "condition":   current.get("weatherDesc", [{}])[0].get("value", "Unknown"),
            "humidity":    int(current.get("humidity", 0)),
            "wind_kph":    int(current.get("windspeedKmph", 0)),
            "wind_dir":    current.get("winddir16Point", "").strip(),
            "feels_like_c": int(current.get("FeelsLikeC", 0)),
            "feels_like_f": int(current.get("FeelsLikeF", 32)),
            "uv_index":    int(current.get("uvIndex", 0)),
            "visibility_km": int(current.get("visibility", 0)),
            "pressure_mb": int(current.get("pressure", 0)),
            "sunrise":     data.get("weather", [{}])[0].get("astronomy", [{}])[0].get("sunrise", ""),
            "sunset":      data.get("weather", [{}])[0].get("astronomy", [{}])[0].get("sunset", ""),
            "forecast": [],
        }

        # Parse 3-day forecast
        for day in data.get("weather", []):
            date    = day.get("date", "")
            max_c   = day.get("maxtempC", "0")
            min_c   = day.get("mintempC", "0")
            avg_c   = day.get("avgtempC", "0")
            cond    = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "")
            rain_mm = day.get("hourly", [{}])[4].get("precipMM", "0")
            result["forecast"].append({
                "date":    date,
                "high_c":  int(max_c),
                "low_c":   int(min_c),
                "avg_c":   int(avg_c),
                "condition": cond,
                "rain_mm": float(rain_mm),
            })

        return result

    except Exception as e:
        logging.getLogger("Weather").info(f"Fetch failed: {e}")
        return None


def _format_weather(weather: dict) -> str:
    """Formats weather data into a natural spoken response."""
    loc      = weather.get("location", "")
    region   = weather.get("region", "")
    cond     = weather.get("condition", "").lower()
    temp_c   = weather.get("temp_c", 0)
    temp_f   = weather.get("temp_f", 0)
    feels_c  = weather.get("feels_like_c", 0)
    humidity  = weather.get("humidity", 0)
    wind_kph  = weather.get("wind_kph", 0)
    wind_dir  = weather.get("wind_dir", "")
    uv        = weather.get("uv_index", 0)
    sunrise   = weather.get("sunrise", "")
    sunset    = weather.get("sunset", "")
    forecast  = weather.get("forecast", [])

    lines = []

    # Current conditions
    location_str = f"{loc}" + (f", {region}" if region else "")
    lines.append(f"Weather for {location_str}:")
    lines.append(f"Condition: {cond.capitalize()}")
    lines.append(f"Temperature: {temp_c}°C / {temp_f}°F")
    lines.append(f"Feels like: {feels_c}°C / {feels_c * 9 // 5 + 32}°F")
    lines.append(f"Humidity: {humidity}%")
    lines.append(f"Wind: {wind_kph} km/h {wind_dir}")
    lines.append(f"UV Index: {uv}")

    if sunrise:
        lines.append(f"Sunrise: {sunrise} | Sunset: {sunset}")

    # 3-day forecast
    if forecast:
        lines.append("\n3-Day Forecast:")
        day_names = ["Today", "Tomorrow", "Day After"]
        for i, day in enumerate(forecast[:3]):
            dn   = day_names[i] if i < len(day_names) else day.get("date", f"Day {i+1}")
            hi   = day.get("high_c", 0)
            lo   = day.get("low_c", 0)
            dc   = day.get("condition", "").lower()
            rain = day.get("rain_mm", 0)
            rain_str = f" | {rain}mm rain" if rain > 0 else ""
            lines.append(f"  {dn}: {dc.capitalize()} -- High {hi}°C / Low {lo}°C{rain_str}")

    return "\n".join(lines)


def _speak_weather(weather: dict) -> str:
    """Short spoken summary of current weather."""
    cond    = weather.get("condition", "").lower()
    temp_c  = weather.get("temp_c", 0)
    feels_c = weather.get("feels_like_c", 0)
    humidity = weather.get("humidity", 0)
    wind_kph = weather.get("wind_kph", 0)
    loc     = weather.get("location", "")

    return (
        f"Right now in {loc}, it's {cond} with a temperature of {temp_c} degrees Celsius. "
        f"It feels like {feels_c} degrees. "
        f"Humidity is at {humidity} percent, "
        f"with wind at {wind_kph} kilometers per hour."
    )


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None
):
    """
    Weather report action using wttr.in API.
    Fetches real weather data and returns both spoken and detailed output.
    Falls back to browser open if API fails.
    """
    city = parameters.get("city")
    time_param = parameters.get("time")

    if not city or not isinstance(city, str):
        msg = "Sir, the city is missing for the weather report."
        _speak_and_log(msg, player)
        return msg

    city = city.strip()

    if player:
        player.write_log(f"[Weather] Fetching weather for: {city}")

    # Try real API first
    if _REQUESTS_OK:
        weather = _fetch_weather(city)
        if weather:
            spoken = _speak_weather(weather)
            detailed = _format_weather(weather)
            _speak_and_log(spoken, player)
            return detailed

    # Fallback: open browser search
    search_query = f"weather in {city}" + (f" {time_param}" if time_param else "")
    url = f"https://www.google.com/search?q={quote_plus(search_query)}"
    with contextlib.suppress(Exception):
        webbrowser.open(url)

    msg = f"Showing the weather for {city}, sir."
    _speak_and_log(msg, player)
    return msg


def _speak_and_log(message: str, player=None):
    if player:
        with contextlib.suppress(Exception):
            player.write_log(f"JARVIS: {message}")
