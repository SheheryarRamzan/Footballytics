"""Moments: the unit of "something worth surfacing", with evidence and instant captions.

A moment is produced deterministically by the stats engine within milliseconds. It carries
* ``facts``    - the numbers that matter (xG, speed, difficulty ...)
* ``why``      - factual reasons derived from metric factors (no LLM involved)
* ``evidence`` - event ids so any claim can be verified
* ``caption``  - instant template captions per depth (fan / analyst / kids)
* ``overlay``  - a timed, machine-readable overlay cue for the render layer

LLM agents later *upgrade* the caption (richer, personalised, multilingual), but the
template version means something is always on screen with zero model latency.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field

BASE_IMPORTANCE = {
    "goal": 100, "penalty_awarded": 85, "red_card": 85, "big_chance": 68, "great_save": 62,
    "wonder_strike": 100, "momentum_swing": 55, "control_shift": 48, "pressing_shift": 45, "tempo_shift": 35,
    "high_turnover": 46, "line_breaking_pass": 44, "shot_speed": 38, "sprint_tag": 30, "milestone": 42,
    "yellow_card": 32, "substitution": 22, "half_time": 70, "full_time": 90, "kick_off": 40,
}

OVERLAY_TEMPLATE = {
    "goal": ("goal_card", 12), "wonder_strike": ("goal_card", 12), "big_chance": ("shot_card", 7),
    "great_save": ("shot_card", 7), "line_breaking_pass": ("pass_arc", 6), "sprint_tag": ("player_tag", 5),
    "shot_speed": ("stat_bubble", 5), "high_turnover": ("stat_bubble", 6), "momentum_swing": ("momentum_ribbon", 8),
    "control_shift": ("lower_third", 8), "pressing_shift": ("lower_third", 8), "tempo_shift": ("lower_third", 7),
    "milestone": ("lower_third", 7), "penalty_awarded": ("lower_third", 8), "red_card": ("lower_third", 8),
    "yellow_card": ("player_tag", 5), "substitution": ("lower_third", 6), "half_time": ("full_screen", 15),
    "full_time": ("full_screen", 20), "kick_off": ("lower_third", 6),
}

_ids = itertools.count(1)


@dataclass
class Moment:
    match_id: str
    kind: str
    clock: float
    t: float
    team_id: str | None
    player_ids: list[str]
    facts: dict
    why: list[str]
    evidence: list[str]
    importance: float = 0.0
    caption: dict[str, str] = field(default_factory=dict)
    overlay: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    moment_id: str = ""

    def __post_init__(self) -> None:
        if not self.moment_id:
            self.moment_id = f"{self.match_id}-m{next(_ids):05d}"

    @property
    def minute(self) -> int:
        return int(self.clock // 60) + 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["minute"] = self.minute
        return d


def leverage(score_diff: int, clock: float) -> float:
    """How much a moment matters given the game state: close + late = high."""
    minute = clock / 60
    closeness = 1.0 if abs(score_diff) <= 1 else 0.8 if abs(score_diff) == 2 else 0.6
    lateness = 1.0 + 0.3 * max(0.0, (minute - 60) / 30)
    return closeness * lateness


def finalize(m: Moment, score_diff: int, names: dict[str, str]) -> Moment:
    """Fill importance, template captions and overlay cue."""
    base = BASE_IMPORTANCE.get(m.kind, 30)
    if m.kind in ("goal", "wonder_strike", "full_time", "half_time"):
        m.importance = float(base)
    else:
        m.importance = round(min(99.0, base * leverage(score_diff, m.clock)), 1)
    m.caption = captions(m, names)
    template, duration = OVERLAY_TEMPLATE.get(m.kind, ("lower_third", 6))
    anchor = {"player_id": m.player_ids[0]} if m.player_ids else {}
    m.overlay = {
        "cue_id": f"cue-{m.moment_id}",
        "template": template,
        "in_clock": round(m.clock, 1),
        "out_clock": round(m.clock + duration, 1),
        "priority": m.importance,
        "anchor": anchor,
        "data": m.facts,
    }
    return m


def _n(names: dict[str, str], pid: str | None) -> str:
    return names.get(pid or "", pid or "")


def captions(m: Moment, names: dict[str, str]) -> dict[str, str]:
    f = m.facts
    who = _n(names, m.player_ids[0] if m.player_ids else None)
    team = names.get(m.team_id or "", m.team_id or "")
    k = m.kind
    if k in ("goal", "wonder_strike"):
        xg = f.get("xg", 0)
        lead = "What a strike!" if k == "wonder_strike" else "GOAL!"
        return {
            "fan": f"{lead} {who} scores for {team}. {f.get('score', '')}",
            "analyst": f"{who} {f.get('minute', m.minute)}' | xG {xg:.2f} from {f.get('distance_m', 0):.0f} m, "
                       f"shot {f.get('shot_speed_kmh', 0):.0f} km/h. {f.get('score', '')}",
            "kids": f"{who} kicked the ball into the net! {team} get a goal.",
        }
    if k == "big_chance":
        return {
            "fan": f"Huge chance for {who}! {f.get('outcome_text', '')}",
            "analyst": f"Big chance: xG {f.get('xg', 0):.2f} ({f.get('distance_m', 0):.0f} m). {f.get('outcome_text', '')}",
            "kids": f"{who} nearly scored!",
        }
    if k == "great_save":
        return {
            "fan": f"Brilliant save by {who}!",
            "analyst": f"Save by {who}: shot xG {f.get('xg', 0):.2f} at {f.get('shot_speed_kmh', 0):.0f} km/h.",
            "kids": f"The goalkeeper {who} stopped it!",
        }
    if k == "line_breaking_pass":
        return {
            "fan": f"Superb pass from {who}, it cut through {f.get('defenders_bypassed', 0)} defenders.",
            "analyst": f"Line-breaker: difficulty {f.get('difficulty', 0)}/10, {f.get('length_m', 0):.0f} m, "
                       f"{f.get('defenders_bypassed', 0)} bypassed, xT +{f.get('xt_added', 0):.3f}.",
            "kids": f"{who} passed the ball past lots of players!",
        }
    if k == "sprint_tag":
        return {
            "fan": f"{who} flying at {f.get('speed_kmh', 0):.1f} km/h!",
            "analyst": f"{who}: {f.get('speed_kmh', 0):.1f} km/h top speed, {f.get('distance_km', 0):.1f} km covered, "
                       f"{f.get('sprints', 0)} sprints.",
            "kids": f"Zoom! {who} is running super fast!",
        }
    if k == "shot_speed":
        return {
            "fan": f"Rocket from {who}: {f.get('shot_speed_kmh', 0):.0f} km/h!",
            "analyst": f"Shot speed {f.get('shot_speed_kmh', 0):.0f} km/h (xG {f.get('xg', 0):.2f}).",
            "kids": f"{who} kicked it really hard!",
        }
    if k == "high_turnover":
        return {
            "fan": f"{team} win it back high up the pitch!",
            "analyst": f"High turnover by {who}, {f.get('metres_from_goal', 0):.0f} m from goal.",
            "kids": f"{team} took the ball back near the other goal!",
        }
    if k == "momentum_swing":
        return {
            "fan": f"The momentum is with {team} now.",
            "analyst": f"Momentum swing to {team}: threat share {f.get('threat_share', 0):.0%} over the last 5 min.",
            "kids": f"{team} are on top right now!",
        }
    if k == "control_shift":
        return {
            "fan": f"The game has changed: {f.get('regime_text', '')}",
            "analyst": f"Regime: {f.get('regime', '')} (chaos {f.get('chaos', 0):.2f}, possession "
                       f"{f.get('possession_home', 0):.0%}-{1 - f.get('possession_home', 0):.0%}).",
            "kids": f"{f.get('regime_text', '')}",
        }
    if k == "pressing_shift":
        return {
            "fan": f"{team} are pressing {'much harder' if f.get('direction') == 'up' else 'less'} now.",
            "analyst": f"{team} PPDA {f.get('ppda_before', 0):.1f} -> {f.get('ppda_now', 0):.1f} (10-min window).",
            "kids": f"{team} are chasing the ball {'more' if f.get('direction') == 'up' else 'less'}.",
        }
    if k == "tempo_shift":
        return {
            "fan": f"The tempo has {'picked up' if f.get('direction') == 'up' else 'dropped'}.",
            "analyst": f"Tempo {f.get('tempo_before', 0):.1f} -> {f.get('tempo_now', 0):.1f} passes per in-play minute.",
            "kids": "The game is getting " + ("faster!" if f.get("direction") == "up" else "slower."),
        }
    if k == "milestone":
        return {"fan": f.get("text", ""), "analyst": f.get("text", ""), "kids": f.get("text", "")}
    if k in ("yellow_card", "red_card"):
        colour = "Yellow" if k == "yellow_card" else "Red"
        return {"fan": f"{colour} card for {who}.", "analyst": f"{colour} card: {who} ({team}).",
                "kids": f"The referee showed {who} a {colour.lower()} card."}
    if k == "penalty_awarded":
        return {"fan": f"PENALTY to {team}!", "analyst": f"Penalty to {team} (foul on {who}). Penalty xG 0.76.",
                "kids": f"{team} get a penalty kick!"}
    if k == "substitution":
        return {"fan": f"Change for {team}: {f.get('on_name', '')} on, {f.get('off_name', '')} off.",
                "analyst": f"Sub {team}: {f.get('on_name', '')} for {f.get('off_name', '')}.",
                "kids": f"{f.get('on_name', '')} comes on to play."}
    if k in ("half_time", "full_time"):
        label = "Half-time" if k == "half_time" else "Full-time"
        return {"fan": f"{label}: {f.get('score', '')}",
                "analyst": f"{label}: {f.get('score', '')} | xG {f.get('xg_home', 0):.2f}-{f.get('xg_away', 0):.2f}",
                "kids": f"{label}! {f.get('score', '')}"}
    return {"fan": k, "analyst": k, "kids": k}
