"""Azure integrations. Each one switches on only when its environment variables are present, so the
same code runs locally (in-memory) and in Azure (Event Hubs, Cosmos DB, App Insights).

  EVENTHUB_NAMESPACE  e.g. fbx-eh-xyz.servicebus.windows.net     -> stream intelligence to Event Hubs
  EVENTHUB_NAME       e.g. match-intelligence
  COSMOS_ENDPOINT     e.g. https://fbx-cosmos-xyz.documents.azure.com:443/
  COSMOS_DATABASE     e.g. footballytics                         -> persist fan profiles (+ archive)
  APPLICATIONINSIGHTS_CONNECTION_STRING                          -> OpenTelemetry traces/metrics/logs
  AZURE_CLIENT_ID     user-assigned managed identity used for every Azure call (keyless)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict

from .jsonutil import dumps

log = logging.getLogger("footballytics.cloud")


# ----------------------------------------------------------------------------- identity
def credential(aio: bool = True):
    client_id = os.getenv("AZURE_CLIENT_ID")
    if aio:
        from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential
    else:
        from azure.identity import AzureCliCredential, ManagedIdentityCredential
    return ManagedIdentityCredential(client_id=client_id) if client_id else AzureCliCredential()


# ----------------------------------------------------------------------------- telemetry
def quiet_azure_logs() -> None:
    """The Azure SDK logs every HTTP request at INFO; keep our logs readable."""
    for name in ("azure", "azure.core.pipeline.policies.http_logging_policy", "azure.monitor", "azure.eventhub",
                 "uamqp", "azure.identity"):
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_telemetry() -> bool:
    quiet_azure_logs()
    conn = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn:
        return False
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=conn, logger_name="footballytics")
    from agent_framework.observability import enable_instrumentation

    enable_instrumentation(enable_sensitive_data=False)  # agent/tool spans without prompt contents
    logging.getLogger("footballytics").setLevel(logging.INFO)
    log.info("telemetry enabled")
    return True


# ----------------------------------------------------------------------------- Event Hubs
class EventHubSink:
    """Hub sink: batches intelligence messages and publishes them partitioned by match id.

    Tracking frames are not streamed (volume); everything else is, so downstream services
    (archiver, analytics, Fabric) can rebuild the matchday from the event log.
    """

    KINDS = {"event", "moment", "broadcast", "fantasy", "recap", "matchday", "matchday_end"}

    def __init__(self, namespace: str, name: str, flush_s: float = 1.0):
        from azure.eventhub.aio import EventHubProducerClient

        self.producer = EventHubProducerClient(fully_qualified_namespace=namespace, eventhub_name=name,
                                               credential=credential())
        self.flush_s = flush_s
        self.buffer: dict[str, list[dict]] = defaultdict(list)
        self.sent = 0
        self.failed = 0
        self._task: asyncio.Task | None = None

    async def __call__(self, msg: dict) -> None:
        if msg["kind"] not in self.KINDS:
            return
        self.buffer[msg.get("match_id") or "league"].append(msg)
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        from azure.eventhub import EventData

        while True:
            await asyncio.sleep(self.flush_s)
            pending, self.buffer = self.buffer, defaultdict(list)
            for key, msgs in pending.items():
                try:
                    batch = await self.producer.create_batch(partition_key=key)
                    for m in msgs:
                        ev = EventData(dumps(m))
                        ev.properties = {"kind": m["kind"], "match_id": key}
                        try:
                            batch.add(ev)
                        except ValueError:  # batch full: send and start a new one
                            await self.producer.send_batch(batch)
                            batch = await self.producer.create_batch(partition_key=key)
                            batch.add(ev)
                    await self.producer.send_batch(batch)
                    self.sent += len(msgs)
                except Exception:
                    self.failed += len(msgs)
                    log.exception("event hub publish failed (%d messages dropped)", len(msgs))

    def stats(self) -> dict:
        return {"sent": self.sent, "failed": self.failed}


# ----------------------------------------------------------------------------- Cosmos DB
class CosmosStore:
    """Thin keyless Cosmos DB wrapper (sync client; profile writes are rare)."""

    CONTAINERS = ("fans", "events", "moments", "broadcasts", "recaps", "matchdays")

    def __init__(self, endpoint: str, database: str):
        from azure.cosmos import CosmosClient

        self.client = CosmosClient(endpoint, credential=credential(aio=False))
        self.db = self.client.get_database_client(database)
        self.containers = {name: self.db.get_container_client(name) for name in self.CONTAINERS}

    def upsert(self, container: str, item: dict) -> None:
        self.containers[container].upsert_item(json.loads(dumps(item)))

    def read(self, container: str, item_id: str, partition: str) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self.containers[container].read_item(item_id, partition_key=partition)
        except CosmosResourceNotFoundError:
            return None

    def query(self, container: str, sql: str, params: list[dict] | None = None, partition: str | None = None,
              limit: int = 50) -> list[dict]:
        it = self.containers[container].query_items(sql, parameters=params or [], partition_key=partition,
                                                    enable_cross_partition_query=partition is None)
        out = []
        for row in it:
            out.append({k: v for k, v in row.items() if not k.startswith("_")})
            if len(out) >= limit:
                break
        return out


def cosmos_from_env() -> CosmosStore | None:
    endpoint = os.getenv("COSMOS_ENDPOINT")
    if not endpoint:
        return None
    try:
        return CosmosStore(endpoint, os.getenv("COSMOS_DATABASE", "footballytics"))
    except Exception:
        log.exception("cosmos unavailable; continuing in memory")
        return None


def eventhub_from_env() -> EventHubSink | None:
    ns, name = os.getenv("EVENTHUB_NAMESPACE"), os.getenv("EVENTHUB_NAME")
    if not (ns and name):
        return None
    return EventHubSink(ns, name)
