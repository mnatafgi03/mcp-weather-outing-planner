"""OpenAI Agents SDK client = MCP Host + Client for server.py.

Usage:
  python client.py                       # interactive chat
  python client.py "Weather in Beirut?"  # one-shot
  python client.py --demo                # scripted run that hits all three tools + a failure
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIStatusError, AsyncOpenAI

from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from agents.exceptions import AgentsException
from agents.mcp import MCPServerStdio

load_dotenv()
SERVER_PATH = str(Path(__file__).parent / "server.py")

INSTRUCTIONS = """You are an outing-planning assistant connected to three MCP tools.
- Weather questions only      -> get_weather_forecast
- 'Remind me ...' requests    -> save_reminder
- 'Plan/schedule an activity on <date>' -> plan_outing
Resolve relative dates like 'tomorrow' yourself (today is {today}) and pass YYYY-MM-DD.
Tripoli is ambiguous: use country_code 'LB' when the user means Lebanon.
If a tool returns an error, tell the user exactly what went wrong; never invent data."""


def build_model():
    """Pick an LLM backend. Non-OpenAI providers go through the OpenAI-compatible endpoint."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "openai":
        return os.getenv("LLM_MODEL", "gpt-4.1-mini")
    set_tracing_disabled(True)  # tracing uploads to OpenAI, which we don't use here
    if provider == "gemini":
        client = AsyncOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=os.getenv("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"],
        )
        name = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    elif provider == "groq":
        client = AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"]
        )
        name = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    elif provider == "openrouter":
        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"]
        )
        name = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    else:
        sys.exit(f"Unknown LLM_PROVIDER '{provider}' (use gemini, groq, openrouter or openai)")
    return OpenAIChatCompletionsModel(model=name, openai_client=client)


def print_trace(result) -> None:
    """Show the round trip: agent -> MCP client -> server -> back."""
    for item in result.new_items:
        if item.type == "tool_call_item":
            raw = item.raw_item
            print(f"  -> CALL   {getattr(raw, 'name', '?')}({getattr(raw, 'arguments', '')})")
        elif item.type == "tool_call_output_item":
            out = str(item.output)
            print(f"  <- RESULT {out[:400]}{'...' if len(out) > 400 else ''}")


async def ask(agent: Agent, question: str) -> None:
    print(f"\nYOU: {question}")
    try:
        result = await Runner.run(agent, question, max_turns=8)
    except AgentsException as exc:  # some SDK versions raise on tool errors
        print(f"  !! tool/agent error: {exc}")
        return
    except APIStatusError as exc:  # the LLM provider rejected the request: show why
        print(f"  !! LLM API error {exc.status_code}: {exc.response.text[:600]}")
        return
    print_trace(result)
    print(f"AGENT: {result.final_output}")


def demo_questions() -> list[str]:
    import datetime as dt

    today = dt.date.today()
    outing = (today + dt.timedelta(days=3)).isoformat()   # inside the 7-day forecast window
    renew = (today + dt.timedelta(days=20)).isoformat()
    return [
        "What's the weather like in Tripoli, Lebanon for the next 3 days?",   # Data
        f"Remind me to renew my library card on {renew}.",                    # Action
        f"Plan a hike in Byblos, Lebanon on {outing}.",                       # Orchestration
        "What's the weather in Atlantisville?",                               # Failure case
    ]


async def main() -> None:
    import datetime as dt

    args = sys.argv[1:]
    async with MCPServerStdio(
        name="weather-outing-planner",
        params={"command": sys.executable, "args": [SERVER_PATH]},
        cache_tools_list=True,
    ) as server:
        tools = await server.list_tools()
        print("MCP server connected. Tools:", ", ".join(t.name for t in tools))
        agent = Agent(
            name="Outing Planner",
            instructions=INSTRUCTIONS.format(today=dt.date.today().isoformat()),
            mcp_servers=[server],
            model=build_model(),
        )
        if args == ["--demo"]:
            for q in demo_questions():
                await ask(agent, q)
        elif args:
            await ask(agent, " ".join(args))
        else:
            print("Type a request (blank line to quit).")
            while (q := input("\n> ").strip()):
                await ask(agent, q)


if __name__ == "__main__":
    asyncio.run(main())
