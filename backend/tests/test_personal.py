import time

import pytest

from footballytics.hub import LiveHub
from footballytics.league import generate_league
from footballytics.personal import taste
from footballytics.personal.director import PersonalDirector
from footballytics.personal.profiles import MODE_WEIGHTS, ProfileStore, auto_squad, validate_squad
from footballytics.personal.session import ViewerSession


@pytest.fixture(scope="module")
def league():
    return generate_league()


def test_auto_squads_are_valid_and_varied(league):
    captains = set()
    for i, club in enumerate(league.clubs):
        squad, captain, vice = auto_squad(league, club, seed=i)
        assert validate_squad(league, squad) == []
        assert captain in squad and vice in squad and captain != vice
        captains.add(captain)
    assert len(captains) > 5


def _moment(match_id, kind, importance, players, team=None):
    return {"moment_id": f"{match_id}-{kind}-{importance}", "match_id": match_id, "kind": kind, "importance": importance,
            "player_ids": players, "team_id": team, "minute": 30, "facts": {"score": "1-0", "xg": 0.3},
            "caption": {"fan": "caption", "analyst": "a", "kids": "k"}}


def test_director_cuts_for_squad_and_respects_budget(league):
    store = ProfileStore(league)
    fan = store.create(favorite_club="KGA")
    other_club = next(c for c in league.clubs if c != "KGA" and c != league.players[fan.captain].club_id)
    captain_club = league.players[fan.captain].club_id
    matches = {"home": {"home": "KGA", "away": "ZZZ"}, "cap": {"home": captain_club, "away": "YYY"},
               "other": {"home": other_club, "away": "XXX"}}
    d = PersonalDirector(fan, league, "home", matches)
    now = time.time()
    # captain scores elsewhere -> cut
    out = d.on_moment(_moment("cap", "goal", 100, [fan.captain]), now)
    assert out[0].action == "cut" and "captain" in " ".join(out[0].reasons)
    # an unrelated low-importance moment -> nothing
    assert d.on_moment(_moment("other", "tempo_shift", 30, []), now + 1) == []
    # an unrelated big chance soon after the cut -> no second cut (interruption budget)
    out = d.on_moment(_moment("other", "big_chance", 90, []), now + 2)
    assert all(x.action != "cut" for x in out)
    # after the hold, the director returns home
    back = d.on_tick(now + 60)
    assert back and back[0].action == "return" and d.stage == "home"


def test_fantasy_points_are_personal_and_captain_doubles(league):
    store = ProfileStore(league)
    fan = store.create(favorite_club="RIV")
    d = PersonalDirector(fan, league, None, {})
    out = d.on_fantasy("m", [{"player_id": fan.captain, "points": 3, "reason": "assist", "event_id": "e1"},
                             {"player_id": "NOT-IN-SQUAD", "points": 4, "reason": "goal"}])
    assert len(out) == 1 and out[0].data["points"] == 6 and "captain x2" in out[0].line


def test_taste_learner_adapts_and_explains(league):
    fan = ProfileStore(league).create(favorite_club="RIV")
    base = fan.weights["momentum_swing"]
    for _ in range(3):
        res = taste.record(fan, "skip", "momentum_swing")
    assert fan.weights["momentum_swing"] < base and res["message"].startswith("Got it")
    assert "momentum swings" in taste.explain(fan)["summary"]
    store = ProfileStore(league)
    store._fans[fan.fan_id] = fan
    store.update(fan.fan_id, mode="analyst")
    assert fan.weights["momentum_swing"] < MODE_WEIGHTS["analyst"]["momentum_swing"]


def test_viewer_session_routes_frames_to_the_stage(league):
    hub = LiveHub(league=league, season={})
    hub.load_matchday(2)
    store = ProfileStore(league)
    fan = store.create(favorite_club="NGU")
    s = ViewerSession(hub, store)
    hello = s.on_client({"fan_id": fan.fan_id})
    assert hello[0]["data"]["action"] == "stage" and "NGU" in s.focus
    other = next(mid for mid in hub.matches if mid != s.focus)
    assert s.on_hub({"kind": "frame", "match_id": other, "data": {}}) == []
    assert s.on_hub({"kind": "frame", "match_id": s.focus, "data": {}})
    item = {"kind": "broadcast", "match_id": other, "data": {"renditions": {"en": {}, "es": {}, "ur": {}}}}
    assert set(s.on_hub(item)[0]["data"]["renditions"]) == {"en"}
