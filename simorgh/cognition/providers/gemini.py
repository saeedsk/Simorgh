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
# Output room for thought, on top of the caller's max_tokens (see _complete_sync).
THINKING_RESERVE_TOKENS = 2048


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._model = model
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def available(self) -> bool:
        return bool(self._api_key)

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float | None = None,
    ) -> ProviderResponse:
        prompt = "\n\n".join(m.get("content", "") for m in messages if m.get("content"))
        return await asyncio.to_thread(self._complete_sync, prompt, max_tokens, timeout)

    def _complete_sync(
        self, prompt: str, max_tokens: int = 0, timeout: float | None = None,
    ) -> ProviderResponse:
        if not self._api_key:
            raise ProviderUnavailable("no Gemini API key configured (GEMINI_API_KEY)")
        # Both arguments were accepted and then dropped on the floor: this
        # provider never told the SDK about either one (observer,
        # 2026-09-10). Neither omission is cosmetic. `timeout` is the
        # Router's slice of a shared whole-call deadline, so a hanging SDK
        # call ran until the SDK's own default gave up -- past the deadline
        # every other candidate was being held to, and past the caller's own
        # patience. `max_tokens` is the number the Router's *pre-call* cost
        # estimate is computed from, so the estimate described a ceiling the
        # provider was never actually asked to respect.
        config: dict = {}
        if max_tokens:
            # Gemini's thinking models spend `max_output_tokens` on thought
            # before the answer. Measured 2026-09-19 on gemini-3.8-flash: a
            # one-word reply with a cap of 20 came back empty (17 thought
            # tokens, finish MAX_TOKENS); with 400 it answered after 97. The
            # caller's number is the ANSWER's room, so thought gets its own.
            config["max_output_tokens"] = int(max_tokens) + THINKING_RESERVE_TOKENS
        if timeout:
            config["http_options"] = {"timeout": int(timeout * 1000)}  # the SDK counts in milliseconds
        try:
            client = self._get_client()
            try:
                response = client.models.generate_content(
                    model=self._model, contents=prompt, config=config or None,
                )
            except TypeError:
                # An SDK version (or an injected double) that predates the
                # `config` keyword: an uncapped call beats no call at all,
                # and the Router now enforces its own deadline regardless.
                response = client.models.generate_content(model=self._model, contents=prompt)
        except Exception as exc:  # noqa: BLE001 -- missing SDK, network, API error: all degrade to the next provider
            raise ProviderUnavailable(f"Gemini request failed: {exc!r}") from exc

        usage = getattr(response, "usage_metadata", None)
        input_tokens = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        # Thought tokens are billed as output; leaving them out made the
        # budget under-count every call.
        output_tokens = ((getattr(usage, "candidates_token_count", 0) or 0)
                         + (getattr(usage, "thoughts_token_count", 0) or 0)) if usage else 0
        text = getattr(response, "text", None) or ""
        if not text and _finished_on_max_tokens(response):
            # An empty answer is not an answer: fail over rather than hand
            # the caller "" as if the model had chosen to say nothing.
            raise ProviderUnavailable(
                f"Gemini spent its {config.get('max_output_tokens')} output tokens thinking and returned no text")
        return ProviderResponse(
            text=text, provider=self.name,
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


def _finished_on_max_tokens(response: Any) -> bool:
    for candidate in getattr(response, "candidates", None) or ():
        reason = getattr(candidate, "finish_reason", None)
        if reason is not None and "MAX_TOKENS" in str(getattr(reason, "name", reason)):
            return True
    return False


__all__ = ["GeminiProvider", "DEFAULT_MODEL", "THINKING_RESERVE_TOKENS"]
