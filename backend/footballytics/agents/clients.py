"""Foundry model clients with keyless (Entra ID) auth.

Locally the developer's `az login` is used; in Azure the app's managed identity (AZURE_CLIENT_ID).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from agent_framework.foundry import FoundryChatClient
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@lru_cache(maxsize=1)
def credential():
    if os.getenv("AZURE_CLIENT_ID"):
        from azure.identity.aio import ManagedIdentityCredential

        return ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
    from azure.identity.aio import AzureCliCredential

    return AzureCliCredential()


@lru_cache(maxsize=4)
def chat_client(kind: str = "fast") -> FoundryChatClient:
    """``fast`` -> low-latency model for live lines; ``reasoning`` -> analysis and planning."""
    model = os.getenv("MODEL_REASONING", "gpt-5-mini") if kind == "reasoning" else os.getenv("MODEL_FAST", "gpt-4.1-mini")
    return FoundryChatClient(project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], model=model,
                             credential=credential())


def is_configured() -> bool:
    return bool(os.getenv("FOUNDRY_PROJECT_ENDPOINT"))
