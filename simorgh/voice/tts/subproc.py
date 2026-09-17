"""A speech engine that lives in another Python: the expressive lane.

The creator, 2026-09-13: "let's build the system for both Miso and
Chatterbox; I like to experiment with both and decide later." Neither
fits the repository's own Python -- Chatterbox pins torch 2.6 against
the 2.14 that kokoro and silero use here, MisoTTS wants Python 3.10 --
so each runs as a server in its own virtual environment under
`workspace/voice/venvs/<engine>/`, started on first use, kept warm, and
spoken to over JSON lines on its stdin/stdout:

    -> {"id": "7", "text": "Hello.", "tone": "warm", "reference": "", "params": {...}}
    <- {"id": "7", "path": "/tmp/….wav", "rate": 24000, "seconds": 1.3}
    <- {"id": "7", "error": "why"}

The server writes the audio to a file rather than down the pipe, so a
long reply never blocks the protocol; the engine reads it, deletes it,
and hands the pipeline the PCM. The first line the server prints is
`{"ready": true, "engine": ..., "device": ...}` once its model is loaded,
which for these models is ten to twenty seconds -- the `warmup()` the
streaming adapter already does at boot absorbs it.

Honesty: `available()` says exactly what is missing (the venv, the
package, the script); a server that dies mid-reply is restarted once
and the error is the reply's if it dies again; `speed` is honoured only
by engines that can, and the caller is told through `problems`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

from ..api import Audio

SERVERS_DIR = Path(__file__).resolve().parent / "servers"
DEFAULT_VENV_DIR = "workspace/voice/venvs"


def venv_python(venv_dir: Path | str, engine: str) -> Path:
    root = Path(venv_dir).expanduser() / engine
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def engine_available(engine: str, module: str, venv_dir: Path | str = DEFAULT_VENV_DIR) -> tuple[bool, str]:
    """Whether the engine's environment exists and imports its package."""
    python = venv_python(venv_dir, engine)
    if not python.is_file():
        return False, f"needs its environment: `voice models {engine}` installs it under {Path(venv_dir) / engine}"
    server = SERVERS_DIR / f"{engine}_server.py"
    if not server.is_file():
        return False, f"the server script {server} is missing"
    try:
        import subprocess

        probe = subprocess.run([str(python), "-c", f"import {module}"], capture_output=True, text=True, timeout=90)
    except Exception as exc:  # noqa: BLE001
        return False, f"could not probe {python}: {exc}"
    if probe.returncode != 0:
        tail = (probe.stderr or "").strip().splitlines()[-1:] or ["import failed"]
        return False, f"{engine}'s environment cannot import {module}: {tail[0][:160]} -- `voice models {engine}` repairs it"
    return True, ""


class SynthesisRefused(Exception):
    """The server answered the request with an error: bad reference, empty
    text. The server is fine; restarting it (12 s of model load) taught
    nothing (observer, 2026-09-13)."""


class SubprocessSynthesiser:
    """Base for an engine served from its own venv. Subclasses set `name`,
    `module`, `server` and `params_for(tone)`."""

    #: The engine that actually produced the last audio -- its own name,
    #: set only after a synthesis really returned sound. `LaneSynthesiser`
    #: keeps the same field for the same reason, and `voice test` reads
    #: whichever it finds.
    #:
    #: Without this, an engine used on its own (`expressive_lane =
    #: always` builds no lane) reported through the CONFIGURED name --
    #: so `voice test` answered `spoken (miso)` because the setting said
    #: miso, not because miso had spoken. The creator, 2026-09-16, heard
    #: nothing while being told exactly that.
    last_engine: str = ""

    name = "subprocess"
    module = ""
    server = ""
    #: sample rate the server reports; kept for `Audio`
    load_timeout_s = 240.0
    #: seconds of rendering per second of speech before the first piece
    #: has been measured (Chatterbox on the M3 Pro: 1.8-2.8, 2026-09-13)
    nominal_pace = 2.0

    def __init__(self, config, *, venv_dir: str | None = None, reference: str = "", timeout_s: float = 180.0) -> None:
        self._venv_dir = Path(venv_dir or getattr(config, "venv_dir", DEFAULT_VENV_DIR)).expanduser()
        self._python = venv_python(self._venv_dir, self.name)
        self._reference = reference
        self._timeout = float(timeout_s)
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._ready: dict = {}
        self._seq = 0
        self.problems: list[str] = []
        self.last_seconds = 0.0
        self.last_took_s = 0.0
        ok, why = engine_available(self.name, self.module, self._venv_dir)
        if not ok:
            raise ImportError(why)

    def voices(self) -> list[str]:
        return [self.name] + ([Path(self._reference).stem] if self._reference else [])

    #: running rendering-seconds-per-spoken-second over pieces of a
    #: second or more (a one-word warm-up is all fixed cost and would
    #: say 16); bounded, because the guard that reads it plans a wait
    _pace = 0.0

    def pace_ratio(self) -> float:
        """Rendering seconds per spoken second, a running figure over
        the pieces long enough to mean something; nominal until one."""
        return float(self._pace or self.nominal_pace)

    def _note_pace(self, took_s: float, seconds: float) -> None:
        if seconds < 1.0 or took_s <= 0:
            return
        ratio = min(4.0, max(1.0, took_s / seconds))
        self._pace = ratio if not self._pace else 0.6 * self._pace + 0.4 * ratio

    def params_for(self, tone: str) -> dict:  # pragma: no cover -- subclasses
        return {}

    async def _start(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        server = SERVERS_DIR / self.server
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        self._proc = await asyncio.create_subprocess_exec(
            str(self._python), str(server), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL if not os.environ.get("SIMORGH_TTS_DEBUG") else None, env=env)
        try:
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=self.load_timeout_s)
        except asyncio.TimeoutError:
            await self._stop()
            raise RuntimeError(f"{self.name} did not come up within {self.load_timeout_s:.0f}s") from None
        try:
            self._ready = json.loads(line.decode("utf-8") or "{}")
        except ValueError:
            self._ready = {}
        if not self._ready.get("ready"):
            await self._stop()
            raise RuntimeError(f"{self.name} failed to load: {self._ready.get('error') or line.decode('utf-8', 'replace')[:200]}")

    async def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def close(self) -> None:
        await self._stop()

    async def reference_for(self, voice: str) -> str:
        """The reference WAV for `voice`: the configured one by default;
        subclasses may render one per named voice."""
        return self._reference

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "") -> Audio:
        reference = await self.reference_for(voice)
        async with self._lock:
            for attempt in (1, 2):
                try:
                    return await self._one(text, tone=tone, speed=speed, reference=reference)
                except SynthesisRefused:
                    raise
                except (BrokenPipeError, ConnectionResetError, RuntimeError) as exc:
                    if attempt == 2:
                        raise
                    self.problems.append(f"{self.name} restarted: {exc}")
                    await self._stop()
            raise RuntimeError("unreachable")

    async def _one(self, text: str, *, tone: str, speed: float, reference: str = "") -> Audio:
        await self._start()
        assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None
        self._seq += 1
        out = Path(tempfile.gettempdir()) / f"simorgh-{self.name}-{os.getpid()}-{self._seq}.wav"
        request = {"id": str(self._seq), "text": text, "tone": tone, "speed": speed, "reference": reference,
                   "params": self.params_for(tone), "out": str(out)}
        started = time.monotonic()
        self._proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()
        try:
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=self._timeout)
        except asyncio.TimeoutError:
            await self._stop()
            raise RuntimeError(f"{self.name} took more than {self._timeout:.0f}s for {len(text)} characters") from None
        if not line:
            raise RuntimeError(f"{self.name} exited (code {self._proc.returncode})")
        reply = json.loads(line.decode("utf-8"))
        if reply.get("error"):
            raise SynthesisRefused(str(reply["error"])[:300])
        path = Path(reply.get("path") or out)
        try:
            with wave.open(str(path), "rb") as handle:
                rate = handle.getframerate()
                pcm = handle.readframes(handle.getnframes())
                if handle.getsampwidth() != 2:
                    raise RuntimeError(f"{self.name} wrote {handle.getsampwidth() * 8}-bit audio; 16-bit expected")
                channels = handle.getnchannels()
                if channels != 1:
                    # Take the first channel, sample by sample -- slicing the
                    # bytes would have taken every Nth BYTE.
                    import array

                    frames = array.array("h", pcm)
                    pcm = frames[::channels].tobytes()
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        # Empty audio is not a successful synthesis. Without this the
        # engine returned `Audio(b"", rate)`, the caller played nothing,
        # and `voice test` answered `spoken (miso)` -- the creator,
        # 2026-09-16: "i didn't hear anything". An engine that produces
        # no sound must say so, not succeed quietly.
        if not pcm:
            self.last_engine = ""
            raise SynthesisRefused(
                f"{self.name} returned no audio for {len(text)} characters "
                f"(wrote {path})")
        # Sound really came back: this engine, and no other, spoke.
        self.last_engine = self.name
        self.last_took_s = round(time.monotonic() - started, 2)
        self.last_seconds = len(pcm) / 2 / float(rate or 24000)
        self._note_pace(self.last_took_s, self.last_seconds)
        return Audio(pcm, int(rate))


def create_venv(venv_dir: Path | str, engine: str, *, python: str = "", packages: tuple[str, ...] = (),
                editable: str = "", log=print) -> tuple[Path | None, str]:
    """Make `<venv_dir>/<engine>` and install `packages` (and an editable
    checkout) into it, with `uv` when present, else `python -m venv` +
    pip. Returns (python path, problem)."""
    import subprocess

    root = Path(venv_dir).expanduser() / engine
    py = venv_python(venv_dir, engine)
    uv = shutil.which("uv")
    try:
        if not py.is_file():
            root.parent.mkdir(parents=True, exist_ok=True)
            if uv:
                cmd = [uv, "venv", str(root)] + (["--python", python] if python else [])
            else:
                base = shutil.which(f"python{python}") if python else sys.executable
                if not base:
                    return None, f"needs Python {python} on this machine (brew install python@{python}), or `uv`"
                cmd = [base, "-m", "venv", str(root)]
            log(f"  creating {root} ...")
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if done.returncode != 0:
                return None, f"could not create the environment: {(done.stderr or done.stdout).strip()[-300:]}"
        installs = []
        if packages:
            installs.append(list(packages))
        if editable:
            installs.append(["-e", editable])
        for spec in installs:
            if uv:
                cmd = [uv, "pip", "install", "--python", str(py), *spec]
            else:
                cmd = [str(py), "-m", "pip", "install", "-q", "setuptools", "wheel", *spec]
            log(f"  installing {' '.join(spec)} ...")
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if done.returncode != 0:
                return None, f"install failed: {(done.stderr or done.stdout).strip()[-400:]}"
    except subprocess.TimeoutExpired:
        return None, "the install took more than an hour; run `voice models <engine>` again"
    except OSError as exc:
        return None, f"could not run the installer: {exc}"
    return py, ""


__all__ = ["DEFAULT_VENV_DIR", "SERVERS_DIR", "SubprocessSynthesiser", "SynthesisRefused", "create_venv", "engine_available", "venv_python"]
