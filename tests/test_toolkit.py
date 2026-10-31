import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: E402
import server  # noqa: E402


def make_fake_http(rain=10, tmax=24.0, results=True, fail=False):
    """Build a stand-in for core._http_get_json (no real network in tests)."""

    def fake(url, params):
        if fail:
            raise core.UpstreamError("The weather service is unavailable right now (fake).")
        if "geocoding" in url:
            if not results:
                return {}
            return {"results": [{"name": "Tripoli", "country": "Lebanon",
                                 "latitude": 34.43, "longitude": 35.84}]}
        n = params["forecast_days"]
        today = dt.date.today()
        return {"daily": {
            "time": [(today + dt.timedelta(days=i)).isoformat() for i in range(n)],
            "weather_code": [1] * n,
            "temperature_2m_max": [tmax] * n,
            "temperature_2m_min": [tmax - 8] * n,
            "precipitation_probability_max": [rain] * n,
        }}

    return fake


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("REMINDERS_DB", str(tmp_path / "test.db"))


def tomorrow():
    return (dt.date.today() + dt.timedelta(days=1)).isoformat()


# ---- Data tool ---------------------------------------------------------------
def test_forecast_ok(monkeypatch):
    monkeypatch.setattr(core, "_http_get_json", make_fake_http())
    res = core.get_forecast("Tripoli", days=3, country_code="lb")
    assert res.city == "Tripoli" and len(res.days) == 3
    assert res.days[0].summary == "Mainly clear"


def test_forecast_unknown_city_is_a_clear_error(monkeypatch):  # FAILURE CASE
    monkeypatch.setattr(core, "_http_get_json", make_fake_http(results=False))
    with pytest.raises(core.ToolInputError, match="Could not find a city"):
        core.get_forecast("Atlantisville")


@pytest.mark.parametrize("days", [0, 8, -1])
def test_forecast_days_out_of_range(days):
    with pytest.raises(core.ToolInputError, match="days must be"):
        core.get_forecast("Tripoli", days=days)


def test_forecast_service_down(monkeypatch):  # FAILURE CASE
    monkeypatch.setattr(core, "_http_get_json", make_fake_http(fail=True))
    with pytest.raises(core.UpstreamError, match="unavailable"):
        core.get_forecast("Tripoli")


# ---- Action tool -------------------------------------------------------------
def test_save_and_list_reminder():
    saved = core.save_reminder("Renew library card", tomorrow(), "bring ID")
    assert saved.id == 1
    assert [r.title for r in core.list_reminders()] == ["Renew library card"]


@pytest.mark.parametrize("title,date,msg", [
    ("", "2099-01-01", "title must be"),
    ("x", "31/02/2099", "YYYY-MM-DD"),
    ("x", "2020-01-01", "in the past"),
])
def test_save_reminder_rejects_bad_input(title, date, msg):  # FAILURE CASE
    with pytest.raises(core.ToolInputError, match=msg):
        core.save_reminder(title, date)
    assert core.list_reminders() == []  # nothing written on failure


# ---- Orchestration tool ------------------------------------------------------
def test_plan_outing_go_saves_reminder(monkeypatch):
    monkeypatch.setattr(core, "_http_get_json", make_fake_http(rain=10, tmax=24))
    plan = core.plan_outing("Hike", "Tripoli", tomorrow())
    assert plan.verdict == "go" and plan.reminder is not None
    assert len(core.list_reminders()) == 1


def test_plan_outing_bad_weather_saves_nothing(monkeypatch):
    monkeypatch.setattr(core, "_http_get_json", make_fake_http(rain=90))
    plan = core.plan_outing("Hike", "Tripoli", tomorrow())
    assert plan.verdict == "reschedule" and plan.reminder is None
    assert core.list_reminders() == []


def test_plan_outing_date_outside_window(monkeypatch):
    monkeypatch.setattr(core, "_http_get_json", make_fake_http())
    far = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    with pytest.raises(core.ToolInputError, match="outside the forecast window"):
        core.plan_outing("Hike", "Tripoli", far)


# ---- MCP layer (in-memory client talks to the real FastMCP server) -----------
def test_server_exposes_exactly_three_tools():
    async def run():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}

    assert asyncio.run(run()) == {"get_weather_forecast", "save_reminder", "plan_outing"}


def test_mcp_error_surfaces_as_tool_error(monkeypatch):  # FAILURE CASE over the protocol
    monkeypatch.setattr(core, "_http_get_json", make_fake_http(results=False))

    async def run():
        async with Client(server.mcp) as c:
            await c.call_tool("get_weather_forecast", {"city": "Atlantisville"})

    with pytest.raises(ToolError, match="Could not find a city"):
        asyncio.run(run())
