"""Rundown agent: the Director's planning brain. On request (and at half-time) it reads the state of
every live match plus the fan's squad and taste, and writes a short personal brief: what to watch
next and why, how the fan's squad is doing, and the storylines across the matchday."""

from __future__ import annotations

import json
import time

from agent_framework import Agent
from pydantic import BaseModel, Field

from ..agents.audit import unsupported_numbers
from ..agents.clients import chat_client
from ..hub import LiveHub
from ..intel import tools
from .profiles import FanProfile

INSTRUCTIONS = """You are the Director of a personalised football broadcast covering every match of a matchday
(a fictional league; synthetic data). Write a short brief for ONE fan in their language and viewing mode.
Plan what they should watch next and why, using their fantasy squad, their club and their taste.
Use only numbers present in the input. Keep player and club names unchanged. Be concrete and lively."""


class WatchNext(BaseModel):
    match_id: str
    why: str = Field(description="One sentence")


class Rundown(BaseModel):
    headline: str = Field(description="At most 10 words")
    summary: str = Field(description="2-3 sentences on the matchday so far, from this fan's point of view")
    squad: str = Field(description="1-2 sentences on how their fantasy squad is doing")
    watch_next: list[WatchNext] = Field(description="1-3 matches to watch next, best first")
    storylines: list[str] = Field(description="2-4 short storylines across the matchday")


_agent: Agent | None = None


def agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(chat_client("reasoning"), INSTRUCTIONS, name="director",
                       description="Plans a personalised multi-match broadcast rundown")
    return _agent


def build_input(fan: FanProfile, hub: LiveHub) -> dict:
    squad_points = tools.fantasy_points(None, fan.squad)
    by_player = {r["player_id"]: r for r in squad_points}
    squad = []
    for pid in fan.squad:
        p = hub.league.players[pid]
        r = by_player.get(pid, {})
        mult = 2 if pid == fan.captain else 1
        squad.append({"player_id": pid, "name": p.name, "club": p.club_id, "pos": p.group,
                      "captain": pid == fan.captain, "points": (r.get("points") or 0) * mult,
                      "playing_in": r.get("match_id")})
    top_moments = tools.get_moments(limit=12)
    return {
        "fan": {"mode": fan.mode, "language": fan.language, "favorite_club": fan.favorite_club,
                "likes_more": [k for k, w in fan.weights.items() if w >= 0.8]},
        "matches": tools.list_live_matches(),
        "recent_moments": [{k: m[k] for k in ("match_id", "kind", "minute", "team", "players", "why")}
                           for m in top_moments],
        "squad": squad,
        "squad_total": sum(s["points"] for s in squad),
    }


async def rundown(fan: FanProfile, hub: LiveHub) -> dict:
    t0 = time.perf_counter()
    data = build_input(fan, hub)
    resp = await agent().run("Write this fan's rundown.\n" + json.dumps(data, default=str),
                             options={"response_format": Rundown, "reasoning": {"effort": "minimal"}, "store": False})
    r = resp.value if isinstance(resp.value, Rundown) else Rundown.model_validate_json(resp.text)
    out = r.model_dump()
    out["unsupported_numbers"] = unsupported_numbers([r.summary, r.squad, *r.storylines], data)
    out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    out["squad_total"] = data["squad_total"]
    return out
