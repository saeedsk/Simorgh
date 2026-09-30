"""Shenava Koochik -- Persian speech recognition in-process, through
sherpa-onnx (Reza2kn/Shenava-Koochik-v1.0-sherpa-onnx, NVIDIA FastConformer
with a CTC head, 114M parameters, CC-BY-NC-4.0).

Measured on 12 of the creator's own kept Farsi turns, 2026-09-29: 1.1 s
for all twelve against whisper large-v3's 24.3 s, and at least as right --
the Hafez line whole («اگر آن ترک شیرازی به دست دارد دل ما را»), «اعراب»
not «عرب», «سعید» not «سایید». It hears Farsi only, so language detection
stays with whisper; this replaces large-v3 only for turns already known to
be Farsi.

The model card's number post-processor (`persian_itn`) is NOT applied: it
turned «نه» ("no") into «۹» on the creator's own «چشم نه چشم». The model
spells numbers, and the brain reads spelled numbers fine.

The model wants UN-normalised log-mel; its ONNX metadata leaves
`normalize_type` empty so sherpa-onnx skips NeMo's per-feature
normalisation (the card: "with the default ... the output is garbage").
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..api import Audio, Utterance

DEFAULT_DIR = "workspace/voice/models/shenava-koochik"


class ShenavaRecogniser:
    """`transcribe(audio, language=...)` for Farsi turns. Loaded lazily, on
    the first turn or `warmup()`: 450 MB is not paid by a Sim that never
    hears Farsi."""

    name = "shenava"

    def __init__(self, model_dir: str | Path = DEFAULT_DIR, *, threads: int = 4) -> None:
        self._dir = Path(model_dir)
        if not (self._dir / "model.onnx").is_file() or not (self._dir / "tokens.txt").is_file():
            raise ImportError(f"Shenava needs model.onnx and tokens.txt in {self._dir}")
        try:
            import sherpa_onnx  # noqa: F401 -- optional adapter
        except ImportError as exc:
            raise ImportError("Shenava runs on sherpa-onnx (`pip install sherpa-onnx`)") from exc
        self._threads = threads
        self._recogniser = None
        self._lock = asyncio.Lock()
        #: None: a CTC decode gives no whisper-style mean log probability.
        self.last_logprob: float | None = None
        self.running = False

    def _load(self):
        if self._recogniser is None:
            try:
                import sherpa_onnx
            except ImportError as exc:   # checked in __init__; said again rather than crashing a turn
                raise RuntimeError("sherpa-onnx is no longer installed") from exc
            self._recogniser = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=str(self._dir / "model.onnx"), tokens=str(self._dir / "tokens.txt"),
                num_threads=self._threads)
            self.running = True
        return self._recogniser

    async def warmup(self) -> None:
        await asyncio.to_thread(self._load)

    def _decode(self, audio: Audio) -> str:
        import array

        recogniser = self._load()
        samples = array.array("h")
        samples.frombytes(audio.pcm[: len(audio.pcm) - len(audio.pcm) % 2])
        stream = recogniser.create_stream()
        stream.accept_waveform(audio.sample_rate, [s / 32768.0 for s in samples])
        recogniser.decode_stream(stream)
        return " ".join(str(stream.result.text or "").split())

    async def transcribe(self, audio: Audio, *, language: str = "", route: bool = True) -> Utterance:
        if audio.seconds < 0.1:
            return Utterance(text="", confidence=0.0, seconds=audio.seconds, engine=self.name, language="fa")
        async with self._lock:
            text = await asyncio.to_thread(self._decode, audio)
        return Utterance(text=text, confidence=1.0, seconds=audio.seconds, engine=self.name, language="fa")

    async def close(self) -> None:
        self._recogniser = None
        self.running = False


__all__ = ["DEFAULT_DIR", "ShenavaRecogniser"]
