"""Meta's MMS-TTS, a second voice for the languages Kokoro does not speak.

Piper's five Persian voices are all VITS-medium and share a family
resemblance; the creator, 2026-09-22: "i don't like the farsi voice
model, what are my options?". MMS (Massively Multilingual Speech) is a
different model trained on different data -- `facebook/mms-tts-fas` for
Persian -- so it is a real alternative rather than another take on the
same one.

Measured on the M3 Pro, first run: 8.4 s of audio in 1.43 s (about six
times real time), 11.5 s of that spent loading the model once. It
speaks at 16 kHz against Piper's 22.05 kHz, which is the trade: a
different voice, less bandwidth.

Optional, like every other engine here: `transformers` and `torch` are
heavy and not part of the stdlib core, so an install without them
refuses BY NAME rather than failing at the first spoken word.
"""

from __future__ import annotations

import asyncio
import re

from ..api import Audio
from ..lang import FARSI

#: language -> the HuggingFace model id MMS publishes for it. MMS covers
#: over a thousand languages; these are the ones this house speaks.
MMS_MODELS: dict[str, str] = {
    FARSI: "facebook/mms-tts-fas",
}

#: MMS is a plain VITS with no punctuation model: a full stop is not a
#: pause, it is an unknown character. Sentences are spoken separately
#: and joined with a real silence, which is also what stops one long
#: paragraph coming out as a single breathless run.
_SENTENCE = re.compile(r"[^.!?؟۔\n]+[.!?؟۔]?")
_GAP_SECONDS = 0.18


class MmsSynthesiser:
    name = "mms"

    def __init__(self, config, *, model_id: str = "", language: str = FARSI) -> None:
        try:
            import numpy
            import torch
            from transformers import AutoTokenizer, VitsModel
        except ImportError as exc:                          # pragma: no cover -- depends on the install
            raise ImportError(
                "MMS-TTS needs transformers and torch (pip install 'transformers[torch]')") from exc
        # Kept on the instance, so nothing in this module imports a
        # third-party package outside that guard -- the rule
        # `test_module_boundaries` enforces for every optional adapter.
        self._np, self._torch = numpy, torch
        self._model_id = model_id or MMS_MODELS.get(language) or MMS_MODELS[FARSI]
        try:
            # `local_files_only` is deliberate: a synthesiser must not
            # stall a spoken reply on a download. `voice models mms-fa`
            # fetches it once, and until then this engine refuses by
            # name like any other missing model.
            self._model = VitsModel.from_pretrained(self._model_id, local_files_only=True)
            self._tokeniser = AutoTokenizer.from_pretrained(self._model_id, local_files_only=True)
        except Exception as exc:  # noqa: BLE001 -- any load failure is "not available", never a crash
            raise ImportError(f"MMS voice {self._model_id!r} is not downloaded yet "
                              f"(run `voice models mms-fa`): {exc}") from exc
        self._model.eval()
        self._rate = int(self._model.config.sampling_rate)
        self._speed = config.tts_speed

    def voices(self) -> list[str]:
        return [self._model_id]

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "") -> Audio:
        """`voice` and `tone` are ignored: an MMS model IS one voice, and
        it has no expressiveness knobs. `speed` is the model's own
        `speaking_rate`, so it costs nothing and does not resample."""
        np, torch = self._np, self._torch
        rate = float(speed or self._speed or 1.0)

        def _run() -> Audio:
            # A VITS speaks faster by shortening every phoneme; the
            # attribute is the same knob Piper reaches through
            # `length_scale`, inverted.
            if rate and rate != 1.0:
                self._model.speaking_rate = rate
            gap = np.zeros(int(self._rate * _GAP_SECONDS), dtype=np.float32)
            pieces: list[np.ndarray] = []
            for sentence in (s.strip() for s in _SENTENCE.findall(text or "")):
                if not sentence:
                    continue
                inputs = self._tokeniser(sentence, return_tensors="pt")
                with torch.no_grad():
                    wave = self._model(**inputs).waveform
                pieces.append(wave.squeeze().to(torch.float32).cpu().numpy())
                pieces.append(gap)
            if not pieces:
                return Audio(pcm=b"", sample_rate=self._rate)
            audio = np.concatenate(pieces[:-1])             # no trailing silence
            pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            return Audio(pcm=pcm, sample_rate=self._rate)

        return await asyncio.to_thread(_run)


def download_mms(*, model_id: str = "", language: str = FARSI, timeout: float = 900.0) -> tuple[str, str]:
    """Fetch an MMS voice into the HuggingFace cache. `(model_id, problem)`.

    Separate from the synthesiser on purpose: fetching is a thing a
    person asks for once, and speaking must never wait on a network.
    """
    target = model_id or MMS_MODELS.get(language) or MMS_MODELS[FARSI]
    try:
        from transformers import AutoTokenizer, VitsModel
    except ImportError as exc:
        return "", f"MMS-TTS needs transformers and torch: {exc}"
    try:
        VitsModel.from_pretrained(target)
        AutoTokenizer.from_pretrained(target)
    except Exception as exc:  # noqa: BLE001 -- a download failure is a message, not a crash
        return "", f"could not fetch MMS voice {target!r}: {exc}"
    return target, ""


__all__ = ["MMS_MODELS", "MmsSynthesiser", "download_mms"]
