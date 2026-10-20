import asyncio

from footballytics.archiver import to_item
from footballytics.hub import LiveHub, load_season


def test_archiver_routes_messages_to_containers():
    c, item = to_item({"kind": "event", "match_id": "m1", "data": {"event_id": "m1-00001", "type": "pass"}})
    assert c == "events" and item["id"] == "m1-00001" and item["match_id"] == "m1"
    c, item = to_item({"kind": "broadcast", "match_id": "m1", "data": {"item_id": "bi-1"}})
    assert c == "broadcasts" and item["id"] == "bi-1"
    c, item = to_item({"kind": "recap", "match_id": "m1", "data": {"headline": "x"}})
    assert c == "recaps" and item["id"] == "recap-m1"
    c, item = to_item({"kind": "matchday_end", "data": {"matchday": 9, "table": []}})
    assert c == "matchdays" and item["match_id"] == "md9"
    assert to_item({"kind": "frame", "match_id": "m1", "data": {}}) is None


def test_seed_season_is_packaged():
    season = load_season()
    assert len(season["table"]) == 20 and season["players"]


def test_results_fold_into_the_table():
    hub = LiveHub()
    hub.load_matchday(9)
    first = next(iter(hub.matches))
    for mid in list(hub.matches):
        if mid != first:
            del hub.matches[mid]
    m = hub.match(first)
    home = m.meta["home"]
    before = next(r for r in hub.season["table"] if r["club"] == home)["p"]
    asyncio.run(hub.run(realtime=False))
    hub.apply_results()
    row = next(r for r in hub.season["table"] if r["club"] == home)
    assert row["p"] == before + 1
    assert sorted(r["pos"] for r in hub.season["table"]) == list(range(1, 21))
