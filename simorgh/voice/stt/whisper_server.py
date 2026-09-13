"""whisper.cpp kept loaded: `whisper-server`, started once, asked over HTTP.

Measured on the M3 Pro with large-v3-turbo on a six-second clip
(2026-09-13): `whisper-cli` 3.35 s wall for 1.27 s of work -- the rest
is the process starting, the model mapping and Metal warming up, paid
on EVERY turn; the same clip through a running `whisper-server` 0.69 s.
That is two and a half seconds off every spoken reply for the same
words, which is why this engine comes before the CLI in `auto`.

The server is whisper.cpp's own (Homebrew installs it beside
`whisper-cli`), bound to 127.0.0.1 on a free port, started on the
first transcription and kept for the life of the engine; `close()`
ends it. A server that stops answering is restarted once, and the
error is the turn's if it fails again. Standard library only.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import time
import urllib.error
import uuid
from pathlib import Path

from ..api import Audio, Utterance, Word
from ..audio import wav_bytes
from .whisper_cli import _TEST_MODEL, clean_transcript, find_model

READY_TIMEOUT_S = 90.0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _multipart(fields: dict[str, str], file_field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "simorgh-" + uuid.uuid4().hex
    out = bytearray()
    for key, value in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode()
    out += data + f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _words(reply: dict) -> list[Word]:
    out: list[Word] = []
    for seg in reply.get("segments") or []:
        text = str(seg.get("text") or "")
        if not text.strip():
            continue
        try:
            start, end = float(seg.get("start") or 0.0), float(seg.get("end") or 0.0)
        except (TypeError, ValueError):
            continue
        cleaned = clean_transcript(text)
        if end > start and cleaned:
            out.append(Word(cleaned, start, end))
    return out


class WhisperServerRecogniser:
    name = "whisper_server"

    def __init__(self, config, *, repo_root=None, command: list[str] | None = None, port: int = 0) -> None:
        if command is None:
            binary = shutil.which("whisper-server")
            if not binary:
                raise ImportError("whisper-server (whisper.cpp) is not installed")
            command = [binary]
        self._command = list(command)
        model_dir = Path(config.model_dir)
        if repo_root is not None and not model_dir.is_absolute():
            model_dir = Path(repo_root) / model_dir
        model = find_model(config.stt_model, model_dir)
        if model is None:
            raise ImportError(f"no whisper.cpp model for {config.stt_model!r} under {model_dir} "
                              f"(run `voice models base.en` to download one)")
        self._model = model
        self._language = config.stt_language or "auto"
        self._port = int(port or getattr(config, "stt_server_port", 0) or 0)
        self._by_word = bool(getattr(config, "diarize_words", False))
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.problems: list[str] = []
        self.last_took_s = 0.0
        tag = model.name.replace("ggml-", "").replace(".bin", "")
        self.name = f"whisper_server:{tag}" + (" (test model -- run `voice models base.en`)" if model.name == _TEST_MODEL else "")

    # ------------------------------------------------------------ the server
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._port}{path}"

    async def _start(self) -> None:
        if self.running:
            return
        if not self._port:
            self._port = free_port()
        # Timed segments are what voice/diarize.py attributes to voices.
        # whisper's own segments cost nothing over none (1.28 s either
        # way on the six-second clip, 2026-09-13); one segment per word
        # (`-ml 1 -sow`) is finer and 0.3-1.4 s slower -- `diarize_words`.
        args = [*self._command, "-m", str(self._model), "--host", "127.0.0.1", "--port", str(self._port)]
        if self._by_word:
            args += ["-ml", "1", "-sow"]
        quiet = None if os.environ.get("SIMORGH_STT_DEBUG") else asyncio.subprocess.DEVNULL
        self._proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL, stdout=quiet, stderr=quiet)
        deadline = time.monotonic() + READY_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.returncode is not None:
                raise RuntimeError(f"whisper-server exited with code {self._proc.returncode} before it listened")
            if await asyncio.to_thread(self._answers):
                return
            await asyncio.sleep(0.2)
        await self._stop()
        raise RuntimeError(f"whisper-server did not listen within {READY_TIMEOUT_S:.0f}s")

    def _answers(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self._port), timeout=0.5):
                return True
        except OSError:
            return False

    async def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def close(self) -> None:
        await self._stop()

    async def warmup(self) -> float:
        """Start the server now, so the first turn does not pay for it."""
        started = time.monotonic()
        async with self._lock:
            await self._start()
        return time.monotonic() - started

    # ------------------------------------------------------------- one turn
    def _post(self, body: bytes, content_type: str) -> dict:
        import urllib.request

        request = urllib.request.Request(self._url("/inference"), data=body, method="POST",
                                         headers={"Content-Type": content_type, "Content-Length": str(len(body))})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        if audio.seconds < 0.1:
            return Utterance(text="", confidence=0.0, seconds=audio.seconds, engine=self.name,
                             language=language or self._language)
        body, content_type = _multipart({"response_format": "verbose_json", "language": language or self._language,
                                         "temperature": "0.0"}, "file", "turn.wav", wav_bytes(audio))
        started = time.monotonic()
        async with self._lock:
            reply: dict = {}
            for attempt in (1, 2):
                try:
                    await self._start()
                    reply = await asyncio.to_thread(self._post, body, content_type)
                    break
                except urllib.error.HTTPError as exc:
                    if 400 <= exc.code < 500:
                        # The request was refused; the server is fine. Restarting
                        # it reloaded 1.6 GB for nothing (observer, 2026-09-13).
                        return Utterance(text="", confidence=0.0, seconds=audio.seconds, engine=self.name,
                                         language=language or self._language)
                    if attempt == 2:
                        raise RuntimeError(f"whisper-server failed: HTTP {exc.code}") from exc
                    self.problems.append(f"whisper-server restarted: HTTP {exc.code}")
                    await self._stop()
                except (OSError, RuntimeError, ValueError) as exc:
                    if attempt == 2:
                        raise RuntimeError(f"whisper-server failed: {exc}") from exc
                    self.problems.append(f"whisper-server restarted: {exc}")
                    await self._stop()
        self.last_took_s = round(time.monotonic() - started, 3)
        if reply.get("error"):
            raise RuntimeError(f"whisper-server: {reply['error']}")
        words = tuple(_words(reply))
        text = "".join(str(s.get("text") or "") for s in (reply.get("segments") or [])) if reply.get("segments") \
            else str(reply.get("text") or "")
        heard_language = str(reply.get("detected_language") or reply.get("language") or "") or (language or self._language)
        return Utterance(text=clean_transcript(text), confidence=1.0, seconds=audio.seconds,
                         engine=self.name, language=heard_language, words=words)


__all__ = ["WhisperServerRecogniser", "free_port"]
