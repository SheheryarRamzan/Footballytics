"""AgentService: connects the live hub to the agent newsroom without ever blocking the live loop.

* Listens to hub messages (as a sink). Important moments are scheduled onto the newsroom workflow.
* Verified broadcast items are published back through the hub as {"kind": "broadcast", ...}.
* Languages are the union of what connected viewers asked for (default English).
* If Foundry is unreachable the template captions keep flowing (graceful degradation).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import Counter, OrderedDict
from collections.abc import Callable

from ..hub import LiveHub
from ..jsonutil import to_jsonable
from .clients import is_configured

log = logging.getLogger("footballytics.agents")


class AgentService:
    def __init__(self, hub: LiveHub, min_importance: float | None = None):
        self.hub = hub
        self.min_importance = float(min_importance or os.getenv("NEWSROOM_MIN_IMPORTANCE", "50"))
        self.languages: Counter[str] = Counter()
        self.broadcast_log: list[dict] = []
        # item_id -> the moment, context and claim values the Verifier checked it against (for "try a wrong number")
        self.verified_against: OrderedDict[str, dict] = OrderedDict()
        self.recaps: dict[str, dict] = {}
        self.enabled = is_configured() and os.getenv("AGENTS", "1") == "1"
        # Agents only spend tokens while someone is watching (plus a short grace period).
        self.viewers: Callable[[], int] = lambda: 1
        self.idle_grace_s = float(os.getenv("AGENTS_IDLE_GRACE_S", "180"))
        self._last_viewer = time.time()
        self.skipped_idle = 0
        self._tasks: set[asyncio.Task] = set()
        self.newsroom = None
        if self.enabled:
            from .newsroom import Newsroom

            self.newsroom = Newsroom(min_importance=self.min_importance,
                                     max_concurrency=int(os.getenv("NEWSROOM_CONCURRENCY", "6")))
        hub.sinks.append(self.on_message)

    def wanted_languages(self) -> list[str]:
        langs = [lang for lang, n in self.languages.items() if n > 0]
        return sorted(set(["en"] + langs))[:5]

    def add_viewer_languages(self, langs: list[str]) -> None:
        self.languages.update(langs)

    def remove_viewer_languages(self, langs: list[str]) -> None:
        self.languages.subtract(langs)

    def watching(self) -> bool:
        if self.viewers() > 0:
            self._last_viewer = time.time()
            return True
        return time.time() - self._last_viewer < self.idle_grace_s

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_message(self, msg: dict) -> None:
        if msg["kind"] != "moment" or not self.enabled:
            return
        moment = msg["data"]
        if not self.watching():
            self.skipped_idle += 1
            return
        if moment["kind"] == "full_time":
            self._spawn(self._recap(moment["match_id"]))
        if moment["importance"] < self.min_importance:
            return
        self._spawn(self._produce(moment, self.wanted_languages()))

    async def _recap(self, match_id: str) -> None:
        from .recap import recap

        try:
            r = to_jsonable(await recap(match_id))
        except Exception:
            log.exception("recap failed for %s", match_id)
            return
        self.recaps[match_id] = r
        await self.hub.publish({"kind": "recap", "match_id": match_id, "data": r})

    async def _produce(self, moment: dict, languages: list[str]) -> None:
        assert self.newsroom is not None
        item = to_jsonable(await self.newsroom.process(moment, languages, include_context=True))
        context, item_moment = item.pop("context", None), item.pop("moment", None)
        if context is not None and item["status"] in ("verified", "corrected"):
            self.remember(item, context, item_moment)
        self.broadcast_log.append(item)
        await self.hub.publish({"kind": "broadcast", "match_id": moment["match_id"], "data": item})
        log.info("broadcast %s %s %s in %sms", item["match_id"], item["kind"], item["status"], item["latency_ms"])

    def remember(self, item: dict, context: dict, moment: dict, keep: int = 60) -> None:
        self.verified_against[item["item_id"]] = {"item": item, "context": context, "moment": moment,
                                                  "claims": item["claims"]}
        while len(self.verified_against) > keep:
            self.verified_against.popitem(last=False)

    def stats(self) -> dict:
        items = self.broadcast_log
        lat = sorted(i["latency_ms"] for i in items if i["status"] != "template")
        return {
            "enabled": self.enabled, "in_flight": len(self._tasks), "items": len(items),
            "by_status": dict(Counter(i["status"] for i in items)),
            "latency_p50_ms": lat[len(lat) // 2] if lat else None,
            "latency_p95_ms": lat[int(len(lat) * 0.95)] if lat else None,
            "languages": self.wanted_languages(),
            "recaps": len(self.recaps),
            "watching": self.watching(),
            "skipped_while_idle": self.skipped_idle,
        }
