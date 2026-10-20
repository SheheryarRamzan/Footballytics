"""Recap Editor: writes the full-time story of a match (studio/streaming recap), verified like the newsroom."""

from __future__ import annotations

import json
import time

from agent_framework import Agent

from ..intel import tools
from . import prompts
from .audit import unsupported_numbers
from .clients import chat_client
from .schemas import Recap

_agent: Agent | None = None


def agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(chat_client("reasoning"), prompts.RECAP, name="recap",
                       description="Writes verified full-time match recaps")
    return _agent


def build_input(match_id: str) -> dict:
    hub = tools.hub()
    m = hub.match(match_id)
    snap = m.proc.snapshot(players=True)
    moments = sorted((x for x in hub.moment_log if x.match_id == match_id and x.importance >= 40),
                     key=lambda x: (-x.importance, x.clock))[:10]
    top = sorted(snap["players"].values(), key=lambda p: -p["impact"])[:5]
    keep = ("player_id", "goals", "assists", "xg", "xa", "xt_added", "shots", "key_passes", "saves", "tackles_won",
            "interceptions", "pass_accuracy", "top_speed_kmh", "impact")
    return {
        "match": {"home": m.meta["home_name"], "away": m.meta["away_name"], "home_id": m.meta["home"],
                  "away_id": m.meta["away"], "score": snap["score"], "teams": {
                      t: {k: s.get(k) for k in ("possession", "shots", "shots_on_target", "xg", "big_chances",
                                                 "pass_completion", "high_turnovers", "corners")}
                      for t, s in snap["teams"].items()}},
        "key_moments": [{"minute": x.minute, "kind": x.kind, "team": x.team_id, "players": x.player_ids,
                         "facts": x.facts, "why": x.why} for x in sorted(moments, key=lambda x: x.clock)],
        "momentum_by_minute": [p["value"] for p in m.proc.momentum][::3],
        "top_players": [{**{k: p.get(k) for k in keep}, "name": hub.league.players[p["player_id"]].name}
                        for p in top],
    }


def _check_moment_claims(claims: list[dict], moments: list[dict]) -> list[dict]:
    """A claim about 'a moment' is true if any key moment has that fact with that value."""
    out = []
    for c in claims:
        values = [float(m["facts"][c["metric"]]) for m in moments
                  if isinstance(m["facts"].get(c["metric"]), int | float) and not isinstance(m["facts"][c["metric"]], bool)]
        ok = any(abs(float(c["value"]) - v) <= max(0.05 * abs(v), 0.02 if abs(v) < 1.5 else 0.6) for v in values)
        out.append({**c, "ok": bool(ok), "actual": values[0] if len(values) == 1 else None})
    return out


async def recap(match_id: str) -> dict:
    t0 = time.perf_counter()
    data = build_input(match_id)
    resp = await agent().run("Write the full-time recap.\n" + json.dumps(data, default=str),
                             options={"response_format": Recap, "reasoning": {"effort": "minimal"}, "store": False})
    r = resp.value if isinstance(resp.value, Recap) else Recap.model_validate_json(resp.text)
    claims = [c.model_dump() for c in r.claims]
    live = [c for c in claims if c["subject_id"] != "moment"]
    checks = tools.verify_claims(match_id, live) + _check_moment_claims(
        [c for c in claims if c["subject_id"] == "moment"], data["key_moments"])
    bad = unsupported_numbers([r.summary, r.turning_point, r.tactical_story], [data, checks])
    status = "verified" if all(c["ok"] for c in checks) and not bad else "partially_verified"
    out = r.model_dump(exclude={"claims"})
    out.update({"match_id": match_id, "claims": checks, "unsupported_numbers": bad, "status": status,
                "score": data["match"]["score"], "home": data["match"]["home"], "away": data["match"]["away"],
                "player_of_the_match_name": tools.hub().league.players.get(r.player_of_the_match).name
                if r.player_of_the_match in tools.hub().league.players else r.player_of_the_match,
                "latency_ms": int((time.perf_counter() - t0) * 1000)})
    return out
