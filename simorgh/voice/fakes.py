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
    """Hands its audio to the endpointer frame by frame, the way a real
    microphone does, so barge-in and endpointing can be exercised; a
    `frame_delay` makes the frames arrive over time."""

    name = "fake"

    def __init__(self, audio: Audio | None = None, *, frame_delay: float = 0.0) -> None:
        self._audio = audio or silence(1.0)
        self._delay = frame_delay
        self.captures = 0

    async def capture(self, *, max_seconds: float, endpointer) -> Audio:
        import asyncio

        self.captures += 1
        frame = SAMPLE_RATE * 30 // 1000 * SAMPLE_WIDTH
        pcm = self._audio.pcm
        for i in range(0, len(pcm), frame):
            if self._delay:
                await asyncio.sleep(self._delay)
            if endpointer.feed(pcm[i:i + frame]):
                return Audio(pcm[:i + frame], self._audio.sample_rate)
        return self._audio

    async def stream(self, *, max_seconds: float = 0.0):
        """The audio, frame by frame, then silence for as long as anyone
        keeps reading -- a fake room that goes quiet after the person
        has spoken. `feed(audio)` queues more speech for later."""
        import asyncio

        frame = SAMPLE_RATE * 30 // 1000 * SAMPLE_WIDTH
        self._queue = getattr(self, "_queue", [])
        self._queue.insert(0, self._audio.pcm)
        served = 0
        limit = int(max_seconds * SAMPLE_RATE) * SAMPLE_WIDTH if max_seconds else 0
        while True:
            pcm = self._queue.pop(0) if self._queue else b"\x00" * frame * 10
            for i in range(0, len(pcm), frame):
                if self._delay:
                    await asyncio.sleep(self._delay)
                else:
                    await asyncio.sleep(0)
                chunk = pcm[i:i + frame]
                served += len(chunk)
                yield chunk
                if limit and served >= limit:
                    return

    def feed(self, audio: Audio) -> None:
        self._queue = getattr(self, "_queue", [])
        self._queue.append(audio.pcm)


class FakeSpeaker:
    """Records what was played; with `realtime=True` it takes as long
    as the audio lasts, and `stop()` cuts it short."""

    name = "fake"

    def __init__(self, *, realtime: bool = False) -> None:
        self.played: list[Audio] = []
        self.stopped = 0
        self._realtime = realtime
        self._stop = None

    async def play(self, audio: Audio) -> None:
        import asyncio

        self.played.append(audio)
        if not self._realtime:
            return
        self._stop = asyncio.Event()
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=audio.seconds)
        except asyncio.TimeoutError:
            pass
        finally:
            self._stop = None

    async def stop(self) -> None:
        self.stopped += 1
        if self._stop is not None:
            self._stop.set()


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
        self.speeds: list[float] = []  # the speed each piece was asked for (voice/delivery.py)

    def voices(self) -> list[str]:
        return ["fake"]

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        self.spoken.append(text)
        self.speeds.append(speed)
        return silence(max(0.1, len(text) / 20.0))


__all__ = ["FakeDetector", "FakeMicrophone", "FakeRecogniser", "FakeSpeaker", "FakeSynthesiser", "silence"]
