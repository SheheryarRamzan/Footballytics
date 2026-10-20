import itertools
from collections import Counter

import pytest

from footballytics.league import generate_league, pick_lineup
from footballytics.models import expected_goals, expected_threat
from footballytics.pitch import PITCH_LENGTH, PITCH_WIDTH
from footballytics.schema import Event, TrackingFrame, public_event
from footballytics.sim.engine import MatchSim
from footballytics.sim.matchday import fixtures


@pytest.fixture(scope="module")
def league():
    return generate_league()


@pytest.fixture(scope="module")
def first_20_minutes(league):
    sim = MatchSim(league, "RIV", "KGA", "t1", seed=42)
    frames, events = [], []
    for frame, evs in itertools.islice(sim.run(), 12_000):
        frames.append(frame)
        events.extend(evs)
    return sim, frames, events


def test_league_is_deterministic_and_complete(league):
    again = generate_league()
    assert len(league.clubs) == 20
    assert [p.name for p in league.players.values()] == [p.name for p in again.players.values()]
    for club in league.clubs.values():
        starters, subs = pick_lineup(club)
        assert len(starters) == 11 and len({p.id for p in starters}) == 11
        assert sum(p.role == "GK" for p in starters) == 1
        assert subs[0].role == "GK"


def test_fixtures_double_round_robin(league):
    rounds = fixtures(league)
    assert len(rounds) == 38
    for rnd in rounds:
        clubs = [c for pair in rnd for c in pair]
        assert len(clubs) == 20 and len(set(clubs)) == 20
    pairs = Counter(pair for rnd in rounds for pair in rnd)
    assert all(n == 1 for n in pairs.values()) and len(pairs) == 380


def test_models_behave():
    near = expected_goals(99, 34).xg
    far = expected_goals(80, 34).xg
    wide = expected_goals(99, 10).xg
    assert near > far and near > wide
    assert expected_goals(99, 34, header=True).xg < near
    assert expected_goals(94, 34, situation="penalty").xg == pytest.approx(0.76)
    assert expected_threat(98, 34) > expected_threat(70, 34) > expected_threat(20, 34)


def test_events_validate_and_are_ordered(first_20_minutes):
    _, _, events = first_20_minutes
    assert events[0]["type"] == "match_start"
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    for e in events:
        Event.model_validate(public_event(e))
        for key in ("x", "end_x"):
            if e[key] is not None:
                assert -2 <= e[key] <= PITCH_LENGTH + 2
        for key in ("y", "end_y"):
            if e[key] is not None:
                assert -2 <= e[key] <= PITCH_WIDTH + 2
    kinds = Counter(e["type"] for e in events)
    assert kinds["pass"] > 100 and kinds["pressure"] > 20


def test_tracking_is_physical(first_20_minutes):
    _, frames, _ = first_20_minutes
    for f in frames[::50]:
        TrackingFrame.model_validate(f)
        assert len(f["players"]) <= 22
        assert all(p[3] < 11.0 for p in f["players"])  # nobody runs faster than ~40 km/h
    assert frames[-1]["clock"] > 15 * 60


def test_public_event_strips_ground_truth():
    e = {"qualifiers": {"speed_kmh": 90, "_truth_p_goal": 0.2}}
    assert public_event(e)["qualifiers"] == {"speed_kmh": 90}
