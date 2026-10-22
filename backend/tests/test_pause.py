"""PAUSE_WHEN_IDLE: the live matchday stops (no simulation, stream, archive writes or model calls) while
nobody is watching, and picks up where it stopped as soon as a viewer or a request arrives."""

import asyncio

from fastapi.testclient import TestClient

from footballytics.api import app as api
from footballytics.hub import LiveHub


def _one_match_hub() -> LiveHub:
    hub = LiveHub()
    hub.load_matchday(9)
    first = next(iter(hub.matches))
    for mid in list(hub.matches):
        if mid != first:
            del hub.matches[mid]
    return hub


def test_the_matchday_pauses_without_an_audience_and_resumes_where_it_stopped():
    async def scenario():
        hub = _one_match_hub()
        m = next(iter(hub.matches.values()))
        hub.idle_after = 0.2
        hub.touch()
        task = asyncio.create_task(hub.run(speed=100))
        await asyncio.sleep(0.5)
        assert hub.paused
        frozen = m.summary()["clock"]
        await asyncio.sleep(0.3)
        assert m.summary()["clock"] == frozen  # nothing is simulated while paused

        hub.touch()  # a viewer arrives
        await asyncio.sleep(0.1)
        assert not hub.paused and m.summary()["clock"] > frozen
        assert m.summary()["clock"] - frozen < 25  # it resumes, it does not catch up on the time it was paused

        hub.audience = lambda: 1  # someone is connected: never pause, however long since the last request
        await asyncio.sleep(0.4)
        assert not hub.paused
        hub.stop()
        await asyncio.wait_for(task, 1)

    asyncio.run(scenario())


def test_a_hub_without_idle_pause_never_pauses():
    hub = _one_match_hub()
    assert hub.idle_after is None and not hub.idle()
    asyncio.run(hub.run(realtime=False, max_ticks=50))
    assert not hub.paused


def test_api_and_mcp_requests_count_as_an_audience_but_health_probes_do_not():
    client = TestClient(api.app, raise_server_exceptions=False)  # no `with`: the live matchday does not start
    api.HUB._last_seen = 0.0
    assert "paused" in client.get("/api/health").json()
    assert api.HUB._last_seen == 0.0
    for path in ("/api/matches", "/mcp-server/mcp"):
        api.HUB._last_seen = 0.0
        client.get(path)
        assert api.HUB._last_seen > 0.0, path
