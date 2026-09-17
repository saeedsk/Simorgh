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
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
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
        vision_model: str = "",
    ) -> None:
        self._model = model
        # A second, separate model for calls that carry pictures: the text
        # model cannot see, and asking it to would get a confident answer
        # about an image it never received. Empty means Sim cannot look at
        # anything, and `supports_images` says so rather than guessing.
        self._vision_model = vision_model
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

    @property
    def vision_model(self) -> str:
        return self._vision_model

    @property
    def supports_images(self) -> bool:
        return bool(self._vision_model)

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
            return self._probe_ok
        except Exception:  # noqa: BLE001 -- not running
            self._probe_ok = False
        # Not answering: start it, once per probe window. The creator,
        # 2026-09-17, choosing how the local engine should come back:
        # "Sim starts it when needed". Seven cameras went blind on
        # 2026-09-16 for no reason but a server nobody had started.
        #
        # Inside the probe cache on purpose: a machine with no Ollama
        # tries once every 30 s, not once per request, which is the
        # difference between a retry and a fork bomb.
        if self._start_server():
            try:
                self._request("GET", "/api/version", None, timeout=2.0)
                self._probe_ok = True
            except Exception:  # noqa: BLE001 -- it was started but is not up yet
                self._probe_ok = False
        return self._probe_ok

    def _start_server(self) -> bool:
        """Spawn `ollama serve`, detached. False when there is nothing to
        spawn, which is not an error -- it is a machine without Ollama.

        Detached deliberately: a child of this process dies when Sim
        exits, and a server that dies with its caller is the fault this
        is fixing, not a fix for it.
        """
        import shutil
        import subprocess

        binary = shutil.which("ollama")
        if not binary:
            return False
        try:
            subprocess.Popen(                      # noqa: S603 -- a fixed binary, no shell
                [binary, "serve"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
        time.sleep(1.0)     # it binds its port in well under a second
        return True

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int, timeout: float | None = None,
        images: list[str] | None = None,
    ) -> ProviderResponse:
        return await asyncio.to_thread(self._complete_sync, messages, max_tokens, timeout, tuple(images or ()))

    def _complete_sync(self, messages: list[dict], max_tokens: int, timeout: float | None,
                       images: tuple[str, ...] = ()) -> ProviderResponse:
        if images and not self._vision_model:
            raise ProviderUnavailable(
                "no Ollama vision model configured ([cognition.providers.ollama] vision_model)")
        if not images and not self._model:
            raise ProviderUnavailable("no Ollama model configured ([cognition.providers.ollama] model)")
        options: dict = {"num_ctx": self._num_ctx}
        if max_tokens:
            options["num_predict"] = int(max_tokens)
        sent = [{"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in messages if m.get("content")] or [{"role": "user", "content": ""}]
        if images:
            # Ollama takes pictures as base64 on the message they belong to.
            # They ride with the last non-system message -- the one actually
            # asking the question -- so a system prompt never swallows them.
            encoded = [_encoded(path) for path in images]
            index = next((i for i in range(len(sent) - 1, -1, -1) if sent[i]["role"] != "system"), len(sent) - 1)
            sent[index] = {**sent[index], "images": [b for b in encoded if b]}
        body = {
            "model": self._vision_model if images else self._model,
            "stream": False, "keep_alive": self._keep_alive, "think": False,
            "options": options, "messages": sent,
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
            cost_usd=0.0, metadata={"model": data.get("model") or body["model"], "done_reason": data.get("done_reason")},
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


#: A camera frame is 1310 KB at a Reolink's full resolution and 37 KB from
#: Ring. Measured 2026-09-15: the same two-frame question took 43.3s on the
#: NVR pair and 10.6s on the Ring pair. A description of what is happening
#: does not need the sensor's every pixel, and a doorbell answered forty
#: seconds late is not an answer.
VISION_MAX_EDGE = 1024


def _shrunk(data: bytes, *, max_edge: int = VISION_MAX_EDGE) -> bytes:
    """A picture small enough to look at quickly, or the original back.

    Pillow is optional on purpose: without it the picture still goes, just
    slowly, rather than the model going blind. Lives here rather than beside
    the cameras because it belongs to encoding, and because Cognition may
    not import Execution (tests/simorgh/test_module_boundaries.py).
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return data          # no Pillow: the picture still goes, just slowly
    try:
        import io

        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) <= max_edge:
                return data
            image = image.convert("RGB")
            image.thumbnail((max_edge, max_edge))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=80, optimize=True)
            return out.getvalue() or data
    except Exception:  # noqa: BLE001 -- a frame Pillow cannot read is still a frame
        return data


def _encoded(path: str) -> str:
    """One picture as base64, or "" when it cannot be read -- a missing
    still is one fewer angle on the scene, not a failed call.

    Shrunk first when it is big: a 1310 KB camera frame took 43s to
    describe where a 37 KB one took 10.6s (measured 2026-09-15), and the
    extra pixels say nothing more about what is happening.
    """
    try:
        data = Path(path).read_bytes()
    except Exception:  # noqa: BLE001 -- unreadable, gone, or not a file
        return ""
    return base64.b64encode(_shrunk(data)).decode("ascii")


__all__ = ["OllamaProvider", "DEFAULT_BASE_URL", "DEFAULT_KEEP_ALIVE", "DEFAULT_NUM_CTX"]
