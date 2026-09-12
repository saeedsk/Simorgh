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
    # "" = detect. Pinned to "en" until 2026-09-11, which made Farsi
    # unrecognisable: whisper was told every utterance was English.
    # `large-v3-turbo` detects the language reliably (measured on a
    # Persian sample: exact transcript, 1.3-2.0 s with Metal); `base.en`
    # cannot hear Farsi at all -- `voice models large-v3-turbo`.
    stt_language: str = ""
    stt_compute: str = "auto"          # faster_whisper: int8 | float16 | auto
    tts: str = "auto"                  # auto | kokoro | piper | say | fake
    tts_voice: str = "af_jessica"      # Kokoro voice id (the creator's pick); a `say -v` name for `say`
    tts_speed: float = 1.0
    # A reply is spoken by the engine for ITS language (voice/lang.py):
    # Kokoro has no Persian and read Farsi as English gibberish
    # (2026-09-11). Off = the one engine above speaks everything.
    tts_by_language: bool = True
    tts_farsi_voice: str = "fa_IR-amir-medium"  # a Piper voice id; `voice models piper-fa` fetches it
    # Endpointing (section 4.2).
    vad: str = "auto"                  # auto | silero | energy | fake
    vad_threshold: float = 0.5
    endpoint_silence_ms: int = 700
    max_utterance_s: float = 30.0
    # Push-to-talk until the wake word is built: `voice listen` and the
    # `space` key in `sim voice`. "" = push-to-talk only.
    wake_word: str = ""
    follow_up_window_s: float = 6.0
    # Speech during playback stops playback (section 4.1). The mic stays
    # open while Sim speaks; this much continuous speech, measured
    # against the level the mic hears of Sim's own voice, is a person
    # cutting in. Below it is an echo, a cough, a chair.
    barge_in: bool = True
    # Raised after the creator found Sim stopping when no one spoke
    # (2026-09-11): two thirds of a second of speech, not a third, and
    # nearly three times the loudest echo, not twice. With continuous
    # echo tracking (`vad.BargeInEndpointer`) these are the belt to its
    # braces -- a person cutting in clears them easily; Sim's own voice
    # and a stray clip do not.
    barge_in_speech_ms: int = 650
    # The first stretch of each reply is spent learning how loud Sim's own
    # voice is at the microphone; nothing can interrupt during it. Kokoro
    # replies open near-silent, so a short window learnt silence and Sim
    # then interrupted itself with its own voice and answered its own
    # reply (the creator's screen, 2026-09-11). Then a person must be
    # this many times louder than the loudest echo heard (2.0 = 6 dB).
    barge_in_calibrate_ms: int = 1200
    barge_in_ratio: float = 2.8
    # Acoustic echo cancellation for barge-in (voice/aec.py). When on,
    # the barge decision is made on the residual after Sim's own voice
    # -- known exactly, it is what we are playing -- is subtracted from
    # what the mic hears, so a person is detected by being ABSENT from
    # the reference, not by being louder than Sim. OFF by default: a
    # simulated echo is not a promise about a real room, and the level
    # gate above is the safe fallback. `voice barge aec` toggles it live.
    aec: bool = True
    aec_taps: int = 1024
    aec_mu: float = 0.3
    aec_residual_threshold: float = 0.02  # a floor; the voice check on the residual is the real gate
    # -- the conversation (voice/session.py, voice/turns.py, voice/planner.py; 2026-09-11).
    # The design's VoiceSettings, by their names here: `speaking_rate` is
    # `tts_speed`, `interrupt_on_user_speech` is `barge_in`, `end_of_turn_
    # silence_ms` is `endpoint_silence_ms`, `tts_provider` is `tts`,
    # `stt_provider` is `stt`, `voice_id` is `tts_voice`, `language` is
    # `stt_language`.
    volume: float = 1.0                # playback gain, 0.2 .. 2.0
    auto_listen: bool = True           # after a reply, listen again without being asked
    vad_sensitivity: str = "balanced"  # low | balanced | high (vad.threshold_for); overrides vad_threshold
    min_speech_ms: int = 250           # shorter than this is a breath or a chair, not a turn
    max_turn_ms: int = 30000           # a turn is finalised at this length regardless
    semantic_silence_factor: float = 0.6  # a finished sentence needs this much of the silence
    stt_partials: bool = True          # provisional transcripts while the person is still talking
    stt_partial_every_ms: int = 1500
    connectors: bool = True            # the planner's rare "Okay," / "Yeah," lead-ins
    max_spoken_sentences: int = 6      # longer answers are cut here and say there is more on screen
    tts_lookahead: int = 2             # pieces synthesised ahead of playback; more = slower to cancel
    ack_after_ms: int = 900            # a slow answer to a request gets a spoken "Okay," meanwhile
    diagnostics: bool = True           # per-turn latencies in `voice:turns` and `voice status`
    # Speak every reply Sim gives, including replies to TYPED turns.
    # The creator asked Sim itself for this on 2026-09-10 ("add TTS
    # output ... voice af_jessica"), and Sim built a second TTS path
    # inside the interface for it; this is that ask, on the one path.
    speak_replies: bool = False
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
