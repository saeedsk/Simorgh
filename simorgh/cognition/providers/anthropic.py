"""Anthropic provider: Claude over the Messages API (2026-10-27).

The creator asked for Opus as Sim's default with his own API key
(`SIM_ANTHROPIC_API_KEY`). The Claude Code CLI provider already reached
Opus on his subscription, at the price of starting a CLI for every call
-- several seconds a turn, which a spoken reply cannot afford.

Stdlib only, like the Together provider (the core takes no SDK): one
`POST /v1/messages`, text in, text out -- tools stay in the prompt as
markers (`tool_dialect = "markers"`). The stable part of the prompt is
cached (`cache_control` at the top level caches the longest prefix), so
a conversation pays the full input rate once and $0.20/1M after.

Opus 5.5 thinks on every call (thinking cannot be disabled; effort is the
only control, default `medium`), and its thinking is billed output, so
`max_tokens` is given room to finish thinking (`MIN_MAX_TOKENS`).
A refusal by Anthropic's classifiers falls back server-side to another
model (`fallbacks: "default"`); a refusal that stands is a failure the
Router moves past, never an empty answer.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from simorgh.contracts.protocols import ProviderResponse

from ..api import Capabilities, ProviderUnavailable

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2026-10-21"
#: Server-side refusal fallback, routed by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: Per 1M tokens, Claude Opus 5.5: input, output, cache read, cache write
#: (5-minute writes bill at 1.25x input).
PRICE_IN, PRICE_OUT, PRICE_CACHED_IN, PRICE_CACHE_WRITE = 4.0, 20.0, 0.20, 5.0
#: Thinking is billed output and counts against `max_tokens`: a chat
#: turn's 1,000 would be spent thinking before any answer.
MIN_MAX_TOKENS = 16_000
KEY_NAME = "SIM_ANTHROPIC_API_KEY"
USER_AGENT = "Simorgh/2.0 (+https://github.com/saeedsk/Simorgh)"


class AnthropicProvider:
    capabilities = Capabilities(context_window=1_000_000, cache_prefix=True)

    #: What `/effort` may set (`output_config.effort`).
    EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

    def __init__(
        self, api_key: str | None = None, model: str = DEFAULT_MODEL, *, name: str = "anthropic",
        base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = 180.0, effort: str = "",
        price_in: float = PRICE_IN, price_out: float = PRICE_OUT, price_cached_in: float = PRICE_CACHED_IN,
        transport: Any | None = None,
    ) -> None:
        self.name = name
        # `None`: look in the environment; "" means there is no key.
        self._api_key = os.environ.get(KEY_NAME) if api_key is None else api_key
        self.model = model or DEFAULT_MODEL
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self.effort = effort.strip()
        self._prices = (price_in, price_out, price_cached_in, price_in * 1.25)
        # Test seam: callable(url, headers, body_bytes, timeout) -> str.
        self._transport = transport

    def available(self) -> bool:
        return bool(self._api_key)

    def set_effort(self, effort: str) -> None:
        self.effort = effort.strip()

    def set_model(self, model: str) -> None:
        self.model = model.strip() or DEFAULT_MODEL

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float | None = None,
    ) -> ProviderResponse:
        return await asyncio.to_thread(self._complete_sync, messages, max_tokens, timeout)

    def _complete_sync(self, messages: list[dict], max_tokens: int, timeout: float | None) -> ProviderResponse:
        if not self._api_key:
            raise ProviderUnavailable(f"no Anthropic API key configured ({KEY_NAME})")
        system, turns = to_anthropic_messages(messages)
        body: dict = {"model": self.model, "max_tokens": max(int(max_tokens or 0), MIN_MAX_TOKENS),
                      "messages": turns, "cache_control": {"type": "ephemeral"},
                      "fallbacks": "default"}
        if system:
            body["system"] = system
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        raw = self._post(f"{self._base_url}/v1/messages", body,
                         timeout=timeout if timeout is not None else self._timeout_seconds)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(f"Anthropic returned a non-JSON body: {raw[:200]!r}") from exc
        return self._to_response(data)

    def _post(self, url: str, body: dict, *, timeout: float) -> str:
        payload = json.dumps(body).encode()
        headers = {"x-api-key": self._api_key or "", "anthropic-version": API_VERSION,
                   "anthropic-beta": FALLBACK_BETA, "content-type": "application/json",
                   "user-agent": USER_AGENT}
        started = time.monotonic()
        try:
            if self._transport is not None:
                return self._transport(url, headers, payload, timeout)
            request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed https endpoint
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            # The body names the problem (bad key, unknown model, overloaded).
            detail = exc.read().decode(errors="replace")[:300]
            raise ProviderUnavailable(f"Anthropic HTTP {exc.code}: {detail}") from exc
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 -- network, DNS, TLS, timeout: degrade to the next provider
            raise ProviderUnavailable(f"Anthropic request failed after {time.monotonic() - started:.1f}s "
                                      f"of {timeout:.1f}s: {exc!r}") from exc

    def _to_response(self, data: dict) -> ProviderResponse:
        usage = data.get("usage") or {}
        written = int(usage.get("cache_creation_input_tokens") or 0)
        uncached = int(usage.get("input_tokens") or 0)
        cached = int(usage.get("cache_read_input_tokens") or 0)
        output = int(usage.get("output_tokens") or 0)
        billed = ProviderResponse(
            text="", provider=self.name, input_tokens=uncached + written, output_tokens=output,
            cached_input_tokens=cached, cost_usd=self._bill(uncached, output, cached, written),
            metadata={"model": data.get("model") or self.model})
        text = "".join(str(b.get("text") or "") for b in data.get("content") or []
                       if isinstance(b, dict) and b.get("type") == "text").strip()
        stop = data.get("stop_reason")
        if stop == "refusal":
            category = (data.get("stop_details") or {}).get("category")
            raise ProviderUnavailable(f"Anthropic declined the request (category {category!r})", billable=billed)
        if not text:
            # All thinking and no answer (`max_tokens`), or nothing at all:
            # a failure the Router can move past, not an empty reply.
            raise ProviderUnavailable(f"Anthropic answered with no text (stop_reason={stop!r})",
                                      billable=billed, truncated=stop == "max_tokens")
        return ProviderResponse(text=text, provider=self.name, input_tokens=billed.input_tokens,
                                output_tokens=output, cached_input_tokens=cached, cost_usd=billed.cost_usd,
                                metadata=billed.metadata)

    def _bill(self, uncached: int, output: int, cached: int, written: int) -> float:
        price_in, price_out, price_cached, price_write = self._prices
        return round((uncached * price_in + output * price_out + cached * price_cached
                      + written * price_write) / 1_000_000, 8)


def to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Sim's role/content list as `(system, messages)` for the Messages API:
    system lines joined into the top-level `system`; every other role is
    user or assistant, empty turns dropped, neighbours of one role merged;
    the first turn is the user's, and the last is never Sim's own (a final
    assistant turn is a prefill, which Opus 5.5 refuses)."""
    system = "\n\n".join(str(m.get("content") or "") for m in messages
                         if m.get("role") == "system" and str(m.get("content") or "").strip())
    turns: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            continue
        content = str(m.get("content") or "")
        if not content.strip():
            continue
        role = "assistant" if m.get("role") == "assistant" else "user"
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n\n" + content
        else:
            turns.append({"role": role, "content": content})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": "(continuing)"})
    if turns[-1]["role"] == "assistant":
        turns.append({"role": "user", "content": "Continue."})
    return system, turns


__all__ = ["API_VERSION", "AnthropicProvider", "DEFAULT_MODEL", "KEY_NAME", "MIN_MAX_TOKENS",
           "to_anthropic_messages"]
