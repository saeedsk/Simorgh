"""Gemini provider (docs/blueprint/subsystems/04-cognition.md section
11): ported from v1 `src/cognition/gemini_provider.py`. The real SDK
client (`google-genai`) is constructed lazily so importing/instantiating
this class never requires the package unless actually called -- absent
if missing, per principle 4.14 (stdlib core, optional adapters)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from simorgh.contracts.protocols import ProviderResponse

from ..api import ProviderUnavailable

DEFAULT_MODEL = "gemini-3.8-flash"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._model = model
        self._client = client

    def available(self) -> bool:
        return bool(self._api_key)

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float | None = None,
    ) -> ProviderResponse:
        prompt = "\n\n".join(m.get("content", "") for m in messages if m.get("content"))
        return await asyncio.to_thread(self._complete_sync, prompt)

    def _complete_sync(self, prompt: str) -> ProviderResponse:
        if not self._api_key:
            raise ProviderUnavailable("no Gemini API key configured (GEMINI_API_KEY)")
        try:
            client = self._get_client()
            response = client.models.generate_content(model=self._model, contents=prompt)
        except Exception as exc:  # noqa: BLE001 -- missing SDK, network, API error: all degrade to the next provider
            raise ProviderUnavailable(f"Gemini request failed: {exc!r}") from exc

        usage = getattr(response, "usage_metadata", None)
        input_tokens = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        output_tokens = (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        return ProviderResponse(
            text=getattr(response, "text", None) or "", provider=self.name,
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=None,
        )

    def _get_client(self) -> Any:
        if self._client is None:
            import logging

            try:
                from google import genai  # optional third-party adapter (principle 4.14)
            except ImportError as exc:
                raise ProviderUnavailable("google-genai is not installed") from exc

            logging.getLogger("google_genai").setLevel(logging.ERROR)
            self._client = genai.Client(api_key=self._api_key)
        return self._client


__all__ = ["GeminiProvider", "DEFAULT_MODEL"]
