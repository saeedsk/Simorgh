"""Microphones and speakers for the laptop, with what this machine has.

Two of each, tried in order. `sounddevice` (PortAudio) when the package
is installed; otherwise `ffmpeg` -- present on this machine, with an
AVFoundation input on macOS and ALSA/PulseAudio on Linux -- for capture,
and `afplay` (macOS) / `ffplay` for playback. Nothing here is required
to import: a machine with none of it answers `voice devices` with "no
microphone path: pip install sounddevice, or install ffmpeg".

Capture is push-to-talk shaped: record until the endpointer says the
utterance ended, or `max_seconds`. The endpointer is `vad.Endpointer`
fed 30 ms frames as they arrive.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from .api import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, Audio

FRAME_MS = 30
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * SAMPLE_WIDTH * CHANNELS


def wav_bytes(audio: Audio) -> bytes:
    """`audio` as a WAV file in memory."""
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(audio.sample_rate)
        w.writeframes(audio.pcm)
    return buf.getvalue()


def read_wav(path: Path) -> Audio:
    """A WAV file as `Audio`, resampled to 16 kHz mono through ffmpeg
    when it is anything else."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() == CHANNELS and w.getsampwidth() == SAMPLE_WIDTH and w.getframerate() == SAMPLE_RATE:
            return Audio(w.readframes(w.getnframes()))
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"{path} is not 16 kHz mono int16 and ffmpeg is not installed to convert it")
    done = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "s16le", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    if done.returncode != 0:
        raise RuntimeError(f"ffmpeg could not read {path}: {done.stderr.decode(errors='replace')[:200]}")
    return Audio(done.stdout)


def write_wav(path: Path, audio: Audio) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(audio))


# ------------------------------------------------------------------ capture
class SounddeviceMicrophone:
    """PortAudio capture, frame by frame, until the endpointer stops it."""

    name = "sounddevice"

    def __init__(self) -> None:
        try:
            import sounddevice  # noqa: F401 -- probe: absent means "not this one"
        except ImportError as exc:
            raise ImportError("sounddevice is not installed") from exc

    async def capture(self, *, max_seconds: float, endpointer) -> Audio:
        try:
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("sounddevice is not installed") from exc

        loop = asyncio.get_running_loop()
        frames: list[bytes] = []
        done = asyncio.Event()
        frame_samples = SAMPLE_RATE * FRAME_MS // 1000

        def _on_frame(indata, _frames, _time, _status) -> None:
            pcm = bytes(indata)
            frames.append(pcm)
            if endpointer.feed(pcm) or sum(map(len, frames)) >= max_seconds * SAMPLE_RATE * SAMPLE_WIDTH:
                loop.call_soon_threadsafe(done.set)

        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
                               blocksize=frame_samples, callback=_on_frame):
            await done.wait()
        return Audio(b"".join(frames))


class FfmpegMicrophone:
    """Capture through ffmpeg's platform input, read as a stream of 30 ms
    frames so the endpointer can stop it mid-recording."""

    name = "ffmpeg"

    def __init__(self, device: str = "") -> None:
        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise ImportError("ffmpeg is not installed")
        self._device = device

    def _input_args(self) -> list[str]:
        if sys.platform == "darwin":
            return ["-f", "avfoundation", "-i", f":{self._device or '0'}"]
        if sys.platform.startswith("linux"):
            return ["-f", "pulse", "-i", self._device or "default"]
        return ["-f", "dshow", "-i", f"audio={self._device or 'default'}"]

    async def capture(self, *, max_seconds: float, endpointer) -> Audio:
        proc = await asyncio.create_subprocess_exec(
            self._ffmpeg, "-v", "error", *self._input_args(),
            "-f", "s16le", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "-t", f"{max_seconds:.1f}", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
        )
        frames: list[bytes] = []
        try:
            assert proc.stdout is not None
            while True:
                frame = await proc.stdout.readexactly(FRAME_BYTES)
                frames.append(frame)
                if endpointer.feed(frame):
                    break
        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                frames.append(exc.partial)
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
        if not frames:
            err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
            raise RuntimeError(f"ffmpeg captured nothing: {err.strip()[:200] or 'no input device?'}")
        return Audio(b"".join(frames))


# ----------------------------------------------------------------- playback
class SounddeviceSpeaker:
    name = "sounddevice"

    def __init__(self) -> None:
        try:
            import sounddevice  # noqa: F401
        except ImportError as exc:
            raise ImportError("sounddevice is not installed") from exc

    async def play(self, audio: Audio) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover -- both are optional
            raise RuntimeError("sounddevice playback needs numpy and sounddevice") from exc

        samples = np.frombuffer(audio.pcm, dtype=np.int16)
        await asyncio.to_thread(sd.play, samples, audio.sample_rate, blocking=True)

    async def stop(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:  # pragma: no cover
            return
        await asyncio.to_thread(sd.stop)


class CommandSpeaker:
    """Playback through a command that takes a WAV path: `afplay` on
    macOS, `ffplay` anywhere ffmpeg is."""

    def __init__(self) -> None:
        for candidate, args in (("afplay", []), ("ffplay", ["-nodisp", "-autoexit", "-v", "quiet"])):
            found = shutil.which(candidate)
            if found:
                self._cmd = [found, *args]
                self.name = candidate
                return
        raise ImportError("neither afplay nor ffplay is installed")

    _proc = None

    async def play(self, audio: Audio) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes(audio))
            path = tmp.name
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._cmd, path, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL,
            )
            await self._proc.wait()
        finally:
            self._proc = None
            Path(path).unlink(missing_ok=True)

    async def stop(self) -> None:
        """Kill the player; `play` returns as its process exits."""
        proc = self._proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()


def open_microphone(preferred: str = "auto") -> tuple[object | None, str]:
    """`(microphone, why not)`: the first capture path that works."""
    order = {"auto": (SounddeviceMicrophone, FfmpegMicrophone), "sounddevice": (SounddeviceMicrophone,),
             "ffmpeg": (FfmpegMicrophone,)}.get(preferred, (SounddeviceMicrophone, FfmpegMicrophone))
    reasons = []
    for cls in order:
        try:
            return cls(), ""
        except ImportError as exc:
            reasons.append(f"{cls.name}: {exc}")
    return None, "no microphone path (" + "; ".join(reasons) + ") -- pip install sounddevice, or install ffmpeg"


def open_speaker(preferred: str = "auto") -> tuple[object | None, str]:
    order = {"auto": (SounddeviceSpeaker, CommandSpeaker), "sounddevice": (SounddeviceSpeaker,),
             "command": (CommandSpeaker,)}.get(preferred, (SounddeviceSpeaker, CommandSpeaker))
    reasons = []
    for cls in order:
        try:
            return cls(), ""
        except ImportError as exc:
            reasons.append(f"{getattr(cls, 'name', cls.__name__)}: {exc}")
    return None, "no playback path (" + "; ".join(reasons) + ") -- pip install sounddevice, or install ffmpeg"


__all__ = ["CommandSpeaker", "FFMPEG_FRAME_BYTES" if False else "FRAME_BYTES", "FRAME_MS", "FfmpegMicrophone",
           "SounddeviceMicrophone", "SounddeviceSpeaker", "open_microphone", "open_speaker", "read_wav",
           "wav_bytes", "write_wav"]
