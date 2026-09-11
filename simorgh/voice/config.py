"""`[voice]` in `simorgh.toml` (docs/plans/voice-design.md section 3).

Every key here is read by something; `tests/simorgh/test_every_subsystem_
reads_its_config.py` and the half-wired scanner both hold this package to
that. Keys the design lists for surfaces not yet built (Wyoming, the
PWA, Alexa) are NOT declared yet -- a settable key nothing reads is the
bug shape this project keeps paying for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    # Engines. "auto" = the best one whose package or binary is present;
    # never a cloud engine (section 0: local first for speech).
    stt: str = "auto"                  # auto | faster_whisper | whisper_cli | fake
    stt_model: str = "large-v3-turbo"  # faster_whisper model name; whisper_cli: a ggml file name or path
    stt_language: str = "en"           # "" = detect
    stt_compute: str = "auto"          # faster_whisper: int8 | float16 | auto
    tts: str = "auto"                  # auto | kokoro | say | fake
    tts_voice: str = "af_heart"        # Kokoro voice id; a `say -v` voice name for `say`
    tts_speed: float = 1.0
    # Endpointing (section 4.2).
    vad: str = "auto"                  # auto | silero | energy | fake
    vad_threshold: float = 0.5
    endpoint_silence_ms: int = 700
    max_utterance_s: float = 30.0
    # Push-to-talk until the wake word is built: `voice listen` and the
    # `space` key in `sim voice`. "" = push-to-talk only.
    wake_word: str = ""
    follow_up_window_s: float = 6.0
    barge_in: bool = True
    # How long a spoken turn may wait for Sim's answer before the
    # pipeline says so aloud instead of nothing.
    reply_timeout_s: float = 60.0
    # Confidence below which Sim asks "did you say ...?" instead of
    # acting (the never-guess rule).
    min_confidence: float = 0.6
    # Privacy (section 6).
    keep_audio: bool = False
    audio_dir: str = "workspace/voice/audio"
    keep_transcripts: bool = True
    # The device name a turn is recorded under (satellites will bring
    # their own).
    device: str = "laptop"
    # Where whisper.cpp / Kokoro models live when a model is a bare name.
    model_dir: str = "workspace/voice/models"
    # Capture and playback paths: auto | sounddevice | ffmpeg | fake, and
    # auto | sounddevice | command | fake.
    microphone: str = "auto"
    speaker: str = "auto"
    # What the fake recogniser "hears", for tests and audio-less machines.
    fake_transcript: str = "hello sim"

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object] | None) -> "Config":
        if not mapping:
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in dict(mapping).items() if k in known})


__all__ = ["Config"]
