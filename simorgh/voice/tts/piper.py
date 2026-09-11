"""Piper (`piper-tts`), for the languages Kokoro does not speak.

Kokoro is the primary voice and has no Persian; Piper's `fa_IR` voices
are open-source, run on the CPU in well under real time (0.08 s for a
3.3 s sentence, measured 2026-09-11), and are one 63 MB download.
`voice models piper-fa` fetches the default one. Same shape as
`kokoro.py`: refused by name when the package or the files are absent.
"""

from __future__ import annotations

import asyncio
import urllib.request
from pathlib import Path

from ..api import Audio
from ..lang import FARSI

#: One voice per language, by the HuggingFace path `rhasspy/piper-voices`
#: publishes them under. Add a language here and `open_synthesiser`
#: routes it.
PIPER_VOICES: dict[str, str] = {
    FARSI: "fa_IR-amir-medium",
}
_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{family}/{code}/{name}/{quality}/{voice}{ext}"


def voice_urls(voice: str) -> tuple[tuple[str, str], ...]:
    """`(filename, url)` for a Piper voice id like `fa_IR-amir-medium`."""
    code, name, quality = voice.split("-", 2)
    family = code.split("_", 1)[0]
    return tuple(
        (f"{voice}{ext}", _HF.format(family=family, code=code, name=name, quality=quality, voice=voice, ext=ext))
        for ext in (".onnx", ".onnx.json")
    )


def download_piper(model_dir: Path, *, voice: str, timeout: float = 600.0) -> tuple[Path | None, str]:
    """Fetch a Piper voice's model and config into `model_dir`.
    `(path to the .onnx, problem)`. Streamed to a temp name and
    renamed, so a half-fetched model never passes for one."""
    model_dir.mkdir(parents=True, exist_ok=True)
    try:
        for filename, url in voice_urls(voice):
            target = model_dir / filename
            if target.is_file() and target.stat().st_size > 0:
                continue
            tmp = target.with_name(target.name + ".part")
            with urllib.request.urlopen(url, timeout=timeout) as resp, tmp.open("wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.replace(target)
    except (OSError, ValueError) as exc:
        return None, f"could not fetch piper voice {voice!r}: {exc}"
    return model_dir / f"{voice}.onnx", ""


class PiperSynthesiser:
    name = "piper"

    def __init__(self, config, *, voice: str | None = None) -> None:
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise ImportError("piper-tts is not installed (pip install piper-tts)") from exc
        self._voice = voice or PIPER_VOICES[FARSI]
        model_dir = Path(config.model_dir)
        model = model_dir / f"{self._voice}.onnx"
        if not (model.is_file() and model.with_name(model.name + ".json").is_file()):
            raise ImportError(f"piper voice {self._voice!r} not found under {model_dir} "
                              f"(run `voice models piper-{self._voice.split('_', 1)[0]}`)")
        self._piper = PiperVoice.load(str(model))
        self._speed = config.tts_speed

    def voices(self) -> list[str]:
        return [self._voice]

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        """`voice` is ignored: a Piper synthesiser IS one voice, and the
        Kokoro voice id the pipeline passes for every reply means
        nothing here."""
        def _run() -> Audio:
            config = None
            rate = speed or self._speed
            if rate and rate != 1.0:
                try:
                    from piper.config import SynthesisConfig
                    config = SynthesisConfig(length_scale=1.0 / rate)
                except (ImportError, TypeError):
                    config = None
            chunks = list(self._piper.synthesize(text, config) if config else self._piper.synthesize(text))
            pcm = b"".join(c.audio_int16_bytes for c in chunks)
            sample_rate = chunks[0].sample_rate if chunks else self._piper.config.sample_rate
            return Audio(pcm=pcm, sample_rate=sample_rate)

        return await asyncio.to_thread(_run)


__all__ = ["PIPER_VOICES", "PiperSynthesiser", "download_piper", "voice_urls"]
