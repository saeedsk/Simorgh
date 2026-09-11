"""Kokoro-82M through `kokoro-onnx`, the design's primary voice."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..api import SAMPLE_RATE, Audio


class KokoroSynthesiser:
    name = "kokoro"

    def __init__(self, config) -> None:
        try:
            from kokoro_onnx import Kokoro  # type: ignore
        except ImportError as exc:
            raise ImportError("kokoro-onnx is not installed") from exc
        model_dir = Path(config.model_dir).expanduser()
        model, voices = model_dir / "kokoro-v1.0.onnx", model_dir / "voices-v1.0.bin"
        if not (model.is_file() and voices.is_file()):
            raise ImportError(f"kokoro model files not found under {model_dir} (run `voice models kokoro`)")
        self._kokoro = Kokoro(str(model), str(voices))
        self._voice = config.tts_voice
        self._speed = config.tts_speed

    def voices(self) -> list[str]:
        try:
            return sorted(self._kokoro.get_voices())
        except Exception:  # noqa: BLE001
            return [self._voice]

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover -- kokoro-onnx depends on numpy
            raise RuntimeError("kokoro needs numpy") from exc

        def _run():
            samples, rate = self._kokoro.create(text, voice=voice or self._voice, speed=speed or self._speed, lang="en-us")
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            return pcm, int(rate)

        pcm, rate = await asyncio.to_thread(_run)
        if rate != SAMPLE_RATE:
            from ..audio import read_wav, write_wav  # resample through ffmpeg
            import tempfile
            with tempfile.TemporaryDirectory() as raw:
                p = Path(raw) / "k.wav"
                write_wav(p, Audio(pcm, rate))
                return read_wav(p)
        return Audio(pcm, rate)
