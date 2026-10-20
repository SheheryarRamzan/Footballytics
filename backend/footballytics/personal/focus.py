"""Follow one stat: a viewing option shaped by a single performance metric the fan cares about.

Each metric names the moments that speak to it (the Personal Director boosts those for the fan) and the live
player stat behind its matchday leaderboard (the top players across every concurrent match).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FocusMetric:
    label: str  # reads in a reason: "you follow top speed"
    kinds: tuple[str, ...]  # moment kinds the Director boosts
    stat: str  # PlayerStats.to_dict() key the leaderboard ranks by
    unit: str
    digits: int


FOCUS_METRICS: dict[str, FocusMetric] = {
    "top_speed": FocusMetric("top speed", ("sprint_tag",), "top_speed_kmh", "km/h", 1),
    "shot_speed": FocusMetric("shot speed", ("shot_speed",), "top_shot_speed_kmh", "km/h", 0),
    # completed passes at difficulty 7+/10
    "pass_difficulty": FocusMetric("pass difficulty", ("line_breaking_pass",), "difficult_passes", "", 0),
    "xg": FocusMetric("xG", ("big_chance", "goal", "wonder_strike"), "xg", "", 2),
    # sprint tags are the tracking moments, and they carry the player's distance covered
    "distance": FocusMetric("distance covered", ("sprint_tag",), "distance_km", "km", 2),
    # completed passes past 3+ defenders
    "line_breaking_passes": FocusMetric("line-breaking passes", ("line_breaking_pass",), "line_breaks", "", 0),
}


def leaders(hub, metric: str, top: int = 5) -> dict:
    """The matchday's top players for one metric, across every live match."""
    if metric not in FOCUS_METRICS:
        raise KeyError(f"unknown metric {metric}")
    m = FOCUS_METRICS[metric]
    rows = []
    for match in hub.matches.values():
        for pid, st in match.proc.players.items():
            d = st.to_dict()
            if d[m.stat]:
                rows.append({"player_id": pid, "club": st.team_id, "match_id": match.match_id,
                             "value": round(float(d[m.stat]), m.digits) if m.digits else round(d[m.stat]),
                             "impact": d["impact"]})
    rows.sort(key=lambda r: (-r["value"], -r["impact"]))
    for i, r in enumerate(rows[:top], 1):
        p = hub.league.players.get(r["player_id"])
        r.update(rank=i, name=p.name if p else r["player_id"])
        r.pop("impact")
    return {"metric": metric, "label": m.label, "unit": m.unit, "digits": m.digits, "rows": rows[:top]}
