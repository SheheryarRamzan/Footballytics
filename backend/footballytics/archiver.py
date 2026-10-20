"""Archiver: an event-driven worker (its own Container App) that consumes the match-intelligence
stream from Event Hubs and archives it in Cosmos DB, checkpointing progress in Blob Storage.

The archive powers replays, recaps of past matchdays and analytics (Cosmos DB can be mirrored into
Microsoft Fabric with no code). Because it is decoupled through Event Hubs, the live broadcast never
waits on storage, and the archiver can be scaled, paused or replayed independently.

Run:  python -m footballytics.archiver
Env:  EVENTHUB_NAMESPACE, EVENTHUB_NAME, COSMOS_ENDPOINT, COSMOS_DATABASE,
      CHECKPOINT_BLOB_URL (https://<account>.blob.core.windows.net), CHECKPOINT_CONTAINER, AZURE_CLIENT_ID
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

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

    async def on_batch(partition_context, events) -> None:
        for ev in events:
            try:
                routed = to_item(json.loads(ev.body_as_str()))
                if routed:
                    container, item = routed
                    await asyncio.to_thread(store.upsert, container, item)
                    counts[container] = counts.get(container, 0) + 1
            except Exception:
                log.exception("failed to archive an event")
        if events:
            await partition_context.update_checkpoint(events[-1])
            log.info("partition %s archived %d (totals %s)", partition_context.partition_id, len(events), counts)

    async with consumer:
        await consumer.receive_batch(on_batch, max_batch_size=200, max_wait_time=5, starting_position="-1")


if __name__ == "__main__":
    asyncio.run(main())
