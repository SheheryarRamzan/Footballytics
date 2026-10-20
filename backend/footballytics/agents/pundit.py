"""Pundit: answers a fan's free-form question by calling the Football Intelligence tools.

Same tools the MCP server exposes, used in-process. Every answer returns the tool calls it made,
so the UI can show "how I know" (and any number can be traced back to a tool result).
"""

from __future__ import annotations

import json
import time

from agent_framework import Agent, FunctionInvocationContext, FunctionMiddleware

from ..intel import tools
from .clients import chat_client

INSTRUCTIONS = """You are the studio pundit for a live, personalised football broadcast (a fictional league with
synthetic data). Answer the fan's question about the live matchday using your tools; never guess numbers.
Start from list_live_matches or get_moments when you need ids. Answer in the fan's language and mode
(fan: lively and simple; analyst: precise with numbers; kids: very simple; audio: describe clearly for a listener).
Keep answers to at most 4 sentences. If the data cannot answer the question, say so."""


def _jsonable_args(args) -> dict:
    if args is None:
        return {}
    if hasattr(args, "model_dump"):
        return args.model_dump()
    try:
        return dict(args)
    except (TypeError, ValueError):
        return {"value": str(args)}


class _TraceMiddleware(FunctionMiddleware):
    """Records every tool call (name, arguments, duration) for the answer's 'how I know' panel."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        t0 = time.perf_counter()
        error = None
        try:
            await call_next()
        except Exception as exc:  # recorded for the trace, then surfaced to the model as a tool error
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.calls.append({"tool": context.function.name, "args": _jsonable_args(context.arguments),
                               "ms": int((time.perf_counter() - t0) * 1000), "error": error})


async def ask(question: str, language: str = "en", mode: str = "fan", match_id: str | None = None,
              squad: list[str] | None = None, captain: str | None = None) -> dict:
    t0 = time.perf_counter()
    trace = _TraceMiddleware()
    agent = Agent(chat_client("fast"), INSTRUCTIONS, name="pundit", tools=list(tools.TOOLS), middleware=[trace])
    hub = tools.hub()
    players = hub.league.players
    match_of = {}
    for mid, m in hub.matches.items():
        match_of[m.meta["home"]] = match_of[m.meta["away"]] = mid
    fan_squad = [{"player_id": p, "name": players[p].name, "club": players[p].club_id, "captain": p == captain,
                  "match_id": match_of.get(players[p].club_id)} for p in (squad or []) if p in players]
    context = {"language": language, "mode": mode, "watching_match_id": match_id, "fan_squad": fan_squad,
               "note": "refer to players by name, never by id"}
    resp = await agent.run(f"FAN CONTEXT: {json.dumps(context)}\nQUESTION: {question}", options={"store": False})
    return {"answer": resp.text, "tool_calls": trace.calls, "latency_ms": int((time.perf_counter() - t0) * 1000)}
