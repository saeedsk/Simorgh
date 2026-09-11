"""Endpointing: deciding that the person has finished speaking.

Section 4.2 of the design: silence for `endpoint_silence_ms` ends the
utterance, a hard cap at `max_utterance_s` bounds it, and (later) a
streaming transcript whose last token is a filler holds the door open.

Two detectors. Silero VAD (ONNX, the standard) when its package is
installed; otherwise an energy detector with an adaptive noise floor --
crude, honest about it in `name`, and enough for push-to-talk on a
laptop. Both are fed 30 ms frames of 16 kHz int16 PCM.
"""

from __future__ import annotations

import array
import math

from .api import SAMPLE_RATE, SAMPLE_WIDTH


class EnergyDetector:
    """Speech = RMS well above a running estimate of the noise floor."""

    name = "energy"

    def __init__(self, threshold: float = 0.5) -> None:
        # `threshold` (0..1) scales how far above the floor speech must
        # sit: 0.5 -> 6 dB, 1.0 -> 12 dB.
        self._ratio = 10 ** (0.6 * max(0.05, min(1.0, threshold)))
        self._floor: float | None = None

    def is_speech(self, frame: bytes) -> bool:
        samples = array.array("h", frame)
        if not samples:
            return False
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        if self._floor is None:
            self._floor = max(rms, 1.0)
            return False
        speech = rms > self._floor * self._ratio and rms > 200.0
        if not speech:
            # Track the floor only through silence, slowly.
            self._floor = 0.95 * self._floor + 0.05 * max(rms, 1.0)
        return speech


class SileroDetector:
    name = "silero"

    def __init__(self, threshold: float = 0.5) -> None:
        try:
            from silero_vad import load_silero_vad  # type: ignore
        except ImportError as exc:
            raise ImportError("silero-vad is not installed") from exc
        self._model = load_silero_vad(onnx=True)
        self._threshold = threshold
        self._buffer = b""

    def is_speech(self, frame: bytes) -> bool:
        try:
            import torch  # silero's API takes a tensor  # type: ignore
        except ImportError as exc:  # pragma: no cover -- silero-vad depends on torch
            raise RuntimeError("silero-vad needs torch") from exc

        self._buffer += frame
        chunk = SAMPLE_RATE * 32 // 1000 * SAMPLE_WIDTH  # silero wants 512-sample windows at 16 kHz
        if len(self._buffer) < chunk:
            return False
        window, self._buffer = self._buffer[:chunk], self._buffer[chunk:]
        samples = array.array("h", window)
        tensor = torch.tensor([s / 32768.0 for s in samples])
        return float(self._model(tensor, SAMPLE_RATE).item()) >= self._threshold


class Endpointer:
    """Feed frames; `True` once the utterance has ended.

    Ends after `silence_ms` of non-speech FOLLOWING some speech, or at
    `max_seconds` regardless. Before any speech it never ends -- a
    person who has not started yet is not finished -- which is why
    `max_seconds` exists.
    """

    def __init__(self, detector, *, silence_ms: int, max_seconds: float, frame_ms: int = 30) -> None:
        self._detector = detector
        self._silence_frames = max(1, silence_ms // frame_ms)
        self._max_frames = max(1, int(max_seconds * 1000 / frame_ms))
        self._frames = 0
        self._quiet = 0
        self.heard_speech = False
        self.ended_by = ""

    @property
    def name(self) -> str:
        return self._detector.name

    def feed(self, frame: bytes) -> bool:
        self._frames += 1
        if self._detector.is_speech(frame):
            self.heard_speech = True
            self._quiet = 0
        elif self.heard_speech:
            self._quiet += 1
            if self._quiet >= self._silence_frames:
                self.ended_by = "silence"
                return True
        if self._frames >= self._max_frames:
            self.ended_by = "max_seconds"
            return True
        return False


def open_detector(preferred: str = "auto", *, threshold: float = 0.5) -> tuple[object, str]:
    """`(detector, note)`. Never fails: the energy detector needs nothing."""
    if preferred in ("auto", "silero"):
        try:
            return SileroDetector(threshold), ""
        except ImportError as exc:
            if preferred == "silero":
                return EnergyDetector(threshold), f"silero requested but {exc}; using the energy detector"
    if preferred == "fake":
        from .fakes import FakeDetector

        return FakeDetector(), ""
    return EnergyDetector(threshold), ""


__all__ = ["EnergyDetector", "Endpointer", "SileroDetector", "open_detector"]
