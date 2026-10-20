"""Guard-rail tests for the agent layer (no model calls)."""

import asyncio
import json

import numpy as np
import pytest

from footballytics.agents.audit import numbers_in, unsupported_numbers
from footballytics.agents.newsroom import NewsTask, check_moment_facts, short_label, template_item
from footballytics.hub import LiveHub
from footballytics.intel import tools
from footballytics.jsonutil import dumps, to_jsonable


def test_numbers_are_extracted_with_percentages():
    found = numbers_in("xG 0.31, a 34 m pass at 108.5 km/h; 62% possession")
    assert [(v, pct) for v, pct, _ in found] == [(0.31, False), (34.0, False), (108.5, False), (62.0, True)]


def test_audit_flags_invented_numbers_only():
    evidence = {"facts": {"xg": 0.312, "shot_speed_kmh": 108.4, "possession": 0.62}}
    ok_text = "An xG 0.31 chance, struck at 108 km/h, with 62% possession and two defenders beaten."
    assert unsupported_numbers([ok_text], evidence) == []
    bad = unsupported_numbers(["He has 14 shots and an xG of 0.77."], evidence)
    assert bad == ["0.77", "14"]


def test_moment_fact_claims_are_checked():
    moment = {"moment_id": "m1", "facts": {"xg": 0.25, "shot_speed_kmh": 101.0}}
    task = NewsTask(moment, {"evidence": [{"assessment": {"difficulty": 8.1}}]}, ["en"])
    res = check_moment_facts(task, [
        {"subject_id": "moment", "metric": "xg", "value": 0.25},
        {"subject_id": "moment", "metric": "difficulty", "value": 6.0},
        {"subject_id": "moment", "metric": "made_up", "value": 1.0},
    ])
    assert [r["ok"] for r in res] == [True, False, False]
    json.dumps(res)


def test_numpy_values_become_plain_json():
    msg = {"a": np.float64(1.5), "b": np.bool_(True), "c": [np.int64(3)], "d": np.array([1, 2])}
    assert to_jsonable(msg) == {"a": 1.5, "b": True, "c": [3], "d": [1, 2]}
    assert json.loads(dumps(msg))["b"] is True


def test_short_label_cuts_on_word_boundary():
    assert short_label("Jansen's Long Header Equaliser Stuns Kingsbridge") == "Jansen's Long Header…"
    assert short_label("Short label") == "Short label"


@pytest.fixture(scope="module")
def live_hub():
    hub = LiveHub(season={})
    hub.load_matchday(3)
    tools.bind(hub)
    asyncio.run(hub.run(realtime=False, max_ticks=6000))  # 10 match-minutes for every match
    return hub


def test_verify_claims_against_live_data(live_hub):
    mid = next(iter(live_hub.matches))
    home = live_hub.match(mid).meta["home"]
    passes = live_hub.match(mid).proc.teams[home].passes
    res = tools.verify_claims(mid, [
        {"subject_id": home, "metric": "passes", "value": passes},
        {"subject_id": home, "metric": "passes", "value": passes + 40},
        {"subject_id": home, "metric": "not_a_metric", "value": 1},
    ])
    assert [r["ok"] for r in res] == [True, False, False]
    assert all(isinstance(r["ok"], bool) for r in res)


def test_template_item_needs_no_model(live_hub):
    m = max(live_hub.moment_log, key=lambda m: m.importance).to_dict()
    item = template_item(m, "test")
    assert item["status"] == "template" and item["renditions"]["en"]["fan"]
    json.dumps(to_jsonable(item))


def test_every_tool_returns_json(live_hub):
    mid = next(iter(live_hub.matches))
    pid = next(iter(live_hub.match(mid).proc.players))
    m = live_hub.moment_log[-1]
    for out in (tools.list_live_matches(), tools.get_match_state(mid), tools.get_player_stats(mid, pid),
                tools.find_player("Rovers"), tools.get_moments(limit=5), tools.explain_moment(m.moment_id),
                tools.get_events(mid, limit=5), tools.get_pitch_control(mid), tools.fantasy_points(mid),
                tools.league_table()):
        json.dumps(to_jsonable(out))
