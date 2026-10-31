# C5: Weather-Aware Outing Planner (FastMCP + OpenAI Agents SDK)

EECE 503P/798S, Agentic Systems. An MCP server with exactly three tools, driven by an agent built with the OpenAI Agents SDK (which acts as the MCP Host + Client).

| Category | Tool | What it does | Side effects |
|---|---|---|---|
| **Data** | `get_weather_forecast(city, days=3, country_code="")` | Daily forecast for a city (Open-Meteo, no API key) | None (read-only) |
| **Action** | `save_reminder(title, remind_date, note="")` | Stores a reminder in a local SQLite file | Writes one row |
| **Orchestration** | `plan_outing(activity, city, date, country_code="")` | Gets the forecast, decides if the day is good, saves a reminder only if so, otherwise suggests a better date | Writes a row only on `go` |

Plus one read-only **resource**: `reminders://all`.

Failure cases (clear errors, never silent): unknown city, `days` out of range, weather service down, empty title, malformed or past date, date outside the 7-day forecast window.

## Layout

```
core.py                 plain-Python logic + typed Pydantic outputs
server.py               FastMCP server (the 3 tools + resource)
client.py               OpenAI Agents SDK host/client (interactive, one-shot, --demo)
tests/test_toolkit.py   15 tests incl. failure cases and an MCP-protocol test
SUMMARY.md              Part 1 written summary
REFLECTION.md           Reflection
DEMO_SCRIPT.md          Screencast outline
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # then add your API key
```

The agent's LLM is selected in `.env` (`LLM_PROVIDER=gemini|openrouter|openai`). Gemini and OpenRouter are used through their OpenAI-compatible endpoints, so no OpenAI key is needed.

## Run

```bash
python -m pytest -q                    # unit tests, no network or API key needed
python client.py --demo                # scripted run: Data, Action, Orchestration, failure
python client.py "Plan a hike in Byblos, Lebanon on 2026-11-04"
python client.py                       # interactive
npx @modelcontextprotocol/inspector python server.py   # optional: inspect the server alone
```

`client.py` prints each step of the round trip: `-> CALL` (agent to MCP client to server) and `<- RESULT` (server back to agent), then the final answer.

## Notes and troubleshooting

- "Tripoli" matches Libya first. Pass `country_code="LB"` (the agent is told to do this).
- Dates for `plan_outing` must be within the next 7 days (the forecast window).
- If the model name in `.env.example` is rejected, set `LLM_MODEL` to one that works for your account.
- Reminders are stored in `reminders.db` (override with `REMINDERS_DB`).
- In Colab/Jupyter, install the requirements, write `.env`/environment variables, and use `await main()` instead of `asyncio.run(main())`.
