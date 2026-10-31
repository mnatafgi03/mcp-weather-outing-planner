"""FastMCP server: exactly three tools (Data, Action, Orchestration) + one read-only resource.

Run standalone (stdio):   python server.py
Inspect interactively:    npx @modelcontextprotocol/inspector python server.py
"""
from __future__ import annotations

import json
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

import core

mcp = FastMCP(
    name="weather-outing-planner",
    instructions=(
        "Tools for weather-aware outing planning. Use get_weather_forecast for weather questions, "
        "save_reminder to store a reminder the user explicitly asked for, and plan_outing when the "
        "user wants to plan an activity on a specific date."
    ),
)


def _guard(fn, *args, **kwargs):
    """Turn expected failures into clear MCP tool errors (isError=true), never silent ones."""
    try:
        return fn(*args, **kwargs)
    except (core.ToolInputError, core.UpstreamError) as exc:
        raise ToolError(str(exc)) from exc


# 1) DATA tool -------------------------------------------------------------- #
@mcp.tool(tags={"data"}, annotations={"readOnlyHint": True, "openWorldHint": True})
def get_weather_forecast(
    city: Annotated[str, Field(description="City name, e.g. 'Tripoli' or 'Beirut'")],
    days: Annotated[int, Field(ge=1, le=7, description="Number of forecast days (1-7)")] = 3,
    country_code: Annotated[
        str, Field(description="Optional 2-letter ISO country code to disambiguate, e.g. 'LB'. Empty = any")
    ] = "",
) -> core.ForecastResult:
    """Look up the daily weather forecast for a city. Read-only: changes nothing.

    Returns per-day conditions, min/max temperature in Celsius and rain chance.
    Fails with a clear error if the city is not found or the weather service is down.
    """
    return _guard(core.get_forecast, city, days, country_code)


# 2) ACTION tool ------------------------------------------------------------ #
@mcp.tool(tags={"action"}, annotations={"readOnlyHint": False, "destructiveHint": False})
def save_reminder(
    title: Annotated[str, Field(description="Short reminder title, max 100 characters")],
    remind_date: Annotated[str, Field(description="Date to be reminded, YYYY-MM-DD")],
    note: Annotated[str, Field(description="Optional extra detail")] = "",
) -> core.Reminder:
    """Save a reminder to the local reminders database. Side effect: writes one new row.

    Fails with a clear error for an empty title, a malformed date, or a date in the past.
    """
    return _guard(core.save_reminder, title, remind_date, note)


# 3) ORCHESTRATION tool ----------------------------------------------------- #
@mcp.tool(tags={"orchestration"}, annotations={"readOnlyHint": False, "openWorldHint": True})
def plan_outing(
    activity: Annotated[str, Field(description="What the user wants to do, e.g. 'Hike at Cedars'")],
    city: Annotated[str, Field(description="City where the activity happens")],
    date: Annotated[str, Field(description="Planned date, YYYY-MM-DD, within the next 7 days")],
    country_code: Annotated[str, Field(description="Optional 2-letter ISO country code, e.g. 'LB'")] = "",
) -> core.OutingPlan:
    """Plan an outing by chaining the other two tools' logic: forecast first, then decide.

    If the weather is good, a reminder is saved (verdict 'go'). If not, nothing is saved and a
    better date is suggested (verdict 'reschedule').
    """
    return _guard(core.plan_outing, activity, city, date, country_code)


# Pure data lookup exposed as a resource (not counted as a tool) ------------- #
@mcp.resource("reminders://all", mime_type="application/json")
def all_reminders() -> str:
    """Every saved reminder, read-only."""
    return json.dumps([r.model_dump() for r in core.list_reminders()], indent=2)


if __name__ == "__main__":
    mcp.run(show_banner=False)  # stdio transport; banner off keeps the demo output clean
