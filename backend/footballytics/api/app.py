"""Footballytics API: live hub + REST + WebSocket stream + MCP server, in one ASGI app.

Run locally:  uvicorn footballytics.api.app:app --port 8000
Env:  MATCHDAY (default 9), SPEED sim-seconds per wall-second (default 6), AUTOSTART (default 1)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from ..agents.service import AgentService
from ..hub import LiveHub
from ..jsonutil import dumps
from ..intel import mcp_server, tools

log = logging.getLogger("footballytics.api")
HUB = LiveHub()
MCP = mcp_server.build()
AGENTS = AgentService(HUB)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tools.bind(HUB)
    HUB.load_matchday(int(os.getenv("MATCHDAY", "9")))
    if os.getenv("AUTOSTART", "1") == "1":
        HUB.start(speed=float(os.getenv("SPEED", "6")))
    async with MCP.session_manager.run():
        yield
    HUB.stop()


app = FastAPI(title="Footballytics", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/mcp-server", MCP.streamable_http_app())  # MCP endpoint: /mcp-server/mcp


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "matchday": HUB.matchday, "running": HUB.running, "speed": HUB.speed,
            "matches": len(HUB.matches), "moments": len(HUB.moment_log), "agents": AGENTS.stats()}


@app.get("/api/broadcast")
def broadcast(match_id: str | None = None, limit: int = Query(30, le=300)) -> list[dict]:
    items = [i for i in reversed(AGENTS.broadcast_log) if not match_id or i["match_id"] == match_id]
    return items[:limit]


@app.get("/api/league")
def league() -> dict:
    return {"name": HUB.league.name, "clubs": [c.to_dict(with_players=True) for c in HUB.league.clubs.values()]}


@app.get("/api/table")
def table() -> list[dict]:
    return tools.league_table()


@app.get("/api/matches")
def matches() -> list[dict]:
    return tools.list_live_matches()


@app.get("/api/matches/{match_id}")
def match_state(match_id: str) -> dict:
    m = _call(HUB.match, match_id)
    return {**m.meta, **m.proc.snapshot(players=True)}


@app.get("/api/matches/{match_id}/players/{player_id}")
def player(match_id: str, player_id: str) -> dict:
    return _call(tools.get_player_stats, match_id, player_id)


@app.get("/api/matches/{match_id}/pitch-control")
def pitch_control(match_id: str) -> dict:
    return _call(tools.get_pitch_control, match_id)


@app.get("/api/moments")
def moments(match_id: str | None = None, since_minute: int = 0, limit: int = Query(50, le=500)) -> list[dict]:
    res = []
    for m in reversed(HUB.moment_log):
        if (match_id and m.match_id != match_id) or m.minute < since_minute:
            continue
        res.append(m.to_dict())
        if len(res) >= limit:
            break
    return res


@app.get("/api/fantasy")
def fantasy(player_ids: str | None = None) -> list[dict]:
    ids = player_ids.split(",") if player_ids else None
    return tools.fantasy_points(None, ids)


@app.post("/api/admin/restart")
async def restart(matchday: int = 9, speed: float = 6.0) -> dict:
    HUB.stop()
    await asyncio.sleep(0.2)
    HUB.load_matchday(matchday)
    HUB.start(speed=speed)
    return health()


@app.post("/api/admin/speed")
def set_speed(speed: float = Query(..., gt=0, le=60)) -> dict:
    HUB.speed = speed
    return health()


@app.websocket("/ws")
async def stream(ws: WebSocket) -> None:
    """Live stream. Client may send {"focus": match_id} to receive tracking frames for one match
    (all moments, events, fantasy deltas and ticks are always sent)."""
    await ws.accept()
    q = HUB.subscribe()
    focus: dict[str, str | None] = {"match_id": None}
    langs: list[str] = []

    async def reader() -> None:
        nonlocal langs
        while True:
            msg = json.loads(await ws.receive_text())
            if "focus" in msg:
                focus["match_id"] = msg["focus"]
            if "languages" in msg:
                AGENTS.remove_viewer_languages(langs)
                langs = [str(x)[:8] for x in msg["languages"]][:3]
                AGENTS.add_viewer_languages(langs)

    task = asyncio.create_task(reader())
    try:
        await ws.send_text(json.dumps({"kind": "hello", "data": {"matchday": HUB.matchday,
                                                                  "matches": tools.list_live_matches()}}))
        while True:
            msg = await q.get()
            if msg["kind"] in ("frame", "event") and msg["match_id"] != focus["match_id"]:
                continue
            try:
                text = dumps(msg)
            except (TypeError, ValueError):
                log.exception("unserialisable %s message skipped", msg.get("kind"))
                continue
            await ws.send_text(text)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        task.cancel()
        with contextlib.suppress(Exception):
            await task
        AGENTS.remove_viewer_languages(langs)
        HUB.unsubscribe(q)
