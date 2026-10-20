"""LiveHub: runs a whole matchday of concurrent simulations and fans out live intelligence.

Locally everything runs in one asyncio process (simulation + stats engine cost well under
1 ms per frame). In Azure the same message shapes flow through Event Hubs / Web PubSub via
pluggable *sinks*, so the hub is the seam between the local and cloud-native topologies.

Outgoing messages (all JSON-serialisable):
  {"kind": "frame",   "match_id", "data": compact tracking frame}       (downsampled)
  {"kind": "event",   "match_id", "data": public event}
  {"kind": "moment",  "match_id", "data": moment dict}
  {"kind": "fantasy", "match_id", "data": [ledger entries]}
  {"kind": "tick",    "data": [{match_id, minute, clock, score, status}]}  (every few seconds)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from .engine.moments import Moment
from .engine.processor import MatchProcessor
from .league import League, generate_league
from .jsonutil import to_jsonable
from .schema import public_event
from .sim.engine import DT, MatchSim
from .sim.matchday import DATA_DIR, fixtures, match_id_for

log = logging.getLogger("footballytics.hub")
Sink = Callable[[dict], Awaitable[None]]


class LiveMatch:
    def __init__(self, league: League, home: str, away: str, match_id: str, seed: int, matchday: int,
                 season_players: dict | None = None):
        self.sim = MatchSim(league, home, away, match_id, seed)
        self.meta = {**self.sim.meta(), "matchday": matchday}
        self.proc = MatchProcessor(self.meta, league, season_players)
        self.match_id = match_id
        self._run = self.sim.run()
        self.done = False
        self.last_frame: dict | None = None

    @property
    def status(self) -> str:
        if self.done:
            return "FT"
        if self.sim.period == 2 and self.sim.period_t < 1 and self.sim.frame_no > 10:
            return "HT"
        return "LIVE" if self.sim.frame_no else "PRE"

    def step(self) -> tuple[dict | None, list[dict], list[Moment], list]:
        try:
            frame, events = next(self._run)
        except StopIteration:
            self.done = True
            return None, [], [], []
        self.last_frame = frame
        upd = self.proc.ingest_frame(frame)
        moments, fantasy = list(upd.moments), list(upd.fantasy)
        published = []
        for e in events:
            u = self.proc.ingest_event(e)
            moments += u.moments
            fantasy += u.fantasy
            published.append(public_event({k: v for k, v in e.items() if not k.startswith("_")}))
        if self.sim.finished:
            self.done = True
        return frame, published, moments, fantasy

    def summary(self) -> dict:
        return {"match_id": self.match_id, "home": self.meta["home"], "away": self.meta["away"],
                "home_name": self.meta["home_name"], "away_name": self.meta["away_name"],
                "minute": int(self.proc.clock // 60) + 1, "clock": round(self.proc.clock, 1),
                "score": [self.proc.score[self.meta["home"]], self.proc.score[self.meta["away"]]],
                "status": self.status, "period": self.proc.period}


def compact_frame(frame: dict) -> dict:
    """Shrink a tracking frame for the wire: ids + 1-decimal coordinates."""
    return {"t": frame["t"], "c": frame["clock"], "b": [round(v, 1) for v in frame["ball"]],
            "o": frame["ball_owner"], "p": [[p[0], round(p[1], 1), round(p[2], 1), round(p[3] * 3.6, 0)]
                                            for p in frame["players"]]}


class LiveHub:
    def __init__(self, league: League | None = None, season: dict | None = None):
        self.league = league or generate_league()
        self.season = season if season is not None else load_season()
        self.matches: dict[str, LiveMatch] = {}
        self.matchday: int | None = None
        self.moment_log: list[Moment] = []
        self._queues: set[asyncio.Queue] = set()
        self.sinks: list[Sink] = []
        self.speed = 1.0
        self.frame_every = 2
        self.running = False
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------- setup
    def load_matchday(self, matchday: int) -> list[str]:
        self.matchday = matchday
        self.matches.clear()
        self.moment_log.clear()
        players = self.season.get("players", {})
        for i, (h, a) in enumerate(fixtures(self.league)[matchday - 1]):
            mid = match_id_for(matchday, h, a)
            self.matches[mid] = LiveMatch(self.league, h, a, mid, seed=10_000 * matchday + i, matchday=matchday,
                                          season_players=players)
        return list(self.matches)

    # ------------------------------------------------------------- pub/sub
    def subscribe(self, maxsize: int = 5000) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    async def publish(self, msg: dict) -> None:
        if msg["kind"] != "frame":  # frames are built from plain Python types already
            msg = to_jsonable(msg)
        for q in list(self._queues):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(msg)
        for sink in self.sinks:
            try:
                await sink(msg)
            except Exception:  # a failing sink must never stop the live loop
                log.exception("sink failed")

    # ------------------------------------------------------------- live loop
    def start(self, speed: float = 6.0) -> asyncio.Task:
        self.speed = speed
        self._task = asyncio.create_task(self.run(speed))
        return self._task

    async def run(self, speed: float = 6.0, realtime: bool = True, max_ticks: int | None = None) -> None:
        """Advance every live match by one 0.1 s tick per iteration. ``speed`` = sim seconds per wall second."""
        self.running = True
        self.speed = speed
        loop = asyncio.get_running_loop()
        tick = 0
        next_t = loop.time()
        try:
            while self.running and any(not m.done for m in self.matches.values()):
                for m in self.matches.values():
                    if m.done:
                        continue
                    frame, events, moments, fantasy = m.step()
                    if frame is not None and tick % self.frame_every == 0:
                        await self.publish({"kind": "frame", "match_id": m.match_id, "data": compact_frame(frame)})
                    for e in events:
                        await self.publish({"kind": "event", "match_id": m.match_id, "data": e})
                    for mo in moments:
                        self.moment_log.append(mo)
                        await self.publish({"kind": "moment", "match_id": m.match_id, "data": mo.to_dict()})
                    if fantasy:
                        await self.publish({"kind": "fantasy", "match_id": m.match_id,
                                            "data": [f.to_dict() for f in fantasy]})
                if tick % 50 == 0:
                    await self.publish({"kind": "tick", "data": [m.summary() for m in self.matches.values()]})
                tick += 1
                if max_ticks is not None and tick >= max_ticks:
                    break
                if realtime:
                    next_t += DT / self.speed
                    await asyncio.sleep(max(0.0, next_t - loop.time()))
                elif tick % 200 == 0:
                    await asyncio.sleep(0)
            await self.publish({"kind": "tick", "data": [m.summary() for m in self.matches.values()]})
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False

    # ------------------------------------------------------------- queries
    def match(self, match_id: str) -> LiveMatch:
        if match_id not in self.matches:
            raise KeyError(f"unknown match_id {match_id!r}; live matches: {sorted(self.matches)}")
        return self.matches[match_id]

    def moment(self, moment_id: str) -> Moment:
        for m in reversed(self.moment_log):
            if m.moment_id == moment_id:
                return m
        raise KeyError(f"unknown moment_id {moment_id!r}")


def load_season(path: Path | None = None) -> dict:
    path = path or DATA_DIR / "season" / "season.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}
