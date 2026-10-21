"""Shared matchday controls: open when running locally, read-only on the public demo (PUBLIC_DEMO=1)."""

import pytest
from fastapi.testclient import TestClient

from footballytics.api import app as api


@pytest.fixture
def client():
    speed = api.HUB.speed
    yield TestClient(api.app)  # no `with`: the lifespan (and the live matchday) does not start
    api.HUB.speed = speed


def test_public_demo_refuses_the_shared_controls_and_says_why(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    before = api.HUB.speed
    for path in ("/api/admin/speed?speed=8", "/api/admin/restart?matchday=9&speed=4"):
        r = client.post(path)
        assert r.status_code == 403
        assert "public demo" in r.json()["detail"]
    assert api.HUB.speed == before  # nothing changed for the other viewers
    assert client.get("/api/health").json()["controls_locked"] is True


def test_the_controls_work_when_running_locally(client, monkeypatch):
    monkeypatch.delenv("PUBLIC_DEMO", raising=False)
    r = client.post("/api/admin/speed?speed=8")
    assert r.status_code == 200
    assert r.json()["speed"] == 8 and r.json()["controls_locked"] is False
