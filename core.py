"""Plain-Python logic behind the three MCP tools.

Keeping the logic here (and not inside the @mcp.tool functions) means:
  * the Orchestration tool can reuse the Data and Action logic directly,
  * everything is unit-testable without starting an MCP server.

Theme: weather-aware outing planner.
  Data          -> get_forecast        (Open-Meteo geocoding + forecast, read-only)
  Action        -> save_reminder       (writes a row to a local SQLite file)
  Orchestration -> plan_outing         (forecast -> decide -> maybe save reminder)
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 7

# Thresholds the orchestrator uses to call a day "good for an outing".
MAX_RAIN_CHANCE = 40  # percent
MIN_TEMP_C = 10.0
MAX_TEMP_C = 33.0


# --------------------------------------------------------------------------- #
# Errors: predictable, human-readable failures (never silent)
# --------------------------------------------------------------------------- #
class ToolInputError(ValueError):
    """The caller passed something invalid (bad date, unknown city, ...)."""


class UpstreamError(RuntimeError):
    """An external resource (the weather API) was unavailable."""


# --------------------------------------------------------------------------- #
# Typed outputs
# --------------------------------------------------------------------------- #
class DailyForecast(BaseModel):
    date: str = Field(description="Local date, YYYY-MM-DD")
    summary: str = Field(description="Plain-English conditions, e.g. 'Light rain'")
    temp_max_c: float
    temp_min_c: float
    rain_chance_pct: int = Field(description="Max precipitation probability, 0-100")


class ForecastResult(BaseModel):
    city: str
    country: str
    latitude: float
    longitude: float
    days: list[DailyForecast]


class Reminder(BaseModel):
    id: int
    title: str
    remind_date: str = Field(description="YYYY-MM-DD")
    note: str
    created_at: str = Field(description="UTC ISO timestamp")


class OutingPlan(BaseModel):
    verdict: str = Field(description="'go' (reminder saved) or 'reschedule' (nothing saved)")
    city: str
    date: str
    forecast: DailyForecast
    reason: str
    reminder: Reminder | None = Field(
        default=None, description="Present only when verdict == 'go'"
    )
    suggested_date: str | None = Field(
        default=None, description="Better day in the window, when verdict == 'reschedule'"
    )


# --------------------------------------------------------------------------- #
# Data tool logic
# --------------------------------------------------------------------------- #
_WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light rain showers", 81: "Rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}


def _http_get_json(url: str, params: dict) -> dict:
    """The only place that touches the network (easy to monkeypatch in tests)."""
    try:
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise UpstreamError(
            f"The weather service is unavailable right now ({type(exc).__name__}). "
            "Try again in a moment."
        ) from exc


def get_forecast(city: str, days: int = 3, country_code: str = "") -> ForecastResult:
    city = (city or "").strip()
    country_code = (country_code or "").strip().upper()
    if not city:
        raise ToolInputError("city must be a non-empty string.")
    if not 1 <= days <= MAX_FORECAST_DAYS:
        raise ToolInputError(f"days must be between 1 and {MAX_FORECAST_DAYS}, got {days}.")
    if country_code and not (len(country_code) == 2 and country_code.isalpha()):
        raise ToolInputError("country_code must be a 2-letter ISO code such as 'LB' or leave it empty.")

    geo_params = {"name": city, "count": 1, "language": "en", "format": "json"}
    if country_code:
        geo_params["countryCode"] = country_code
    places = _http_get_json(GEOCODE_URL, geo_params).get("results") or []
    if not places:
        hint = f" in country '{country_code}'" if country_code else ""
        raise ToolInputError(
            f"Could not find a city called '{city}'{hint}. "
            "Check the spelling or pass a country_code (e.g. 'LB')."
        )
    place = places[0]

    data = _http_get_json(
        FORECAST_URL,
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": days,
        },
    )
    daily = data.get("daily")
    if not daily or not daily.get("time"):
        raise UpstreamError("The weather service returned no forecast data.")

    rows = []
    for i, date in enumerate(daily["time"]):
        rain = daily["precipitation_probability_max"][i]
        rows.append(
            DailyForecast(
                date=date,
                summary=_WEATHER_CODES.get(daily["weather_code"][i], "Unknown conditions"),
                temp_max_c=daily["temperature_2m_max"][i],
                temp_min_c=daily["temperature_2m_min"][i],
                rain_chance_pct=int(rain) if rain is not None else 0,
            )
        )
    return ForecastResult(
        city=place["name"],
        country=place.get("country", ""),
        latitude=place["latitude"],
        longitude=place["longitude"],
        days=rows,
    )


# --------------------------------------------------------------------------- #
# Action tool logic
# --------------------------------------------------------------------------- #
def _db_path() -> Path:
    return Path(os.environ.get("REMINDERS_DB", Path(__file__).parent / "reminders.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS reminders (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               remind_date TEXT NOT NULL,
               note TEXT NOT NULL DEFAULT '',
               created_at TEXT NOT NULL)"""
    )
    return conn


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(**dict(row))


def save_reminder(title: str, remind_date: str, note: str = "") -> Reminder:
    title = (title or "").strip()
    if not title:
        raise ToolInputError("title must be a non-empty string.")
    if len(title) > 100:
        raise ToolInputError("title must be 100 characters or fewer.")
    try:
        day = dt.date.fromisoformat(remind_date)
    except (TypeError, ValueError):
        raise ToolInputError(
            f"remind_date must be a real date in YYYY-MM-DD format, got {remind_date!r}."
        ) from None
    # One day of grace so a forecast date in a timezone behind ours is still accepted.
    if day < dt.date.today() - dt.timedelta(days=1):
        raise ToolInputError(f"remind_date {remind_date} is in the past.")

    created = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (title, remind_date, note, created_at) VALUES (?, ?, ?, ?)",
            (title, remind_date, note.strip(), created),
        )
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_reminder(row)


def list_reminders() -> list[Reminder]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM reminders ORDER BY remind_date, id").fetchall()
    return [_row_to_reminder(r) for r in rows]


# --------------------------------------------------------------------------- #
# Orchestration tool logic
# --------------------------------------------------------------------------- #
def _is_good_day(d: DailyForecast) -> bool:
    return d.rain_chance_pct <= MAX_RAIN_CHANCE and MIN_TEMP_C <= d.temp_max_c <= MAX_TEMP_C


def _describe(d: DailyForecast) -> str:
    return f"{d.summary}, {d.temp_min_c:.0f}-{d.temp_max_c:.0f} C, {d.rain_chance_pct}% chance of rain"


def plan_outing(activity: str, city: str, date: str, country_code: str = "") -> OutingPlan:
    """Forecast -> decide -> (only if the weather is fine) save a reminder."""
    activity = (activity or "").strip()
    if not activity:
        raise ToolInputError("activity must be a non-empty string.")
    try:
        dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        raise ToolInputError(f"date must be a real date in YYYY-MM-DD format, got {date!r}.") from None

    forecast = get_forecast(city, days=MAX_FORECAST_DAYS, country_code=country_code)  # DATA step
    by_date = {d.date: d for d in forecast.days}
    if date not in by_date:
        raise ToolInputError(
            f"{date} is outside the forecast window ({forecast.days[0].date} to {forecast.days[-1].date})."
        )
    day = by_date[date]

    if _is_good_day(day):
        reminder = save_reminder(  # ACTION step
            title=f"{activity} in {forecast.city}",
            remind_date=date,
            note=f"Forecast: {_describe(day)}",
        )
        return OutingPlan(
            verdict="go", city=forecast.city, date=date, forecast=day,
            reason=f"Good weather for it: {_describe(day)}. Reminder saved.",
            reminder=reminder,
        )

    # Not a good day: save nothing, suggest the best alternative in the window.
    others = [d for d in forecast.days if d.date != date]
    good = [d for d in others if _is_good_day(d)]
    best = good[0] if good else min(others, key=lambda d: d.rain_chance_pct, default=None)
    return OutingPlan(
        verdict="reschedule", city=forecast.city, date=date, forecast=day,
        reason=f"Weather is poor on {date}: {_describe(day)}. No reminder was saved.",
        suggested_date=best.date if best else None,
    )
