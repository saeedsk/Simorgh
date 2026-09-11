"""Kokoro-82M through `kokoro-onnx`, the design's primary voice."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..api import SAMPLE_RATE, Audio


#: The ONNX build's own release files (thewh1teagle/kokoro-onnx).
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def download_kokoro(model_dir: Path, *, timeout: float = 900.0) -> tuple[Path | None, str]:
    """Fetch Kokoro's model and voice bank into `model_dir` (~340 MB).
    `(model path, problem)`. Streamed to a `.part` and renamed, so a
    half-fetched model never passes for one."""
    import urllib.error
    import urllib.request

    model_dir.mkdir(parents=True, exist_ok=True)
    for name, url in KOKORO_FILES.items():
        target = model_dir / name
        if target.is_file() and target.stat().st_size > 1_000_000:
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp, tmp.open("wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.replace(target)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            tmp.unlink(missing_ok=True)
            return None, f"could not download {name}: {exc!r}"
    return model_dir / "kokoro-v1.0.onnx", ""


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
        # Kokoro speaks at 24 kHz. Keep it: every playback path plays a
        # WAV at its own rate, and downsampling to the pipeline's 16 kHz
        # -- which only the RECOGNISER needs -- threw away exactly the
        # brightness that separates a natural voice from a telephone.
        return Audio(pcm, rate)
