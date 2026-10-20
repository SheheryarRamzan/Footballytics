"""Footballytics API: live hub + REST + WebSocket stream + MCP server (+ the built web app), one ASGI app.

Run locally:  uvicorn footballytics.api.app:app --port 8000
Env:  MATCHDAY (default 9), SPEED sim-seconds per wall-second (default 4), AUTOSTART (default 1),
      AUTOLOOP (default 0: play one matchday; 1: play matchday after matchday forever)
      plus the optional Azure settings documented in footballytics/cloud.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents.service import AgentService
from ..cloud import cosmos_from_env, eventhub_from_env, setup_telemetry
from ..hub import LiveHub
from ..intel import mcp_server, tools
from ..jsonutil import dumps, to_jsonable
from ..personal import taste
from ..personal.profiles import ProfileStore
from ..personal.session import ViewerSession

log = logging.getLogger("footballytics.api")
TELEMETRY = setup_telemetry()
HUB = LiveHub()
MCP = mcp_server.build()
AGENTS = AgentService(HUB)
COSMOS = cosmos_from_env()
FANS = ProfileStore(HUB.league, COSMOS)
SESSIONS: set[ViewerSession] = set()
AGENTS.viewers = lambda: len(SESSIONS)
EVENTHUB = None
WEB_DIST = Path(os.getenv("WEB_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global EVENTHUB
    tools.bind(HUB)
    EVENTHUB = eventhub_from_env()
    if EVENTHUB is not None:
        HUB.sinks.append(EVENTHUB)
    HUB.load_matchday(int(os.getenv("MATCHDAY", "9")))
    speed = float(os.getenv("SPEED", "4"))
    if os.getenv("AUTOSTART", "1") == "1":
        if os.getenv("AUTOLOOP", "0") == "1":
            HUB.start_loop(speed=speed, gap_s=float(os.getenv("MATCHDAY_GAP_S", "45")))
        else:
            HUB.start(speed=speed)
    async with MCP.session_manager.run():
        yield
    HUB.stop()


app = FastAPI(title="Footballytics", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/mcp-server", MCP.streamable_http_app())  # MCP endpoint: /mcp-server/mcp


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


# ----------------------------------------------------------------------------- live data
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "matchday": HUB.matchday, "running": HUB.running, "looping": HUB.looping, "speed": HUB.speed,
            "matches": len(HUB.matches), "moments": len(HUB.moment_log), "viewers": len(SESSIONS),
            "agents": AGENTS.stats(),
            "cloud": {"telemetry": TELEMETRY, "cosmos": COSMOS is not None,
                      "eventhub": EVENTHUB.stats() if EVENTHUB is not None else None}}


@app.get("/api/recaps")
def recaps() -> list[dict]:
    return list(AGENTS.recaps.values())


@app.get("/api/recaps/{match_id}")
def recap(match_id: str) -> dict:
    if match_id in AGENTS.recaps:
        return AGENTS.recaps[match_id]
    if COSMOS is not None:
        item = COSMOS.read("recaps", f"recap-{match_id}", match_id)
        if item:
            return {k: v for k, v in item.items() if not k.startswith("_")}
    raise HTTPException(404, "no recap for this match yet")


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
    return to_jsonable({**m.meta, **m.proc.snapshot(players=True), "field_tilt": m.proc.field_tilt()})


@app.get("/api/matches/{match_id}/players/{player_id}")
def player(match_id: str, player_id: str) -> dict:
    return to_jsonable(_call(tools.get_player_stats, match_id, player_id))


@app.get("/api/matches/{match_id}/pitch-control")
def pitch_control(match_id: str, full: bool = False) -> dict:
    out = _call(tools.get_pitch_control, match_id)
    if full:  # full-resolution grid for the analyst heatmap (rows = y bottom->top, cols = x left->right)
        import numpy as np

        from ..engine.metrics import pitch_control as pc

        m = HUB.match(match_id)
        f, team_of = m.last_frame, m.proc.team_of
        hxy = np.array([(p[1], p[2]) for p in f["players"] if team_of.get(p[0]) == m.meta["home"]])
        axy = np.array([(p[1], p[2]) for p in f["players"] if team_of.get(p[0]) == m.meta["away"]])
        out["grid_full"] = np.round(pc(hxy, axy, nx=30, ny=20), 3).tolist()
    return to_jsonable(out)


@app.get("/api/moments")
def moments(match_id: str | None = None, since_minute: int = 0, limit: int = Query(50, le=500)) -> list[dict]:
    res = []
    for m in reversed(HUB.moment_log):
        if (match_id and m.match_id != match_id) or m.minute < since_minute:
            continue
        res.append(m.to_dict())
        if len(res) >= limit:
            break
    return to_jsonable(res)


@app.get("/api/moments/{moment_id}/explain")
def explain(moment_id: str) -> dict:
    return to_jsonable(_call(tools.explain_moment, moment_id))


@app.get("/api/broadcast")
def broadcast(match_id: str | None = None, limit: int = Query(30, le=300)) -> list[dict]:
    items = [i for i in reversed(AGENTS.broadcast_log) if not match_id or i["match_id"] == match_id]
    return items[:limit]


@app.get("/api/tts")
async def tts(moment_id: str, lang: str = "en", kind: str = "audio"):
    """Voice a broadcast item's rendition (audio description by default) with gpt-4o-mini-tts.
    Only newsroom-generated text can be voiced; the result is cached."""
    from fastapi.responses import Response

    from ..agents.voice import speak

    if not AGENTS.enabled:
        raise HTTPException(503, "agents are not configured")
    item = next((i for i in reversed(AGENTS.broadcast_log) if i["moment_id"] == moment_id), None)
    if item is None:
        raise HTTPException(404, "unknown broadcast item")
    rend = item["renditions"].get(lang) or item["renditions"].get("en")
    if not rend or kind not in ("audio", "fan", "kids", "analyst"):
        raise HTTPException(404, "no rendition for this language")
    used_lang = lang if lang in item["renditions"] else "en"
    try:
        audio = await speak((moment_id, used_lang, kind), rend[kind], used_lang)
    except Exception as exc:
        log.exception("tts failed")
        raise HTTPException(502, f"voice unavailable: {type(exc).__name__}") from exc
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=3600",
                                                                       "X-Voice-Language": used_lang})


@app.get("/api/fantasy")
def fantasy(player_ids: str | None = None) -> list[dict]:
    ids = player_ids.split(",") if player_ids else None
    return to_jsonable(tools.fantasy_points(None, ids))


# ----------------------------------------------------------------------------- fans
class FanIn(BaseModel):
    favorite_club: str = "RIV"
    mode: str = "fan"
    language: str = "en"
    display_name: str = "Fan"
    squad: list[str] | None = None
    captain: str | None = None


class FanPatch(BaseModel):
    mode: str | None = None
    language: str | None = None
    favorite_club: str | None = None
    captain: str | None = None
    focus_player: str | None = None
    display_name: str | None = None


class Feedback(BaseModel):
    signal: str  # skip | replay | like | dwell | ask
    kind: str
    moment_id: str | None = None


def _fan_view(fan) -> dict:
    lg = HUB.league
    squad = []
    for pid in fan.squad:
        p = lg.players[pid]
        squad.append({"player_id": pid, "name": p.name, "short_name": p.short_name, "club": p.club_id,
                      "club_name": lg.clubs[p.club_id].name, "group": p.group, "role": p.role, "number": p.number,
                      "price": p.price, "captain": pid == fan.captain, "vice_captain": pid == fan.vice_captain})
    return {**fan.to_dict(), "squad_detail": squad, "taste": taste.explain(fan)}


@app.post("/api/fans")
def create_fan(body: FanIn) -> dict:
    if body.favorite_club not in HUB.league.clubs:
        raise HTTPException(404, f"unknown club {body.favorite_club}")
    fan = _call(FANS.create, body.favorite_club, body.mode, body.language, body.display_name, body.squad, body.captain)
    return _fan_view(fan)


@app.get("/api/fans/{fan_id}")
def get_fan(fan_id: str) -> dict:
    return _fan_view(_call(FANS.get, fan_id))


@app.patch("/api/fans/{fan_id}")
def patch_fan(fan_id: str, body: FanPatch) -> dict:
    fan = _call(FANS.update, fan_id, **body.model_dump(exclude_none=True))
    for s in SESSIONS:
        if s.fan is fan:
            s.refresh_profile()
    return _fan_view(fan)


@app.post("/api/fans/{fan_id}/feedback")
def feedback(fan_id: str, body: Feedback) -> dict:
    fan = _call(FANS.get, fan_id)
    result = taste.record(fan, body.signal, body.kind, body.moment_id)
    FANS.save(fan)
    return {**result, "taste": taste.explain(fan)}


@app.post("/api/fans/{fan_id}/rundown")
async def fan_rundown(fan_id: str) -> dict:
    fan = _call(FANS.get, fan_id)
    if not AGENTS.enabled:
        raise HTTPException(503, "agents are not configured")
    from ..personal.rundown import rundown

    return to_jsonable(await rundown(fan, HUB))


class Question(BaseModel):
    question: str
    fan_id: str | None = None
    match_id: str | None = None
    language: str | None = None
    mode: str | None = None


@app.post("/api/ask")
async def ask(body: Question) -> dict:
    if not AGENTS.enabled:
        raise HTTPException(503, "agents are not configured")
    from ..agents.pundit import ask as pundit_ask

    fan = FANS.get(body.fan_id) if body.fan_id else None
    lang = body.language or (fan.language if fan else "en")
    mode = body.mode or (fan.mode if fan else "fan")
    return to_jsonable(await pundit_ask(body.question[:500], lang, mode, body.match_id, fan.squad if fan else None,
                                       fan.captain if fan else None))


# ----------------------------------------------------------------------------- admin
@app.post("/api/admin/restart")
async def restart(matchday: int = 9, speed: float = 4.0) -> dict:
    HUB.stop()
    await asyncio.sleep(0.3)
    HUB.load_matchday(matchday)
    await HUB.publish({"kind": "matchday", "data": {"matchday": HUB.matchday, "speed": speed,
                                                     "matches": tools.list_live_matches()}})
    if os.getenv("AUTOLOOP", "0") == "1":
        HUB.start_loop(speed=speed, gap_s=float(os.getenv("MATCHDAY_GAP_S", "45")))
    else:
        HUB.start(speed=speed)
    return health()


@app.post("/api/admin/speed")
def set_speed(speed: float = Query(..., gt=0, le=60)) -> dict:
    HUB.speed = speed
    return health()


# ----------------------------------------------------------------------------- stream
@app.websocket("/ws")
async def stream(ws: WebSocket) -> None:
    """Live stream; see personal/session.py for the client protocol."""
    await ws.accept()
    q = HUB.subscribe()
    session = ViewerSession(HUB, FANS, AGENTS)
    SESSIONS.add(session)
    send_lock = asyncio.Lock()

    async def send(msg: dict) -> None:
        try:
            text = dumps(msg)
        except (TypeError, ValueError):
            log.exception("unserialisable %s message skipped", msg.get("kind"))
            return
        async with send_lock:
            await ws.send_text(text)

    async def reader() -> None:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                continue
            try:
                for out in session.on_client(msg):
                    await send(out)
            except KeyError as exc:
                await send({"kind": "error", "data": {"message": str(exc)}})

    task = asyncio.create_task(reader())
    try:
        await send({"kind": "hello", "data": {"matchday": HUB.matchday, "speed": HUB.speed,
                                              "matches": tools.list_live_matches()}})
        while True:
            msg = await q.get()
            for out in session.on_hub(msg):
                await send(out)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        task.cancel()
        with contextlib.suppress(Exception):
            await task
        session.close()
        SESSIONS.discard(session)
        HUB.unsubscribe(q)


# ----------------------------------------------------------------------------- web app
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        target = WEB_DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")
