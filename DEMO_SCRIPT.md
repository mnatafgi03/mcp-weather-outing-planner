# Screencast outline (5 to 7 minutes)

Before recording: `python -m pytest -q` passes, `.env` has your key, delete `reminders.db` for a clean run.

| Time | Show | Say |
|---|---|---|
| 0:00-0:45 | README table | Theme: weather-aware outing planner. Name the three tools: **Data** = `get_weather_forecast`, **Action** = `save_reminder`, **Orchestration** = `plan_outing`. |
| 0:45-1:45 | `server.py` | Typed arguments and docstrings are the tool interface the model reads. Point at the `readOnlyHint` annotations and at `_guard` turning failures into clear tool errors. Mention `core.py` holds the logic. |
| 1:45-2:30 | `client.py` | Agents SDK is the Host; `MCPServerStdio` is the Client that spawns the server. Show `build_model` (Gemini via the OpenAI-compatible endpoint). |
| 2:30-5:00 | Terminal: `python client.py --demo` | Narrate each query: (1) forecast -> Data tool, (2) reminder -> Action tool, (3) hike on a date -> Orchestration tool; point at `-> CALL` / `<- RESULT` lines as the round trip. |
| 5:00-5:40 | Same run, query 4 | Unknown city: the server returns an error, the agent explains it instead of inventing data. |
| 5:40-6:20 | `python -m pytest -q` | 15 tests, including the failure cases and the "exactly three tools" check. |
| 6:20-7:00 | Challenges + repo link | Keeping tools single-purpose (geocoding folded into the forecast tool; policy kept in the orchestrator); predictable errors; Tripoli ambiguity. Share the GitHub link. |

Optional extra beat: run `python client.py "Plan a picnic in Beirut on <a rainy date>"` if the forecast shows rain, to show the `reschedule` branch saving nothing.
