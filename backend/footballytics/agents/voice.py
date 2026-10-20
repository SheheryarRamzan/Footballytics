"""Multilingual voice for audio-description mode (gpt-4o-mini-tts on Foundry, keyless).

Only text the newsroom generated (a broadcast item's rendition) can be voiced, so the endpoint
cannot be abused to synthesise arbitrary speech. Audio is cached per (item, language, kind).
"""

from __future__ import annotations

import os
from collections import OrderedDict
from functools import lru_cache

from ..cloud import credential
from . import clients  # noqa: F401  (loads backend/.env for local development)

LANG_NAMES = {"en": "English", "es": "Spanish", "ar": "Arabic", "ur": "Urdu", "fr": "French", "pt": "Portuguese",
              "hi": "Hindi"}
_cache: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()
CACHE_MAX = 300


@lru_cache(maxsize=1)
def _client():
    from azure.identity.aio import get_bearer_token_provider
    from openai import AsyncAzureOpenAI

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured")
    provider = get_bearer_token_provider(credential(), "https://cognitiveservices.azure.com/.default")
    return AsyncAzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=provider, api_version="2025-04-01-preview")


async def speak(key: tuple[str, str, str], text: str, language: str) -> bytes:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    lang = LANG_NAMES.get(language, "English")
    resp = await _client().audio.speech.create(
        model=os.getenv("MODEL_TTS", "gpt-4o-mini-tts"),
        voice="coral",
        input=text[:1200],
        instructions=(f"Speak in natural, fluent {lang}. You are describing live football for a blind or "
                      "low-vision fan: clear, warm and lively, a little faster than conversation, with "
                      "excitement for goals and big saves. Pronounce player names as written."),
        response_format="mp3",
    )
    audio = resp.content
    _cache[key] = audio
    if len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return audio
