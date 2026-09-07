"""Together AI provider (docs/blueprint/subsystems/04-cognition.md
section 11), default model `zai-org/GLM-5.3-Flash`.

Talks to the OpenAI-compatible `/v1/chat/completions` endpoint over
stdlib `urllib` rather than the `together` SDK. The SDK is a fine client,
but it would be a hard third-party dependency on the default reasoning
path, and principle 4.14 keeps the core stdlib-only with optional
adapters -- a provider Sim reaches for on every single think call is the
last place to want an import that might not be installed. The request
this builds is byte-for-byte the one in Together's own curl example.

Unlike Gemini's provider this keeps the real message roles instead of
flattening everything into one prompt string: Cognition's assembler puts
the constitution, the persona voice, the self summary and the task rules
in `role: "system"` blocks precisely so a chat-completions provider can
send them as system messages.

Cost is reported by this provider rather than left to the token-times-
price fallback, because Together prices cached input separately
($0.03/1M against $0.15/1M) and the response says how much of the prompt
was cached. `input_tokens` here is the *uncached* remainder, with the
cached part carried in `cached_input_tokens`, so the two never
double-count.

GLM-5.3-Flash is a reasoning model, and its thinking tokens are billed
and counted against `max_tokens` like any other output. Measured live on
2026-09-07: "say hi in five words" spent 204 reasoning tokens before 9
tokens of answer, and at Cognition's `reground` ceiling (512 output
tokens) a call like that returns `finish_reason: "length"` with an empty
`content` -- paid for, and useless. `reasoning_effort` (default "low")
brought the same request down to 4 reasoning tokens with a complete
answer, so it is sent on every call. Raise it per instance for a
provider dedicated to hard drafting work.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from simorgh.contracts.protocols import ProviderResponse

from ..api import ProviderUnavailable

DEFAULT_MODEL = "zai-org/GLM-5.3-Flash"
DEFAULT_BASE_URL = "https://api.together.ai/v1"
DEFAULT_REASONING_EFFORT = "low"
USER_AGENT = "Simorgh/2.0 (+https://github.com/saeedsk/Simorgh)"

# Per 1M tokens (Together's published GLM-5.3-Flash pricing). Mirrored in
# `config.py`'s ProviderConfig so the Router can estimate a call's cost
# *before* making it; kept here too so a response's real usage -- cached
# tokens included -- is priced without a round trip through config.
PRICE_IN = 0.15
PRICE_OUT = 0.50
PRICE_CACHED_IN = 0.03


class TogetherProvider:
    name = "together"

    def __init__(
        self, api_key: str | None = None, model: str = DEFAULT_MODEL, *,
        base_url: str = DEFAULT_BASE_URL, timeout_seconds: float = 180.0,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT, transport: Any | None = None,
    ) -> None:
        # `None` means "look in the environment"; an explicit "" means
        # "there is no key" and must not silently pick one up from the
        # shell -- that difference is what lets the Kernel pass
        # `ctx.secrets.get(...)` straight through, and what keeps a
        # test asserting the no-key path from depending on who is
        # running it.
        self._api_key = os.environ.get("TOGETHER_API_KEY") if api_key is None else api_key
        self._model = model or DEFAULT_MODEL
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._reasoning_effort = reasoning_effort
        # Test seam: a callable(url, headers, body_bytes, timeout) -> str.
        # Nothing in the suite may make a real network call.
        self._transport = transport

    def available(self) -> bool:
        return bool(self._api_key)

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float | None = None,
    ) -> ProviderResponse:
        return await asyncio.to_thread(self._complete_sync, messages, max_tokens, timeout)

    # -- the call ---------------------------------------------------------------
    def _complete_sync(self, messages: list[dict], max_tokens: int, timeout: float | None) -> ProviderResponse:
        if not self._api_key:
            raise ProviderUnavailable("no Together API key configured (TOGETHER_API_KEY)")
        body = {
            "model": self._model,
            "messages": [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in messages if m.get("content")
            ] or [{"role": "user", "content": ""}],
        }
        if max_tokens:
            body["max_tokens"] = int(max_tokens)
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort

        raw = self._post(
            f"{self._base_url}/chat/completions", body,
            timeout=timeout if timeout is not None else self._timeout_seconds,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(f"Together returned a non-JSON body: {raw[:200]!r}") from exc
        return self._to_response(data)

    def _post(self, url: str, body: dict, *, timeout: float) -> str:
        payload = json.dumps(body).encode()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # Live-caught 2026-09-07: without this every request came back
            # `HTTP 403: error code: 1010` -- Cloudflare in front of the
            # API rejects urllib's default `Python-urllib/3.x` agent. The
            # identical request from curl succeeded, which is what made it
            # a header problem rather than a key problem.
            "User-Agent": USER_AGENT,
        }
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            # The transport seam stands exactly where the real call does,
            # so a test's simulated network failure takes the same path to
            # `ProviderUnavailable` that a real one would.
            if self._transport is not None:
                return self._transport(url, headers, payload, timeout)
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed https endpoint
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            # The body carries Together's own error message; it is the only
            # thing that distinguishes a bad key from a bad model name.
            detail = exc.read().decode(errors="replace")[:300]
            raise ProviderUnavailable(f"Together HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001 -- network, DNS, TLS, timeout: degrade to the next provider
            raise ProviderUnavailable(f"Together request failed: {exc!r}") from exc

    # -- response shaping -------------------------------------------------------
    def _to_response(self, data: dict) -> ProviderResponse:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderUnavailable(f"Together returned no choices: {str(data)[:200]}")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        text = message.get("content") or ""
        if not text and message.get("reasoning_content"):
            # The model spent the whole output budget thinking and never
            # reached an answer. Handing Cognition "" would look exactly
            # like a real empty reply and be parsed as a non-answer; saying
            # the provider failed lets the Router try the next one, which
            # is what a truncated call actually warrants.
            raise ProviderUnavailable(
                f"Together answered with reasoning only (finish_reason={choice.get('finish_reason')!r}); "
                f"max_tokens was too small for this model to finish thinking",
            )

        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cached = self._cached_tokens(usage)
        # Together counts cached tokens *inside* `prompt_tokens`. Splitting
        # them out here is what lets one addition price both tiers without
        # charging the cached part twice.
        uncached = max(0, prompt_tokens - cached)
        return ProviderResponse(
            text=text, provider=self.name,
            input_tokens=uncached, output_tokens=output_tokens, cached_input_tokens=cached,
            cost_usd=self.price(uncached, output_tokens, cached),
            metadata={"model": data.get("model") or self._model},
        )

    @staticmethod
    def _cached_tokens(usage: dict) -> int:
        """Together reports the cache hit as `prompt_tokens_details.
        cached_tokens` (OpenAI's shape); some responses carry a flat
        `cached_tokens` instead, and older ones omit it entirely. Zero is
        the safe reading of "absent": it prices the whole prompt at the
        full input rate, so an unknown cache can only ever *over*-estimate
        the bill, never quietly under-report spend."""
        details = usage.get("prompt_tokens_details") or {}
        return int(details.get("cached_tokens") or usage.get("cached_tokens") or 0)

    @staticmethod
    def price(input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> float:
        return (
            (input_tokens / 1_000_000) * PRICE_IN
            + (output_tokens / 1_000_000) * PRICE_OUT
            + (cached_input_tokens / 1_000_000) * PRICE_CACHED_IN
        )


__all__ = [
    "TogetherProvider", "DEFAULT_MODEL", "DEFAULT_BASE_URL", "DEFAULT_REASONING_EFFORT",
    "USER_AGENT", "PRICE_IN", "PRICE_OUT", "PRICE_CACHED_IN",
]
