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


#: A feeling as a share of another Kokoro voice mixed into the base voice
#: (the same speaker, coloured): tone -> (voice by family, weight). The
#: families are Kokoro's own prefixes: af/am American, bf/bm British.
#: Measured 2026-09-13: a 0.3-0.4 blend changes the audio by ~7% mean
#: absolute difference and costs nothing extra.
TONE_BLENDS: dict[str, tuple[dict[str, str], float]] = {
    "warm": ({"af": "af_heart", "am": "am_michael", "bf": "bf_emma", "bm": "bm_george"}, 0.4),
    "bright": ({"af": "af_bella", "am": "am_puck", "bf": "bf_lily", "bm": "bm_lewis"}, 0.4),
    "calm": ({"af": "af_nicole", "am": "am_onyx", "bf": "bf_alice", "bm": "bm_daniel"}, 0.3),
    "serious": ({"af": "af_sarah", "am": "am_eric", "bf": "bf_isabella", "bm": "bm_george"}, 0.35),
    "playful": ({"af": "af_sky", "am": "am_adam", "bf": "bf_lily", "bm": "bm_fable"}, 0.4),
    "sorry": ({"af": "af_nicole", "am": "am_michael", "bf": "bf_alice", "bm": "bm_daniel"}, 0.25),
}


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
        self._blend = float(getattr(config, "tone_blend", 1.0))
        self._styles: dict[str, object] = {}

    def voices(self) -> list[str]:
        try:
            return sorted(self._kokoro.get_voices())
        except Exception:  # noqa: BLE001
            return [self._voice]

    def style_for(self, voice: str, tone: str):
        """The style Kokoro speaks with: the voice's own, or a blend of it
        with the tone's voice of the same family; None means "the name".
        The blend weight is scaled by `[voice] tone_blend` (1.0 = as
        tabled, 0 = plain voice)."""
        spec = TONE_BLENDS.get((tone or "").lower())
        if spec is None or self._blend <= 0.0:
            return None
        family = voice[:2] if len(voice) > 2 and voice[2] == "_" else "af"
        other = spec[0].get(family) or spec[0]["af"]
        weight = max(0.0, min(0.6, spec[1] * self._blend))
        if other == voice or weight <= 0.0:
            return None
        try:
            import numpy as np
        except ImportError:  # kokoro-onnx brings numpy; without it there is no blend, just the plain voice
            return None
        try:
            key = f"{voice}+{other}@{weight:.2f}"
            style = self._styles.get(key)
            if style is None:
                names = set(self._kokoro.get_voices())
                if voice not in names or other not in names:
                    return None
                style = ((1.0 - weight) * self._kokoro.get_voice_style(voice)
                         + weight * self._kokoro.get_voice_style(other)).astype(np.float32)
                self._styles[key] = style
            return style
        except Exception:  # noqa: BLE001 -- a blend that fails is a plain voice, never a failed reply
            return None

    #: reads ⟦Name|ipa⟧ marks (voice/pronounce.py) as phonemes
    speaks_ipa = True

    def _phonemes(self, text: str) -> str | None:
        """The text as phonemes when it carries an IPA mark and the
        library can phonemize the rest; None to speak it as text."""
        from ..pronounce import phonemes_for, strip_marks

        if "⟦" not in text:
            return None
        tokenizer = getattr(self._kokoro, "tokenizer", None)
        if tokenizer is None or not hasattr(tokenizer, "phonemize"):
            return None
        try:
            return phonemes_for(text, lambda plain: tokenizer.phonemize(plain, lang="en-us"))
        except Exception:  # noqa: BLE001 -- then the respelling, as any other engine
            return None

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "") -> Audio:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover -- kokoro-onnx depends on numpy
            raise RuntimeError("kokoro needs numpy") from exc
        from ..pronounce import strip_marks

        phonemes = self._phonemes(text)
        if phonemes is None:
            text = strip_marks(text)

        def _run():
            name = voice or self._voice
            style = self.style_for(name, tone)
            samples, rate = self._kokoro.create(phonemes if phonemes is not None else text,
                                                voice=style if style is not None else name,
                                                speed=speed or self._speed, lang="en-us", is_phonemes=phonemes is not None)
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            return pcm, int(rate)

        pcm, rate = await asyncio.to_thread(_run)
        # Kokoro speaks at 24 kHz. Keep it: every playback path plays a
        # WAV at its own rate, and downsampling to the pipeline's 16 kHz
        # -- which only the RECOGNISER needs -- threw away exactly the
        # brightness that separates a natural voice from a telephone.
        return Audio(pcm, rate)
