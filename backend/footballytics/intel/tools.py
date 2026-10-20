"""Football Intelligence tools: one implementation, exposed twice.

* Over MCP (``mcp_server.py``) for any MCP client: GitHub Copilot, Claude, Foundry agents.
* As in-process Agent Framework function tools for our own agents (zero network hop).

Outputs are deliberately compact JSON so agents spend tokens on reasoning, not payloads.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

import numpy as np

from ..engine.metrics import control_share, pitch_control
from ..hub import LiveHub

_HUB: LiveHub | None = None


def bind(hub: LiveHub) -> None:
    """Point the tool functions at a live hub (call once at start-up)."""
    global _HUB
    _HUB = hub


def hub() -> LiveHub:
    if _HUB is None:
        raise RuntimeError("tools are not bound to a LiveHub; call footballytics.intel.tools.bind(hub)")
    return _HUB


def _name(pid: str | None) -> str | None:
    if not pid:
        return None
    p = hub().league.players.get(pid)
    return p.name if p else hub().league.clubs[pid].name if pid in hub().league.clubs else pid


def _round(v: Any) -> Any:
    if isinstance(v, float | np.floating):
        return round(float(v), 3)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_round(x) for x in v]
    return v


# --------------------------------------------------------------------------- tools
def list_live_matches() -> list[dict]:
    """List every match on the current matchday with live score, minute and status (PRE/LIVE/HT/FT)."""
    return [m.summary() for m in hub().matches.values()]


def get_match_state(match_id: Annotated[str, "Match id, e.g. md09-RIV-KGA"]) -> dict:
    """Live team statistics for one match: score, minute, possession, passes, pass completion, shots,
    xG, expected threat (xT), big chances, high turnovers, distance, current control regime and the
    last 10 minutes of momentum (positive = home team on top)."""
    snap = hub().match(match_id).proc.snapshot(players=False)
    return _round({k: snap[k] for k in ("match_id", "home_name", "away_name", "minute", "period", "score",
                                         "regime", "teams")} | {"momentum": snap["momentum"][-10:]})


def get_player_stats(match_id: Annotated[str, "Match id"], player_id: Annotated[str, "Player id, e.g. RIV-09"]) -> dict:
    """In-match statistics for one player: passes, pass accuracy (completion), average pass difficulty
    (1-10), key passes, xG, xA, xT added, shots, goals, assists, defensive actions, distance, top speed,
    sprints, impact score and live fantasy points with an itemised breakdown."""
    proc = hub().match(match_id).proc
    if player_id not in proc.players:
        raise KeyError(f"{player_id} has not played in {match_id}")
    st = proc.players[player_id].to_dict()
    fantasy = proc.snapshot()["fantasy"].get(player_id)
    return _round({"name": _name(player_id), **st, "fantasy": fantasy})


def find_player(query: Annotated[str, "Part of a player name, a club name or a player id"]) -> list[dict]:
    """Find players by (partial) name or club. Returns up to 10 matches with id, name, club, role."""
    q = query.lower().strip()
    league = hub().league
    out = []
    for p in league.players.values():
        club = league.clubs[p.club_id].name
        if q in p.name.lower() or q in club.lower() or q == p.id.lower():
            out.append({"player_id": p.id, "name": p.name, "club": club, "role": p.role, "group": p.group,
                        "fantasy_price": p.price})
        if len(out) >= 10:
            break
    return out


def get_moments(match_id: Annotated[str | None, "Match id, or null for all live matches"] = None,
                since_minute: Annotated[int, "Only moments from this minute on"] = 0,
                kinds: Annotated[list[str] | None, "Filter, e.g. ['goal','big_chance','momentum_swing']"] = None,
                limit: Annotated[int, "Max moments (most recent first)"] = 15) -> list[dict]:
    """Recent key moments detected by the stats engine, most recent first. Each has kind, minute,
    importance (0-100), players, key facts, factual reasons ('why') and evidence event ids."""
    res = []
    for m in reversed(hub().moment_log):
        if match_id and m.match_id != match_id:
            continue
        if m.minute < since_minute or (kinds and m.kind not in kinds):
            continue
        res.append({"moment_id": m.moment_id, "match_id": m.match_id, "kind": m.kind, "minute": m.minute,
                    "importance": m.importance, "team": _name(m.team_id), "players": [_name(p) for p in m.player_ids],
                    "facts": m.facts, "why": m.why, "evidence": m.evidence})
        if len(res) >= limit:
            break
    return _round(res)


def explain_moment(moment_id: Annotated[str, "Moment id from get_moments"]) -> dict:
    """Everything needed to explain a moment: its facts and reasons, plus the full evidence events
    including the engine's measured assessment (xG factors, pass difficulty factors, speeds)."""
    m = hub().moment(moment_id)
    proc = hub().match(m.match_id).proc
    evidence = []
    wanted = set(m.evidence)
    for e in reversed(proc.events):
        if e["event_id"] in wanted:
            evidence.append({"event_id": e["event_id"], "type": e["type"], "minute": int(e["clock"] // 60) + 1,
                             "player": _name(e.get("player_id")), "outcome": e.get("outcome"),
                             "qualifiers": {k: v for k, v in e["qualifiers"].items() if not k.startswith("_")},
                             "assessment": e.get("_assessment")})
            if len(evidence) == len(wanted):
                break
    return _round({"moment_id": m.moment_id, "kind": m.kind, "minute": m.minute, "team": _name(m.team_id),
                   "players": {p: _name(p) for p in m.player_ids}, "facts": m.facts, "why": m.why,
                   "evidence": evidence, "score": m.facts.get("score")})


def get_events(match_id: Annotated[str, "Match id"],
               types: Annotated[list[str] | None, "Event types, e.g. ['shot','goal','card']"] = None,
               player_id: Annotated[str | None, "Only this player's events"] = None,
               from_minute: Annotated[int, "Start minute"] = 0,
               to_minute: Annotated[int, "End minute"] = 130,
               limit: Annotated[int, "Max events (most recent first)"] = 25) -> list[dict]:
    """Raw match events (the evidence log) filtered by type, player and minute range, most recent first."""
    out = []
    for e in reversed(hub().match(match_id).proc.events):
        minute = int(e["clock"] // 60) + 1
        if not from_minute <= minute <= to_minute:
            continue
        if (types and e["type"] not in types) or (player_id and e.get("player_id") != player_id):
            continue
        out.append({"event_id": e["event_id"], "minute": minute, "type": e["type"], "team": e.get("team_id"),
                    "player": _name(e.get("player_id")), "outcome": e.get("outcome"),
                    "x": e.get("x"), "y": e.get("y"), "assessment": e.get("_assessment")})
        if len(out) >= limit:
            break
    return _round(out)


_PLAYER_METRICS = {"goals", "assists", "shots", "xg", "xa", "xt_added", "passes", "passes_completed", "pass_accuracy",
                   "key_passes", "distance_km", "top_speed_kmh", "sprints", "saves", "tackles_won", "interceptions",
                   "recoveries", "impact"}
_TEAM_METRICS = {"goals", "shots", "shots_on_target", "xg", "xt", "passes", "pass_completion", "possession",
                 "big_chances", "corners", "fouls", "high_turnovers", "distance_km"}


def verify_claims(match_id: Annotated[str, "Match id"],
                  claims: Annotated[list[dict], "Claims as {subject_id, metric, value}; subject is a player id or club id"]
                  ) -> list[dict]:
    """Fact-check numeric claims against the live data. Supported player metrics: goals, assists, shots, xg,
    xa, xt_added, passes, pass_accuracy, key_passes, distance_km, top_speed_kmh, sprints, saves, tackles_won,
    interceptions, recoveries, impact. Team metrics: goals, shots, shots_on_target, xg, xt, passes,
    pass_completion, possession, big_chances, corners, fouls, high_turnovers, distance_km. Ratios are 0-1.
    Returns each claim with ok, actual value and tolerance used."""
    snap = hub().match(match_id).proc.snapshot()
    season = hub().season
    results = []
    for c in claims:
        sid, metric, value = c.get("subject_id"), c.get("metric"), c.get("value")
        actual = None
        if sid in snap["teams"] and metric in _TEAM_METRICS:
            actual = snap["teams"][sid].get(metric)
        elif sid in snap.get("players", {}) and metric in _PLAYER_METRICS:
            actual = snap["players"][sid].get(metric)
        elif metric in ("season_goals", "season_assists", "season_apps") and sid in hub().league.players:
            before = season.get("players", {}).get(sid, {})
            live = snap.get("players", {}).get(sid, {})
            key = metric.removeprefix("season_")
            actual = before.get(key, 0) + (live.get(key, 0) if key != "apps" else (1 if live else 0))
        elif metric in ("table_position", "table_points") and sid in hub().league.clubs:
            row = next((r for r in season.get("table", []) if r["club"] == sid), None)
            actual = row and row["pos" if metric == "table_position" else "pts"]
        if actual is None or value is None:
            results.append({**c, "ok": False, "actual": actual, "reason": "unknown subject or metric"})
            continue
        tol = max(0.05 * abs(actual), 0.02 if isinstance(actual, float) and actual < 1.5 else 0.5)
        ok = bool(math.isclose(float(value), float(actual), abs_tol=float(tol)))
        results.append({**c, "ok": ok, "actual": _round(actual), "tolerance": round(float(tol), 3)})
    return results


def get_pitch_control(match_id: Annotated[str, "Match id"]) -> dict:
    """Who controls which space right now (time-to-intercept pitch control from tracking). Returns the home
    team's overall share, each side's share of its attacking half, and a coarse 7x5 grid of home control
    probabilities (rows = touchline to touchline, columns = left goal to right goal)."""
    m = hub().match(match_id)
    f = m.last_frame
    if f is None:
        raise ValueError("match has not started")
    home, away = m.meta["home"], m.meta["away"]
    team_of = m.proc.team_of
    hxy = np.array([(p[1], p[2]) for p in f["players"] if team_of.get(p[0]) == home])
    axy = np.array([(p[1], p[2]) for p in f["players"] if team_of.get(p[0]) == away])
    grid = pitch_control(hxy, axy, nx=21, ny=14)
    coarse = grid.reshape(7, 2, 7, 3).mean(axis=(1, 3))
    return _round({"minute": int(f["clock"] // 60) + 1, "home": m.meta["home_name"], "away": m.meta["away_name"],
                   "home_attack_dir": m.proc.home_attack_dir, **control_share(grid, m.proc.home_attack_dir),
                   "grid_home_control": coarse.tolist()})


def season_context(subject_id: Annotated[str, "Player id or club id"]) -> dict:
    """Season-to-date context before today's matchday: club table position, points and form, or a player's
    appearances, goals, assists, shots, cards and clean sheets."""
    season = hub().season
    if not season:
        return {"note": "no season history loaded"}
    if subject_id in hub().league.clubs:
        row = next((r for r in season["table"] if r["club"] == subject_id), None)
        return {"club": _name(subject_id), **(row or {}), "played_matchdays": season.get("played_matchdays")}
    p = season["players"].get(subject_id, {"apps": 0, "goals": 0, "assists": 0})
    return {"player": _name(subject_id), "season": p, "played_matchdays": season.get("played_matchdays")}


def league_table(top: Annotated[int, "Number of rows"] = 20) -> list[dict]:
    """The league table before today's matchday (position, played, points, goal difference, form)."""
    season = hub().season
    rows = season.get("table", [])[:top]
    return [{k: r[k] for k in ("pos", "name", "club", "p", "w", "d", "l", "gd", "pts", "form")} for r in rows]


def fantasy_points(match_id: Annotated[str | None, "Match id, or null for every live match"] = None,
                   player_ids: Annotated[list[str] | None, "Only these players"] = None) -> list[dict]:
    """Live fantasy points (confirmed + provisional clean sheets and projected bonus) with itemised reasons,
    sorted by points. Use for 'how is my fantasy team doing?' questions."""
    out = []
    matches = [hub().match(match_id)] if match_id else list(hub().matches.values())
    for m in matches:
        for pid, f in m.proc.snapshot()["fantasy"].items():
            if player_ids and pid not in player_ids:
                continue
            out.append({"player_id": pid, "name": _name(pid), "match_id": m.match_id, "points": f["points"],
                        "minutes": f["minutes"], "breakdown": [(b["reason"], b["points"]) for b in f["breakdown"]]})
    return sorted(out, key=lambda r: -r["points"])[:40]


TOOLS = [list_live_matches, get_match_state, get_player_stats, find_player, get_moments, explain_moment, get_events,
         verify_claims, get_pitch_control, season_context, league_table, fantasy_points]
