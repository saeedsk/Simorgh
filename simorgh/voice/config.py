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
    # Listen on boot. "auto" (the default since 2026-09-11, the creator:
    # "the voice should be enabled by default when we start sim") means
    # on when Sim is started by a person at a terminal and a real
    # microphone opens; off under tests, in a pipe, or with a fake
    # microphone. `true`/`false` say so outright.
    enabled: bool | str = "auto"
    # Engines. "auto" = the best one whose package or binary is present;
    # never a cloud engine (section 0: local first for speech).
    stt: str = "auto"                  # auto | faster_whisper | whisper_server | whisper_cli | fake
    stt_server_port: int = 0           # whisper_server's port; 0 = a free one
    stt_model: str = "large-v3-turbo"  # faster_whisper model name; whisper_cli: a ggml file name or path
    # "" = detect. Pinned to "en" until 2026-09-11, which made Farsi
    # unrecognisable: whisper was told every utterance was English.
    # `large-v3-turbo` detects the language reliably (measured on a
    # Persian sample: exact transcript, 1.3-2.0 s with Metal); `base.en`
    # cannot hear Farsi at all -- `voice models large-v3-turbo`.
    stt_language: str = ""
    # The languages this house speaks. Whisper, left to detect, called a
    # line Turkish and Sim answered in Turkish (live 2026-09-13); a turn
    # heard in a language outside this list is most likely noise and is
    # not answered. "" allows any.
    stt_languages: str = "en,fa"
    stt_compute: str = "auto"          # faster_whisper: int8 | float16 | auto
    tts: str = "auto"                  # auto | kokoro | piper | say | chatterbox | miso | fake
    tts_voice: str = "af_jessica"      # Kokoro voice id (the creator's pick); a `say -v` name for `say`
    tts_speed: float = 1.1     # the creator, 2026-09-13: "you speak too slow, speak fast" -- playful's pace, always
    # A reply is spoken by the engine for ITS language (voice/lang.py):
    # Kokoro has no Persian and read Farsi as English gibberish
    # (2026-09-11). Off = the one engine above speaks everything.
    tts_by_language: bool = True
    tts_farsi_voice: str = "fa_IR-amir-medium"  # a Piper voice id; `voice models piper-fa` fetches it
    # Endpointing (section 4.2).
    vad: str = "auto"                  # auto | silero | energy | fake
    vad_threshold: float = 0.5
    # 700 ms until 2026-09-11; a person who pauses after a sentence to
    # find the next one was cut off, and Sim's "Aha" landed on top of
    # their next word ("sim is cutting other people too much").
    endpoint_silence_ms: int = 1000
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
    barge_in_speech_ms: int = 450     # "stop" is short: 650 let the creator say it twenty times unheard (2026-09-13)
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
    # Where Sim's voice comes out: this machine's speaker, the TV page
    # (each piece of a reply travels as a ledger blob the page plays --
    # the creator, 2026-09-12: "route its voice to TV"), or both. With
    # "tv" the local player is silent but keeps time, so turns and the
    # echo gate behave as they do; `tv_audio_lag_s` is how much later
    # the TV's sound reaches the microphone than the local player would.
    output: str = "laptop"             # laptop | tv | both
    tv_audio_lag_s: float = 2.5
    auto_listen: bool = True           # after a reply, listen again without being asked
    # "high" since 2026-09-13: Ira, nine, spoke to Sim twice and neither
    # became a turn -- a child's voice from across the room sits under
    # the balanced bar. The model's QUIET handles what the looser bar
    # lets through; `voice set vad_sensitivity balanced` restores it.
    vad_sensitivity: str = "high"      # low | balanced | high (vad.threshold_for); overrides vad_threshold
    min_speech_ms: int = 250           # shorter than this is a breath or a chair, not a turn
    max_turn_ms: int = 30000           # a turn is finalised at this length regardless
    # How long a ready reply waits while the microphone hears speech that
    # may be a new turn. With children and a TV in the room the microphone
    # hears speech all the time, and replies sat 2-6 s before the first
    # sound (measured 2026-09-13, `before_lock`). If it really is a new
    # turn, that turn supersedes this reply anyway (turns.py).
    hold_reply_max_s: float = 1.5
    semantic_silence_factor: float = 0.75  # a finished sentence needs this much of the silence
    stt_partials: bool = True          # provisional transcripts while the person is still talking
    stt_partial_every_ms: int = 1500
    connectors: bool = True            # the planner's rare "Okay," / "Yeah," lead-ins
    max_spoken_sentences: int = 3      # longer answers are cut here and say there is more on screen
    tts_lookahead: int = 2             # pieces synthesised ahead of playback; more = slower to cancel
    # The moment the person's turn ends, before the recogniser has even
    # finished, Sim says a short "Aha." / "Let me check." / "Sure, one
    # sec." (voice/backchannel.py) and only then goes to think; a person
    # is never left wondering whether they were heard. `still_after_s`
    # later, with no answer yet, one more ("Still on it.").
    # ... but not on every turn, and not at once. A sound after every
    # sentence, and another every few seconds, is a tic, not a listener
    # (the creator, 2026-09-11: "like a person with ADHD that every 5
    # seconds throws out a short sound"). So: only if the answer is not
    # already back `backchannel_after_ms` after the turn ended -- a quick
    # answer IS the acknowledgement -- and not within `backchannel_gap_s`
    # of the last one.
    # And only when the words are presumably for Sim: its name was
    # said, or Sim itself spoke within `exchange_window_s` -- an
    # exchange under way. Overheard talk gets no sound; whether it gets
    # an answer at all is the model's call (backchannel.is_quiet).
    # Read through what the recogniser mangled before answering
    # (cognition/tidy.py): "Seem do something" is "Sim, do something"
    # at once; a garbled sentence gets one short model call, under the
    # backchannel, and the screen shows what it was read as.
    tidy: bool = True
    backchannel: bool = True
    # 2500, not 1500: the model's answer usually lands in 1-2.5 s, and an
    # "Okay." that starts at 1.5 s holds the floor for the answer -- the
    # creator heard the sound as the delay itself (2026-09-13).
    backchannel_after_ms: int = 2500
    backchannel_gap_s: float = 12.0
    exchange_window_s: float = 20.0
    still_after_s: float = 20.0
    # A listener's "uh-huh" under the person, at half volume, when
    # they pause mid-story (voice/delivery.py "hum"): only once they have
    # been talking `hum_after_ms`, at a pause that is not the end of a
    # question, and not twice within `hum_gap_s`.
    hum: bool = True
    hum_after_ms: int = 6000
    hum_gap_s: float = 10.0
    # How a reply is delivered -- pace, loudness, pauses -- follows the
    # situation (voice/delivery.py): warm for a hurt, bright for good
    # news, "Aha…" slow, "Got it." quick. Off = one flat register.
    expressive: bool = True
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
    # Who is speaking (voice/speakers.py): "auto" identifies when the
    # engine and model are there and somebody is enrolled; "off" never.
    # threshold/margin are the cosine rules the SpeakerBook applies;
    # `voice whois` shows the live scores so a household can tune them.
    speaker_id: str = "auto"
    speaker_threshold: float = 0.5     # TitaNet: same voice ~0.87, another ~0.31 (2026-09-13); the creator asked for 0.5
    speaker_margin: float = 0.06
    # Under the threshold but at least this close, and clear of the
    # runner-up: "probably <name>" -- the turn is theirs, marked so.
    # 0 turns the lean off (unknown is unknown).
    speaker_lean: float = 0.45
    # A turn Sim is sure about becomes one more take for that person,
    # silently (voice/speakers.py `refine`): the voice model tunes itself
    # to the room without ever asking for training sentences.
    speaker_refine: bool = True
    # A turn long enough may hold two people (voice/diarize.py): its
    # words are attributed by voice, window by window, and the model is
    # told "Saeed: ... / Soodeh: ...". Off, or too short, and the whole
    # turn is one voice.
    diarize: bool = True
    diarize_min_s: float = 3.5
    diarize_words: bool = False    # whisper times every word (finer cuts, ~0.5 s slower a turn) instead of its own segments
    speakers_dir: str = "workspace/voice/speakers"
    # Meeting a voice Sim does not know (voice/introduce.py): after this
    # many turns from the same unknown voice, Sim asks who it is talking
    # to and enrols them by conversation. 0 turns off the asking; "Sim,
    # learn Aran's voice" still works.
    # 0 (the default since 2026-09-13): Sim never asks an unknown voice
    # who it is on its own -- "it continuously detected our voices as
    # new people and asked for three sentences" (the creator). A voice
    # is enrolled by `voice enroll <name>` or by being asked: "Sim, learn
    # Aran's voice". A number above 0 restores the asking.
    introduce_after_turns: int = 0
    # Two known people talking to each other: Sim keeps the thread and
    # stays quiet unless named or mid-exchange (voice/session.py).
    bystander: bool = True
    # How much of a feeling shows in the voice: Kokoro blends that share
    # of a differently coloured voice into yours (1.0 = as tabled in
    # tts/kokoro.py, 0 = always the plain voice; 2.0 is a lot).
    tone_blend: float = 1.0
    # The expressive engines (voice/tts/chatterbox.py, miso.py) live in
    # their own virtual environments under `venv_dir`; a reference WAV
    # clones a voice; `expressive_timeout_s` bounds one sentence.
    venv_dir: str = "workspace/voice/venvs"
    chatterbox_reference: str = ""          # the WAV Chatterbox's `default` voice clones; "" for its own
    references_dir: str = "workspace/voice/references"   # named reference clips (Kokoro voices rendered once, or yours)
    chatterbox_exaggeration: float = 0.0    # 0 = the tone table decides; else a fixed dial 0.1-1.0
    miso_reference: str = ""
    miso_repo: str = "workspace/voice/engines/MisoTTS"
    miso_device: str = ""                   # "" = cuda, else mps, else cpu
    expressive_timeout_s: float = 180.0
    # Which replies the expressive engine speaks when `tts` names one
    # (voice/tts/lanes.py): "auto" = `voice test` only (and a spoken
    # reply at least `expressive_min_chars` long, when that is set);
    # spoken turns, typed-turn replies and asides take the quick lane
    # (Kokoro). "always" = everything through the expressive engine,
    # slow first sound and all; "off" = never, the quick lane only.
    expressive_warm_delay_s: float = 90.0   # the slow engine loads this long after `voice on`, so hearing comes first
    expressive_lane: str = "auto"
    expressive_min_chars: int = 0     # 0 = a spoken turn never takes the slow lane in auto (it held the floor 78 s once)
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
        values = {k: v for k, v in dict(mapping).items() if k in known}
        if isinstance(values.get("enabled"), str) and values["enabled"].strip().lower() != "auto":
            values["enabled"] = values["enabled"].strip().lower() in ("on", "true", "yes", "1")
        return cls(**values)

    def wants_listening(self, *, interactive: bool, real_microphone: bool) -> bool:
        """Whether to listen on boot: `enabled` as said, or for "auto",
        a person at a terminal with a microphone that is not a fake."""
        if isinstance(self.enabled, bool):
            return self.enabled
        return bool(interactive and real_microphone)


__all__ = ["Config"]
