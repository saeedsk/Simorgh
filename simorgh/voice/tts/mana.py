"""Mana -- a fast Farsi voice: Piper trained on Mana-TTS (MahtaFetrat/
Mana-Persian-Piper, 114 hours of one Persian speaker, MIT), with the
ezafe its author recommends and the creator's pick of delivery.

Chosen by ear, 2026-09-29, as the everyday Farsi voice: of the fast ones
(sherpa-onnx musa/khadijah, plain Mana, Mana with ezafe) the creator liked
"ezafe-slow-bright" best -- "not ideal", and about forty times faster than
real time where Chatterbox Persian is 0.4x, so a reply starts in well under
a second instead of 11-16 s.

What each part is for:
- **Ezafe.** Piper's eSpeak phonemes never say the linking -e: «کتاب قرمز»
  came out as two words where Persian says «کتابِ قرمز». The author's paper
  (Fetrat et al., arXiv 2512.08006) predicts it per word with a small ALBERT
  (abreza/persian-ezafe-albert, the quantized ONNX) and appends "e" (or
  "je" after i) at confidence above 0.7 -- done the same way here, with the
  `tokenizers` library rather than `transformers`.
- **Slow.** `length_scale` 1.08.
- **Bright.** A +4 dB high shelf at 3 kHz. Measured: that brings the voice's
  2-4 kHz and >4 kHz energy level with a real recording (Roya's clip).
  A speech super-resolution pass (MossFormer2 48 kHz) was tried too: 3.4 s
  for a 4 s sentence, so it is not used.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from pathlib import Path

from ..api import Audio

ENGINE = "mana"
DEFAULT_MODEL = "fa_IR-mana-medium"
DEFAULT_EZAFE = "workspace/voice/models/persian-ezafe-albert"
LENGTH_SCALE = 1.08
SHELF_HZ, SHELF_DB = 3000.0, 4.0
EZAFE_CONFIDENCE = 0.7
SENTENCE_PAUSE_S = 0.25
_NO_EZAFE_AFTER = set('.,!?؟،؛«»:;')
_SENTENCES = re.compile(r"(?<=[.!?؟])\s+")


def _shelf(sample_rate: int):
    """RBJ high-shelf biquad coefficients."""
    import math

    a = 10 ** (SHELF_DB / 40)
    w0 = 2 * math.pi * SHELF_HZ / sample_rate
    alpha = math.sin(w0) / 2 * math.sqrt(2)
    cos = math.cos(w0)
    b = [a * ((a + 1) + (a - 1) * cos + 2 * math.sqrt(a) * alpha),
         -2 * a * ((a - 1) + (a + 1) * cos),
         a * ((a + 1) + (a - 1) * cos - 2 * math.sqrt(a) * alpha)]
    den = [(a + 1) - (a - 1) * cos + 2 * math.sqrt(a) * alpha,
           2 * ((a - 1) - (a + 1) * cos),
           (a + 1) - (a - 1) * cos - 2 * math.sqrt(a) * alpha]
    return [x / den[0] for x in b], [x / den[0] for x in den]


class ManaSynthesiser:
    name = ENGINE

    def __init__(self, config) -> None:
        try:
            import numpy
            import onnxruntime
            from piper import PiperVoice
            from piper.config import SynthesisConfig
            from piper.phonemize_espeak import EspeakPhonemizer
            from scipy.signal import lfilter
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise ImportError(f"the Mana voice needs piper-tts, onnxruntime, tokenizers and scipy: {exc}") from exc
        model_dir = Path(config.model_dir)
        model = model_dir / f"{str(config.tts_farsi_mana_model or DEFAULT_MODEL)}.onnx"
        if not (model.is_file() and model.with_name(model.name + ".json").is_file()):
            raise ImportError(f"the Mana voice is not at {model} (MahtaFetrat/Mana-Persian-Piper)")
        self._np, self._lfilter, self._synthesis_config = numpy, lfilter, SynthesisConfig
        self._piper = PiperVoice.load(str(model))
        self._espeak = EspeakPhonemizer()
        self._speed = float(config.tts_speed or 1.0)
        # Ezafe is an improvement, not a requirement: without its model the
        # voice still speaks, as plain Piper does.
        self._ezafe = None
        ezafe_dir = Path(str(config.tts_farsi_ezafe_model or DEFAULT_EZAFE))
        if (ezafe_dir / "model_quantized.onnx").is_file() and (ezafe_dir / "tokenizer.json").is_file():
            self._tokenizer = Tokenizer.from_file(str(ezafe_dir / "tokenizer.json"))
            self._tokenizer.no_padding()
            self._ezafe = onnxruntime.InferenceSession(str(ezafe_dir / "model_quantized.onnx"))

    def voices(self) -> list[str]:
        return [DEFAULT_MODEL]

    def _needs_ezafe(self, words: list[str]) -> list[bool]:
        np = self._np
        if self._ezafe is None or not words:
            return [False] * len(words)
        enc = self._tokenizer.encode(words, is_pretokenized=True)
        arrays = {"input_ids": np.array([enc.ids], dtype=np.int64),
                  "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
                  "token_type_ids": np.array([enc.type_ids], dtype=np.int64)}
        feeds = {i.name: arrays[i.name] for i in self._ezafe.get_inputs() if i.name in arrays}
        logits = self._ezafe.run(None, feeds)[0][0]
        probs = np.exp(logits - logits.max(-1, keepdims=True))
        probs /= probs.sum(-1, keepdims=True)
        out = [False] * len(words)
        seen = None
        for i, word in enumerate(enc.word_ids):
            if word is not None and word != seen and word < len(words):
                out[word] = bool(probs[i].argmax()) and float(probs[i].max()) > EZAFE_CONFIDENCE
                seen = word
        return out

    def phonemes(self, sentence: str) -> list[str]:
        """eSpeak phonemes word by word, with the ezafe the model predicts."""
        words = sentence.split()
        ezafe = self._needs_ezafe(words)
        parts = []
        for i, (word, needs) in enumerate(zip(words, ezafe)):
            sound = "".join(sum(self._espeak.phonemize("fa", word), []))
            if needs and word[-1] not in _NO_EZAFE_AFTER and i < len(words) - 1:
                if sound.endswith(("i", "iː")):
                    sound += "je"
                elif not sound.endswith(("e", "eː")):
                    sound += "e"
            parts.append(sound)
        return list(unicodedata.normalize("NFC", " ".join(parts)))

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "") -> Audio:
        def _run() -> Audio:
            np, lfilter, SynthesisConfig = self._np, self._lfilter, self._synthesis_config
            rate = self._piper.config.sample_rate
            length = LENGTH_SCALE / ((speed or 1.0) * self._speed or 1.0)
            pause = np.zeros(int(rate * SENTENCE_PAUSE_S), dtype=np.float32)
            pieces = []
            for sentence in (s for s in _SENTENCES.split(text.strip()) if s.strip()):
                ids = self._piper.phonemes_to_ids(self.phonemes(sentence))
                audio = self._piper.phoneme_ids_to_audio(ids, SynthesisConfig(length_scale=length))
                pieces.extend([np.asarray(audio, dtype=np.float32), pause])
            if not pieces:
                return Audio(pcm=b"", sample_rate=rate)
            wave = np.concatenate(pieces[:-1])
            b, a = _shelf(rate)
            wave = lfilter(b, a, wave)
            peak = float(np.max(np.abs(wave))) or 1.0
            wave = wave / max(1.0, peak / 0.95)          # the shelf may lift peaks past full scale
            return Audio(pcm=(wave * 32767).astype("<i2").tobytes(), sample_rate=rate)

        return await asyncio.to_thread(_run)


__all__ = ["DEFAULT_EZAFE", "DEFAULT_MODEL", "ENGINE", "ManaSynthesiser"]
