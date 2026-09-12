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
    # Per-turn diagnostics (voice/session.py): latencies in seconds
    # (`stt`, `llm`, `first_audio`, `interruption`), `underruns`,
    # `dropped`, `interrupted`. Metadata only, never text.
    metrics: dict = field(default_factory=dict)


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


# -- the conversational pipeline's shapes (2026-09-11) ----------------------------------------
#
# The streaming pipeline (voice/session.py) is built from independently
# replaceable parts speaking these: frames go in, events come out, and
# no part knows which engine is behind another.


@dataclass(frozen=True)
class TranscriptEvent:
    """What the recogniser has heard so far. A `partial` is provisional
    and replaced by the next one; a `final` closes the utterance."""

    kind: str                  # "partial" | "final"
    text: str
    turn_id: int
    confidence: float = 1.0
    language: str = ""
    audio_seconds: float = 0.0
    engine: str = ""


@dataclass(frozen=True)
class VadEvent:
    """One frame's verdict. `speech_start`/`speech_end` fire once at the
    edges; `speech`/`silence` every frame in between."""

    kind: str                  # "speech_start" | "speech" | "silence" | "speech_end"
    speech_ms: int = 0         # continuous speech so far
    silence_ms: int = 0        # continuous silence so far
    level: float = 0.0


@dataclass(frozen=True)
class AudioChunk:
    """One piece of a spoken reply, in playback order. `request_id` is
    the response it belongs to: a chunk from an old response can never
    play in a new turn."""

    pcm: bytes
    sample_rate: int
    request_id: str
    seq: int
    final: bool = False
    text: str = ""
    pause_ms: int = 0

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (SAMPLE_WIDTH * CHANNELS * self.sample_rate)


@dataclass(frozen=True)
class TtsRequest:
    request_id: str
    pieces: tuple[tuple[str, int], ...]   # (text, pause_ms after it)
    voice: str = ""
    speed: float = 1.0
    gain: float = 1.0   # loudness multiplier on the synthesised PCM (voice/delivery.py)


@dataclass(frozen=True)
class PlaybackState:
    state: str                 # "started" | "chunk" | "finished" | "stopped"
    request_id: str
    seq: int = -1


class SpeechToTextProvider(Protocol):
    name: str

    def start_stream(self, frames, *, turn_id: int, language: str = ""):
        """`frames`: an async iterable of PCM frames. Yields `TranscriptEvent`s."""
        ...

    async def stop(self) -> None: ...


class TextToSpeechProvider(Protocol):
    name: str

    async def warmup(self) -> float: ...

    def synthesise_stream(self, request: TtsRequest):
        """Yields `AudioChunk`s as they are ready."""
        ...

    async def cancel(self, request_id: str) -> None: ...

    def list_voices(self) -> list[str]: ...


class VoiceActivityDetector(Protocol):
    def process(self, frame: bytes) -> VadEvent: ...


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


__all__ = ["Audio", "AudioChunk", "CHANNELS", "Microphone", "PlaybackState", "Recogniser", "SAMPLE_RATE",
           "SAMPLE_WIDTH", "Speaker", "SpeechToTextProvider", "Synthesiser", "TextToSpeechProvider",
           "TranscriptEvent", "TtsRequest", "Utterance", "VadEvent", "VoiceActivityDetector", "VoiceState",
           "VoiceTurn"]
