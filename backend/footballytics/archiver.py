"""Archiver: an event-driven worker (its own Container App) that consumes the match-intelligence
stream from Event Hubs and archives it in Cosmos DB, checkpointing progress in Blob Storage.

The archive powers replays, recaps of past matchdays and analytics (Cosmos DB can be mirrored into
Microsoft Fabric with no code). Because it is decoupled through Event Hubs, the live broadcast never
waits on storage, and the archiver can be scaled, paused or replayed independently.

Match events are archived as one document per match-minute (about 100 writes per match instead of one
per event); moments, broadcasts, recaps and matchdays are written one document each.

Run:  python -m footballytics.archiver
Env:  EVENTHUB_NAMESPACE, EVENTHUB_NAME, COSMOS_ENDPOINT, COSMOS_DATABASE,
      CHECKPOINT_BLOB_URL (https://<account>.blob.core.windows.net), CHECKPOINT_CONTAINER, AZURE_CLIENT_ID
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque

from .cloud import CosmosStore, credential, setup_telemetry

log = logging.getLogger("footballytics.archiver")

ROUTES = {"event": "events", "moment": "moments", "broadcast": "broadcasts", "recap": "recaps",
          "matchday": "matchdays", "matchday_end": "matchdays"}


def to_item(msg: dict) -> tuple[str, dict] | None:
    kind = msg.get("kind")
    container = ROUTES.get(kind)
    if container is None:
        return None
    data = msg.get("data") or {}
    match_id = msg.get("match_id") or "league"
    if kind == "event":
        item = {**data, "id": data["event_id"]}
    elif kind == "moment":
        item = {**data, "id": data["moment_id"]}
    elif kind == "broadcast":
        item = {**data, "id": data["item_id"]}
    elif kind == "recap":
        item = {**data, "id": f"recap-{match_id}"}
    else:
        item = {**data, "id": f"{kind}-md{data.get('matchday')}", "kind": kind}
    item["match_id"] = match_id if kind not in ("matchday", "matchday_end") else f"md{data.get('matchday')}"
    return container, item


MinuteKey = tuple[str, int, int]  # (match_id, period, minute)


def minute_key(match_id: str, event: dict) -> MinuteKey:
    return match_id, int(event.get("period") or 1), int((event.get("clock") or 0) // 60) + 1


def minute_doc(key: MinuteKey, events: list[dict]) -> dict:
    """One archive document holding every event of a match-minute (deduplicated by event id, in order)."""
    match_id, period, minute = key
    ordered = sorted({e["event_id"]: e for e in events}.values(), key=lambda e: e.get("seq", 0))
    return {"id": f"{match_id}-p{period}-min{minute:03d}", "match_id": match_id, "period": period, "minute": minute,
            "count": len(ordered), "events": ordered}


class MinuteBatcher:
    """Collects each match's events until its minute is over, then hands the minute over to be written once.

    A minute closes when its match moves on to a later minute, or after ``max_age_s`` without a new event
    (full time, or the live loop paused for lack of an audience).
    """

    def __init__(self, max_age_s: float = 30.0):
        self.max_age_s = max_age_s
        self.open: dict[MinuteKey, list[dict]] = {}
        self.updated: dict[MinuteKey, float] = {}

    def add(self, match_id: str, event: dict, now: float) -> list[tuple[MinuteKey, list[dict]]]:
        key = minute_key(match_id, event)
        done = [k for k in self.open if k[0] == match_id and k[1:] < key[1:]]
        self.open.setdefault(key, []).append(event)
        self.updated[key] = now
        return [self._close(k) for k in done]

    def due(self, now: float) -> list[tuple[MinuteKey, list[dict]]]:
        return [self._close(k) for k in list(self.open) if now - self.updated[k] >= self.max_age_s]

    def reopen(self, key: MinuteKey, events: list[dict], now: float) -> None:
        """A write failed: keep the minute (merged with anything that arrived since) for the next attempt."""
        self.open[key] = events + self.open.get(key, [])
        self.updated[key] = now

    def _close(self, key: MinuteKey) -> tuple[MinuteKey, list[dict]]:
        self.updated.pop(key, None)
        return key, self.open.pop(key)


def safe_checkpoint(backlog: deque, open_minutes) -> object | None:
    """Pop the events that are fully archived and return the newest one, the point it is safe to resume after.

    ``backlog`` holds ``(event, minute_key or None)`` in arrival order; an event is archived once its minute
    has been written (or at once, for anything other than a match event).
    """
    safe = None
    while backlog and (backlog[0][1] is None or backlog[0][1] not in open_minutes):
        safe = backlog.popleft()[0]
    return safe


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    setup_telemetry()
    from azure.eventhub.aio import EventHubConsumerClient
    from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore

    cred = credential()
    store = CosmosStore(os.environ["COSMOS_ENDPOINT"], os.getenv("COSMOS_DATABASE", "footballytics"))
    checkpoints = BlobCheckpointStore(os.environ["CHECKPOINT_BLOB_URL"], os.getenv("CHECKPOINT_CONTAINER", "checkpoints"),
                                      credential=cred)
    consumer = EventHubConsumerClient(fully_qualified_namespace=os.environ["EVENTHUB_NAMESPACE"],
                                      eventhub_name=os.environ["EVENTHUB_NAME"], consumer_group="$Default",
                                      credential=cred, checkpoint_store=checkpoints)
    counts: dict[str, int] = {}
    minutes = MinuteBatcher()
    backlog: dict[str, deque] = defaultdict(deque)
    writing: set[MinuteKey] = set()  # closed minutes whose write is in flight: not yet safe to checkpoint past

    async def write_minute(key: MinuteKey, events: list[dict]) -> None:
        doc = minute_doc(key, events)
        # A minute can arrive in parts (a pause mid-minute, or a replay after a restart): merge, never overwrite.
        existing = await asyncio.to_thread(store.read, "events", doc["id"], doc["match_id"])
        if existing:
            doc = minute_doc(key, existing.get("events", []) + events)
        await asyncio.to_thread(store.upsert, "events", doc)
        counts["events"] = counts.get("events", 0) + len(events)
        counts["event_docs"] = counts.get("event_docs", 0) + 1

    async def on_batch(partition_context, events) -> None:
        now = time.monotonic()
        closed: list[tuple[MinuteKey, list[dict]]] = []
        for ev in events:
            key = None
            try:
                msg = json.loads(ev.body_as_str())
                if msg.get("kind") == "event":
                    match_id = msg.get("match_id") or msg["data"]["match_id"]
                    key = minute_key(match_id, msg["data"])
                    closed += minutes.add(match_id, msg["data"], now)
                else:
                    routed = to_item(msg)
                    if routed:
                        container, item = routed
                        await asyncio.to_thread(store.upsert, container, item)
                        counts[container] = counts.get(container, 0) + 1
            except Exception:
                log.exception("failed to archive an event")
            backlog[partition_context.partition_id].append((ev, key))
        closed += minutes.due(now)
        writing.update(key for key, _ in closed)
        for key, evs in closed:
            try:
                await write_minute(key, evs)
            except Exception:
                log.exception("failed to archive minute %s; will retry", key)
                minutes.reopen(key, evs, now)
            finally:
                writing.discard(key)
        safe = safe_checkpoint(backlog[partition_context.partition_id], minutes.open.keys() | writing)
        if safe is not None:
            await partition_context.update_checkpoint(safe)
        if events:
            log.info("partition %s received %d (archived %s)", partition_context.partition_id, len(events), counts)

    async with consumer:
        await consumer.receive_batch(on_batch, max_batch_size=200, max_wait_time=5, starting_position="-1")


if __name__ == "__main__":
    asyncio.run(main())
