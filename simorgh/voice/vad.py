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

    def raise_floor(self, rms: float) -> None:
        """Treat `rms` as silence from now on. Used while Sim speaks:
        the microphone hears the speakers, and that echo must not count
        as a person talking."""
        self._floor = max(self._floor or 0.0, rms, 1.0)

    def set_ratio(self, ratio: float) -> None:
        """How many times louder than the floor speech must be."""
        self._ratio = max(1.1, float(ratio))

    @staticmethod
    def rms(frame: bytes) -> float:
        samples = array.array("h", frame)
        return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0

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
        reset = getattr(self._model, "reset_states", None)
        if reset is not None:
            reset()
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


class CompositeDetector:
    """Speech only if the voice detector says so AND the level gate does.

    For barge-in. Silero knows a voice from a keyboard, a clap, a chair
    -- the creator, 2026-09-11: "if sim is talking and I'm typing or
    clapping, that should not interrupt sim" -- but Sim's own voice
    through the speakers is a voice too, so on its own it would fire on
    every echo. The level gate, calibrated to that echo, is what says
    "louder than Sim". Both, or it is not a person cutting in.
    """

    def __init__(self, voice, level) -> None:
        self._voice = voice
        self._level = level
        self.name = f"{voice.name}+{level.name}"

    def is_speech(self, frame: bytes) -> bool:
        # Evaluate both every frame: the level gate's floor only learns
        # from frames it sees, and Silero's state must follow the audio.
        loud = self._level.is_speech(frame)
        voiced = self._voice.is_speech(frame)
        return loud and voiced

    def raise_floor(self, rms: float) -> None:
        raise_floor = getattr(self._level, "raise_floor", None)
        if raise_floor is not None:
            raise_floor(rms)

    def set_ratio(self, ratio: float) -> None:
        set_ratio = getattr(self._level, "set_ratio", None)
        if set_ratio is not None:
            set_ratio(ratio)

    @staticmethod
    def rms(frame: bytes) -> float:
        return EnergyDetector.rms(frame)


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


class BargeInEndpointer(Endpointer):
    """An endpointer that also notices a person cutting in.

    Runs while Sim is speaking. The first `calibrate_frames` frames are
    taken to be what the microphone hears of Sim's own voice through
    the speakers, and the detector's floor is raised to that level --
    the cheapest echo cancellation there is, and enough for a laptop:
    a person at the keyboard is louder at the mic than the speakers'
    spill. Then `speech_ms` of continuous speech calls `on_barge_in`
    once, and the utterance carries on to its normal end, so the words
    that interrupted Sim are the start of the next turn, not lost.
    """

    def __init__(self, detector, *, silence_ms: int, max_seconds: float, speech_ms: int = 400,
                 on_barge_in=None, calibrate_frames: int = 30, ratio: float | None = None,
                 frame_ms: int = 30) -> None:
        super().__init__(detector, silence_ms=silence_ms, max_seconds=max_seconds, frame_ms=frame_ms)
        self._need = max(1, speech_ms // frame_ms)
        self._run = 0
        self._on_barge_in = on_barge_in
        self._calibrate = calibrate_frames
        self._seen = 0
        self.barged = False
        if ratio is not None and hasattr(detector, "set_ratio"):
            detector.set_ratio(ratio)

    def feed(self, frame: bytes) -> bool:
        self._seen += 1
        if self._seen <= self._calibrate:
            raise_floor = getattr(self._detector, "raise_floor", None)
            if raise_floor is not None:
                raise_floor(self._detector.rms(frame) if hasattr(self._detector, "rms") else 0.0)
            self._frames += 1
            return False
        speech = self._detector.is_speech(frame)
        if speech:
            self._run += 1
            if not self.barged and self._run >= self._need:
                self.barged = True
                self.heard_speech = True
                if self._on_barge_in is not None:
                    self._on_barge_in()
        else:
            self._run = 0
        if not self.barged:
            # Nothing decisive yet; keep listening for as long as the
            # playback (the caller's `max_seconds`) allows.
            self._frames += 1
            if self._frames >= self._max_frames:
                self.ended_by = "max_seconds"
                return True
            return False
        # A person is talking over Sim: from here on, an ordinary utterance.
        self._frames += 1
        if speech:
            self._quiet = 0
        else:
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


__all__ = ["BargeInEndpointer", "CompositeDetector", "EnergyDetector", "Endpointer", "SileroDetector", "open_detector"]
