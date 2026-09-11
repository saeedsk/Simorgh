"""faster-whisper (CTranslate2), the design's primary recogniser."""

from __future__ import annotations

import asyncio

from ..api import Audio, Utterance


class FasterWhisperRecogniser:
    name = "faster_whisper"

    def __init__(self, config, *, repo_root=None) -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise ImportError("faster-whisper is not installed") from exc
        compute = "int8" if config.stt_compute == "auto" else config.stt_compute
        self._model = WhisperModel(config.stt_model, compute_type=compute)
        self._language = config.stt_language or None
        self.name = f"faster_whisper:{config.stt_model}"

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover -- faster-whisper depends on numpy
            raise RuntimeError("faster-whisper needs numpy") from exc

        samples = np.frombuffer(audio.pcm, dtype=np.int16).astype(np.float32) / 32768.0

        def _run():
            segments, info = self._model.transcribe(samples, language=language or self._language, beam_size=5)
            segments = list(segments)
            text = " ".join(s.text.strip() for s in segments).strip()
            # Whisper's per-segment log-probabilities, folded to 0..1.
            probs = [float(np.exp(s.avg_logprob)) for s in segments if s.avg_logprob is not None]
            confidence = min(1.0, sum(probs) / len(probs)) if probs else (1.0 if text else 0.0)
            return text, confidence, getattr(info, "language", "") or ""

        text, confidence, lang = await asyncio.to_thread(_run)
        return Utterance(text=text, confidence=confidence, seconds=audio.seconds, engine=self.name, language=lang)
