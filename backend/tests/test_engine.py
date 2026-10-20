import json
from collections import Counter

import numpy as np
import pytest

from footballytics.engine.fantasy import FantasyLedger
from footballytics.engine.metrics import assess_pass, pitch_control
from footballytics.engine.processor import MatchProcessor
from footballytics.league import generate_league
from footballytics.sim.engine import MatchSim


@pytest.fixture(scope="module")
def processed():
    league = generate_league()
    sim = MatchSim(league, "NGU", "HBC", "e1", seed=7)
    proc = MatchProcessor(sim.meta(), league)
    moments = []
    for frame, events in sim.run():
        moments += proc.ingest_frame(frame).moments
        for e in events:
            moments += proc.ingest_event(e).moments
    return sim, proc, moments


def test_pass_difficulty_rises_with_pressure_and_distance():
    start, end = np.array([40.0, 34.0]), np.array([55.0, 34.0])
    easy = assess_pass(start, end, np.array([[80.0, 10.0]]), lofted=False)
    hard = assess_pass(start, np.array([90.0, 34.0]), np.array([[60.0, 34.5], [89.0, 35.0], [41.0, 34.0]]), lofted=True)
    assert easy.difficulty < hard.difficulty
    assert 1 <= easy.difficulty <= 10 and 1 <= hard.difficulty <= 10
    assert hard.defenders_bypassed >= 1


def test_pitch_control_favours_the_closer_team():
    home = np.array([[30.0, 34.0]])
    away = np.array([[80.0, 34.0]])
    grid = pitch_control(home, away)
    assert grid[7, 2] > 0.9 and grid[7, -3] < 0.1


def test_score_and_stats_match_the_simulation(processed):
    sim, proc, _ = processed
    assert [proc.score[proc.home], proc.score[proc.away]] == sim.score
    snap = proc.snapshot()
    json.dumps(snap)
    h, a = snap["teams"][proc.home], snap["teams"][proc.away]
    assert abs(h["possession"] + a["possession"] - 1) < 1e-6
    assert h["passes"] > 200 and 0.6 < h["pass_completion"] < 0.95
    assert h["goals"] + a["goals"] == sum(sim.score)


def test_moments_are_explainable_and_not_spammy(processed):
    sim, proc, moments = processed
    kinds = Counter(m.kind for m in moments)
    assert kinds["kick_off"] == 1 and kinds["half_time"] == 1 and kinds["full_time"] == 1
    assert kinds["goal"] + kinds["wonder_strike"] == sum(sim.score)
    assert kinds["sprint_tag"] <= 25 and kinds["line_breaking_pass"] <= 16
    for m in moments:
        assert set(m.caption) == {"fan", "analyst", "kids"}
        assert m.overlay["out_clock"] > m.overlay["in_clock"]
        if m.kind in ("goal", "big_chance", "line_breaking_pass"):
            assert m.why and m.evidence


def test_fantasy_points_reconcile_with_events(processed):
    sim, proc, _ = processed
    totals = proc.snapshot()["fantasy"]
    for pid, st in proc.players.items():
        goals = sum(b["points"] for b in totals.get(pid, {}).get("breakdown", []) if b["reason"] == "goal")
        if st.goals:
            assert goals > 0
    assert all(any(b["reason"] == "appearance" for b in t["breakdown"]) for t in totals.values())


def test_fantasy_ledger_goal_and_assist():
    ledger = FantasyLedger({"A": "MID", "B": "FWD", "K": "GK"}, {"A": "X", "B": "X", "K": "Y"})
    for p in ("A", "B", "K"):
        ledger.start(p, 0.0)
    new = ledger.on_event({"type": "goal", "clock": 600.0, "player_id": "B", "event_id": "g1",
                           "qualifiers": {"assist_id": "A"}, "outcome": "goal"})
    reasons = {(e.player_id, e.reason, e.points) for e in new}
    assert ("B", "goal", 4) in reasons and ("A", "assist", 3) in reasons
    assert ledger.players["K"].goals_conceded == 1
