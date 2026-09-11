"""The shapes of the voice subsystem, and the protocols its engines meet.

Every engine is optional and probed (`service.py`): a machine with none
of them installed still boots, still answers `voice status`, and refuses
`voice on` by name -- "no speech recogniser: pip install faster-whisper,
or brew install whisper-cpp". The fakes in `fakes.py` meet the same
protocols, which is what lets the whole pipeline be tested without a
microphone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

#: PCM the pipeline works in end to end: 16 kHz mono 16-bit, the shape
#: every recogniser here takes natively.
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes; int16


@dataclass(frozen=True)
class Audio:
    """A run of PCM samples. `pcm` is little-endian int16 bytes."""

    pcm: bytes
    sample_rate: int = SAMPLE_RATE

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (SAMPLE_WIDTH * CHANNELS * self.sample_rate)


@dataclass(frozen=True)
class Utterance:
    """What the recogniser heard."""

    text: str
    confidence: float  # 0..1; engines that give none report 1.0 and say so in `engine`
    seconds: float     # of audio
    engine: str
    language: str = ""


@dataclass(frozen=True)
class VoiceTurn:
    """One spoken exchange, as the ledger records it (`voice:turns`)."""

    session_id: str
    device: str
    speaker: str
    heard: str
    confidence: float
    said: str
    heard_at: float
    answered_at: float
    engine_stt: str
    engine_tts: str


@dataclass
class VoiceState:
    """What `voice status` reports."""

    enabled: bool = False
    listening: bool = False
    muted: bool = False
    speaking: bool = False
    stt: str = ""          # engine name, or "" when none
    tts: str = ""
    device: str = "laptop"
    turns: int = 0
    last_heard: str = ""
    last_said: str = ""
    problems: list[str] = field(default_factory=list)


class Recogniser(Protocol):
    name: str

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance: ...


class Synthesiser(Protocol):
    name: str

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio: ...

    def voices(self) -> list[str]: ...


class Microphone(Protocol):
    """Captures one utterance: records until the endpointer says stop
    (or `max_seconds`), and returns the audio."""

    name: str

    async def capture(self, *, max_seconds: float, endpointer) -> Audio: ...


class Speaker(Protocol):
    name: str

    async def play(self, audio: Audio) -> None: ...

    async def stop(self) -> None:
        """Cut playback short. `play` returns once it has."""
        ...


__all__ = ["Audio", "CHANNELS", "Microphone", "Recogniser", "SAMPLE_RATE", "SAMPLE_WIDTH", "Speaker",
           "Synthesiser", "Utterance", "VoiceState", "VoiceTurn"]
