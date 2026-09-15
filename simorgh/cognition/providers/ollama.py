"""Ollama provider: a local model as the last resort before the floor.

The creator, 2026-09-15: "give Sim the option of using Ollama as last-resort
fallback if all API calls fail ... I prefer Sim doesn't use much local
resource from this machine." So it is built only when `[cognition.providers.
ollama] model` is set, sits after every cloud provider and before the floor,
loads the model only when asked (`keep_alive` unloads it again after a short
idle), caps the context window (`num_ctx`) so its memory stays small, turns a
reasoning model's thinking off, and is normally limited to chat
(`only_purposes`). Stdlib only: it talks to Ollama's local HTTP API.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any

from simorgh.contracts.protocols import ProviderResponse

from ..api import ProviderUnavailable

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_KEEP_ALIVE = "2m"
DEFAULT_NUM_CTX = 8192
_PROBE_CACHE_S = 30.0


class OllamaProvider:
    name = "ollama"

    def __init__(
        self, model: str = "", *, base_url: str = DEFAULT_BASE_URL, keep_alive: str = DEFAULT_KEEP_ALIVE,
        num_ctx: int = DEFAULT_NUM_CTX, timeout_seconds: float = 120.0, transport: Any | None = None,
    ) -> None:
        self._model = model
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._keep_alive = keep_alive or DEFAULT_KEEP_ALIVE
        self._num_ctx = int(num_ctx or DEFAULT_NUM_CTX)
        self._timeout_seconds = timeout_seconds
        # Test seam: callable(method, url, body_bytes | None, timeout) -> str.
        self._transport = transport
        self._probe_at = 0.0
        self._probe_ok = False

    @property
    def model(self) -> str:
        return self._model

    def available(self) -> bool:
        """A model is configured and the local server answers. Checked at most
        every 30 s, with a short timeout, so the Router can ask on every call."""
        if not self._model:
            return False
        now = time.monotonic()
        if now - self._probe_at < _PROBE_CACHE_S:
            return self._probe_ok
        self._probe_at = now
        try:
            self._request("GET", "/api/version", None, timeout=0.5)
            self._probe_ok = True
        except Exception:  # noqa: BLE001 -- not running is simply unavailable
            self._probe_ok = False
        return self._probe_ok

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float | None = None,
    ) -> ProviderResponse:
        return await asyncio.to_thread(self._complete_sync, messages, max_tokens, timeout)

    def _complete_sync(self, messages: list[dict], max_tokens: int, timeout: float | None) -> ProviderResponse:
        if not self._model:
            raise ProviderUnavailable("no Ollama model configured ([cognition.providers.ollama] model)")
        options: dict = {"num_ctx": self._num_ctx}
        if max_tokens:
            options["num_predict"] = int(max_tokens)
        body = {
            "model": self._model, "stream": False, "keep_alive": self._keep_alive, "think": False,
            "options": options,
            "messages": [{"role": m.get("role", "user"), "content": m.get("content", "")}
                         for m in messages if m.get("content")] or [{"role": "user", "content": ""}],
        }
        raw = self._request("POST", "/api/chat", json.dumps(body).encode(),
                            timeout=timeout if timeout is not None else self._timeout_seconds)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(f"Ollama returned a non-JSON body: {raw[:200]!r}") from exc
        if data.get("error"):
            raise ProviderUnavailable(f"Ollama error: {str(data['error'])[:200]}")
        text = ((data.get("message") or {}).get("content") or "").strip()
        return ProviderResponse(
            text=text, provider=self.name,
            input_tokens=int(data.get("prompt_eval_count") or 0), output_tokens=int(data.get("eval_count") or 0),
            cost_usd=0.0, metadata={"model": data.get("model") or self._model, "done_reason": data.get("done_reason")},
        )

    def _request(self, method: str, path: str, body: bytes | None, *, timeout: float) -> str:
        url = f"{self._base_url}{path}"
        try:
            if self._transport is not None:
                return self._transport(method, url, body, timeout)
            request = urllib.request.Request(url, data=body, method=method,
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- local Ollama endpoint
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise ProviderUnavailable(f"Ollama HTTP {exc.code}: {detail}") from exc
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 -- not running, refused, timeout
            raise ProviderUnavailable(f"Ollama request failed: {exc!r}") from exc


__all__ = ["OllamaProvider", "DEFAULT_BASE_URL", "DEFAULT_KEEP_ALIVE", "DEFAULT_NUM_CTX"]
