"""Realism scorecard: compare simulated matches against typical top-flight ranges.

Reference ranges are per match (both teams combined) and reflect widely published
averages for elite European leagues. They are intentionally ranges, not point targets.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass

import numpy as np

from ..league import League, generate_league
from .engine import MatchSim

BENCHMARKS: dict[str, tuple[float, float, str]] = {
    "goals": (2.3, 3.3, "goals per match"),
    "shots": (21, 29, "shots per match"),
    "shots_on_target": (7, 10.5, "shots on target per match"),
    "xg_per_shot": (0.085, 0.13, "average xG per shot"),
    "passes": (780, 1050, "passes per match"),
    "pass_completion": (0.77, 0.87, "pass completion rate"),
    "corners": (8.5, 12, "corners per match"),
    "fouls": (17, 25, "fouls per match"),
    "yellow_cards": (2.8, 4.8, "yellow cards per match"),
    "offsides": (2, 5, "offsides per match"),
    "tackles": (28, 45, "tackles per match"),
    "interceptions": (14, 28, "interceptions per match"),
    "distance_km_outfield": (9.4, 11.8, "km per outfielder (90 min)"),
    "top_speed_kmh": (31, 37, "fastest player speed in match"),
    "ball_in_play_pct": (52, 64, "% of time ball in play"),
}


@dataclass
class MatchSummary:
    stats: dict[str, float]
    seconds: float


def summarize(sim_events: list[dict], frames_sampled: list[dict], sim: MatchSim) -> dict[str, float]:
    from ..models import expected_goals
    from ..pitch import to_team_frame

    c = Counter(e["type"] for e in sim_events)
    passes = [e for e in sim_events if e["type"] in ("pass", "cross")]
    shots = [e for e in sim_events if e["type"] == "shot"]
    xgs = []
    for s in shots:
        x, y = to_team_frame(s["x"], s["y"], s["attack_dir"])
        xgs.append(expected_goals(x, y, header=s["qualifiers"].get("body_part") == "head",
                                  pressure=0.5 if s["under_pressure"] else 0.0,
                                  situation=s["qualifiers"].get("situation", "open_play")).xg)
    played = np.array([(sim.t - sim.on_since[s]) / 5400.0 for s in range(22)])
    outfield = ~sim.is_gk & sim.active
    km = sim.dist_covered[outfield] / 1000 / np.maximum(played[outfield], 0.3)
    speeds = [p[3] for f in frames_sampled for p in f["players"]]
    in_play = sum(1 for f in frames_sampled if f.get("_live"))
    return {
        "goals": c["goal"],
        "shots": len(shots),
        "shots_on_target": sum(1 for s in shots if s["outcome"] in ("goal", "saved")),
        "xg_per_shot": float(np.mean(xgs)) if xgs else 0.0,
        "xg_total": float(np.sum(xgs)),
        "passes": len(passes),
        "pass_completion": sum(1 for p in passes if p["outcome"] == "complete") / max(1, len(passes)),
        "corners": c["corner"],
        "fouls": c["foul"],
        "yellow_cards": sum(1 for e in sim_events if e["type"] == "card" and e["outcome"] == "yellow"),
        "offsides": c["offside"],
        "tackles": c["tackle"],
        "interceptions": c["interception"],
        "distance_km_outfield": float(np.mean(km)),
        "top_speed_kmh": float(max(speeds) * 3.6) if speeds else 0.0,
        "ball_in_play_pct": 100.0 * in_play / max(1, len(frames_sampled)),
        "carries": c["carry"],
        "pressures": c["pressure"],
        "take_ons": c["take_on"],
        "penalties": c["penalty_awarded"],
        "subs": c["substitution"],
    }


def run_match(league: League, home: str, away: str, seed: int, match_id: str = "test") -> tuple[MatchSummary, list[dict], MatchSim]:
    sim = MatchSim(league, home, away, match_id, seed)
    events: list[dict] = []
    sampled: list[dict] = []
    t0 = time.perf_counter()
    for frame, evs in sim.run():
        events.extend(evs)
        if frame["frame"] % 5 == 0:
            frame["_live"] = sim.restart is None
            sampled.append(frame)
    dt = time.perf_counter() - t0
    return MatchSummary(summarize(events, sampled, sim), dt), events, sim


def _scorecard_job(args: tuple[str, str, int, str]) -> MatchSummary:
    home, away, seed, match_id = args
    summary, _, _ = run_match(generate_league(), home, away, seed=seed, match_id=match_id)
    return summary


def scorecard(n_matches: int = 8, seed: int = 1, workers: int = 8) -> dict:
    """Simulate ``n_matches`` random fixtures (in parallel) and compare averages to the benchmarks."""
    from concurrent.futures import ProcessPoolExecutor

    ids = list(generate_league().clubs)
    rng = np.random.default_rng(seed)
    jobs = []
    for i in range(n_matches):
        h, a = rng.choice(ids, 2, replace=False)
        jobs.append((str(h), str(a), seed * 1000 + i, f"rc{i}"))
    with ProcessPoolExecutor(max_workers=min(workers, n_matches)) as ex:
        rows = list(ex.map(_scorecard_job, jobs))
    keys = rows[0].stats.keys()
    means = {k: float(np.mean([r.stats[k] for r in rows])) for k in keys}
    report = {}
    for k, (lo, hi, label) in BENCHMARKS.items():
        v = means[k]
        report[k] = {"value": round(v, 3), "range": [lo, hi], "label": label, "ok": lo <= v <= hi}
    report["_extra"] = {k: round(v, 2) for k, v in means.items() if k not in BENCHMARKS}
    report["_sim_seconds_per_match"] = round(float(np.mean([r.seconds for r in rows])), 2)
    return report


if __name__ == "__main__":
    import json
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    rep = scorecard(n)
    ok = sum(1 for k, v in rep.items() if not k.startswith("_") and v["ok"])
    total = sum(1 for k in rep if not k.startswith("_"))
    for k, v in rep.items():
        if k.startswith("_"):
            continue
        mark = "PASS" if v["ok"] else "FAIL"
        print(f"{mark}  {v['label']:<34} {v['value']:>9}   range {v['range']}")
    print(json.dumps(rep["_extra"]))
    print(f"sim seconds/match: {rep['_sim_seconds_per_match']}   realism: {ok}/{total}")
