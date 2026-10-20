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
from collections import Counter

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
        self.enabled = is_configured() and os.getenv("AGENTS", "1") == "1"
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

    async def on_message(self, msg: dict) -> None:
        if msg["kind"] != "moment" or not self.enabled:
            return
        moment = msg["data"]
        if moment["importance"] < self.min_importance:
            return
        task = asyncio.create_task(self._produce(moment, self.wanted_languages()))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _produce(self, moment: dict, languages: list[str]) -> None:
        assert self.newsroom is not None
        item = to_jsonable(await self.newsroom.process(moment, languages))
        self.broadcast_log.append(item)
        await self.hub.publish({"kind": "broadcast", "match_id": moment["match_id"], "data": item})
        log.info("broadcast %s %s %s in %sms", item["match_id"], item["kind"], item["status"], item["latency_ms"])

    def stats(self) -> dict:
        items = self.broadcast_log
        lat = sorted(i["latency_ms"] for i in items if i["status"] != "template")
        return {
            "enabled": self.enabled, "in_flight": len(self._tasks), "items": len(items),
            "by_status": dict(Counter(i["status"] for i in items)),
            "latency_p50_ms": lat[len(lat) // 2] if lat else None,
            "latency_p95_ms": lat[int(len(lat) * 0.95)] if lat else None,
            "languages": self.wanted_languages(),
        }
