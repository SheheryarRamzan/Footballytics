import asyncio
from collections import deque

from footballytics.archiver import MinuteBatcher, minute_doc, minute_key, safe_checkpoint, to_item
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


def _ev(n, period, clock):
    return {"event_id": f"m1-{n:05d}", "seq": n, "period": period, "clock": clock, "type": "pass"}


def test_events_are_archived_one_document_per_match_minute():
    b = MinuteBatcher(max_age_s=30)
    assert b.add("m1", _ev(1, 1, 5), now=0) == []
    assert b.add("m1", _ev(2, 1, 50), now=1) == []
    assert b.add("m2", {**_ev(3, 1, 10), "event_id": "m2-00003"}, now=1) == []  # another match: its own minute
    closed = b.add("m1", _ev(4, 1, 61), now=2)  # m1 moves to minute 2: minute 1 is written, once
    assert [(k, [e["seq"] for e in evs]) for k, evs in closed] == [(("m1", 1, 1), [1, 2])]
    assert set(b.open) == {("m1", 1, 2), ("m2", 1, 1)}
    # first-half stoppage time and the start of the second half share a minute number, not a document
    assert minute_key("m1", _ev(5, 1, 2760)) != minute_key("m1", _ev(6, 2, 2760))
    # a minute with no new event for max_age_s is written too (full time, or the live loop paused)
    assert sorted(k for k, _ in b.due(now=40)) == [("m1", 1, 2), ("m2", 1, 1)] and b.open == {}


def test_minute_documents_merge_parts_without_duplicates():
    doc = minute_doc(("m1", 2, 47), [_ev(3, 2, 2770), _ev(1, 2, 2761), _ev(3, 2, 2770)])
    assert doc["id"] == "m1-p2-min047" and doc["match_id"] == "m1"
    assert [e["seq"] for e in doc["events"]] == [1, 3] and doc["count"] == 2


def test_checkpoint_never_passes_an_unwritten_minute():
    b = MinuteBatcher()
    backlog = deque([("e1", ("m1", 1, 1)), ("e2", None), ("e3", ("m2", 1, 4)), ("e4", ("m1", 1, 1))])
    b.open = {("m2", 1, 4): []}  # m1 minute 1 written, m2 minute 4 still open
    assert safe_checkpoint(backlog, b.open) == "e2" and len(backlog) == 2
    b.open = {}
    assert safe_checkpoint(backlog, b.open) == "e4" and not backlog


def test_a_failed_minute_write_is_kept_for_the_next_attempt():
    b = MinuteBatcher(max_age_s=30)
    b.add("m1", _ev(1, 1, 5), now=0)
    (key, evs), = b.due(now=31)
    b.add("m1", _ev(2, 1, 6), now=32)  # arrived while the write was failing
    b.reopen(key, evs, now=32)
    (key, evs), = b.due(now=70)
    assert [e["seq"] for e in evs] == [1, 2]
