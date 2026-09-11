"""Deterministic stand-ins for every engine and device, for tests and for
`[voice] stt = "fake"` on a machine with no audio at all."""

from __future__ import annotations

from .api import SAMPLE_RATE, SAMPLE_WIDTH, Audio, Utterance


def silence(seconds: float) -> Audio:
    return Audio(b"\x00" * int(seconds * SAMPLE_RATE * SAMPLE_WIDTH))


class FakeDetector:
    """Every frame is speech until `speech_frames` have passed."""

    name = "fake"

    def __init__(self, speech_frames: int = 10) -> None:
        self._left = speech_frames

    def is_speech(self, frame: bytes) -> bool:
        self._left -= 1
        return self._left >= 0


class FakeMicrophone:
    name = "fake"

    def __init__(self, audio: Audio | None = None) -> None:
        self._audio = audio or silence(1.0)
        self.captures = 0

    async def capture(self, *, max_seconds: float, endpointer) -> Audio:
        self.captures += 1
        return self._audio


class FakeSpeaker:
    name = "fake"

    def __init__(self) -> None:
        self.played: list[Audio] = []

    async def play(self, audio: Audio) -> None:
        self.played.append(audio)


class FakeRecogniser:
    name = "fake"

    def __init__(self, text: str = "hello sim", confidence: float = 0.95) -> None:
        self.text = text
        self.confidence = confidence
        self.heard: list[Audio] = []

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        self.heard.append(audio)
        return Utterance(text=self.text, confidence=self.confidence, seconds=audio.seconds, engine=self.name)


class FakeSynthesiser:
    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def voices(self) -> list[str]:
        return ["fake"]

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        self.spoken.append(text)
        return silence(max(0.1, len(text) / 20.0))


__all__ = ["FakeDetector", "FakeMicrophone", "FakeRecogniser", "FakeSpeaker", "FakeSynthesiser", "silence"]
