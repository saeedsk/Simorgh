# voice -- talking to Sim

The 19th subsystem (docs/plans/voice-design.md). A spoken turn becomes
`percept.text.received{channel: "voice"}` and rides the same
Orchestration/Cognition path as typed text; the reply comes back as
`turn.completed` and is spoken. One brain, one Guardian, one ledger.
This package owns only the audio.

| file | what |
|---|---|
| `api.py` | `Audio`, `Utterance`, `VoiceTurn`, `VoiceState`; the engine protocols |
| `config.py` | `[voice]` -- every key is read by something |
| `audio.py` | capture (`sounddevice`, else `ffmpeg`), playback (`sounddevice`, else `afplay`/`ffplay`), WAV helpers |
| `vad.py` | `Endpointer` over Silero (if installed) or an energy detector |
| `stt/` | `faster_whisper` (primary), `whisper_cli` (whisper.cpp, present via Homebrew) |
| `tts/` | `kokoro` (primary), `piper` (the languages Kokoro lacks: Farsi), `say` (macOS, present); `open_synthesiser` routes each reply by its script (`lang.py`) |
| `pipeline.py` | capture -> endpoint -> STT -> percept -> wait for the turn -> TTS -> play; `voice:turns` in the ledger |
| `service.py` | the Subsystem: presence probes into `capabilities`, the `voice.*` request handlers, the `voice on` loop |
| `fakes.py` | every engine and device as a deterministic stand-in |

## Built (slice 1: the laptop)

- `voice status | on | off | mute | unmute | listen [seconds] [only] | test <text> | voices | devices | models [name]`
- Engines are opened on first use and refused BY NAME when absent, with
  what to install. `capabilities` lists speech-to-text, text-to-speech,
  microphone and audio-playback beside Docker and Chromium.
- The never-guess rule: a hearing below `min_confidence` is asked about
  ("did you say ...?"), never acted on.
- **Echo cancellation** (`aec.py`, off by default, `voice barge aec on`): an NLMS adaptive
  filter learns the room's echo of Sim's own voice -- known exactly, it is what is
  playing -- and subtracts it; barge-in then decides on the residual, so a person is
  detected by being ABSENT from the reference, not by being louder than Sim. Validated
  on a synthetic echo (>20 dB ERLE); a real room needs a recording to tune, which is why
  it is off until then. The level gate is the default and the fallback.
- **Barge-in**: the mic stays open while Sim speaks; `barge_in_speech_ms` of a
  person's speech, measured over the level the mic hears of Sim's own voice
  (the first frames of each reply calibrate the floor), stops playback at once,
  and the interrupting words become the next turn. Headphones make it
  bulletproof; on a laptop's speakers the echo calibration carries it.
- A reply that is not back within `reply_timeout_s` is spoken as
  "I'm still working on that", never silence.
- Privacy defaults from the design: audio is not kept unless
  `keep_audio`; transcripts are ledgered (`voice:turns`).

- **Farsi** (2026-09-11): a reply in the Arabic script is spoken by Piper's
  `fa_IR-amir-medium` (`voice models piper-fa` fetches it, 63 MB; `[voice]
  tts_farsi_voice` picks another), English stays with Kokoro. Kokoro had been
  reading Persian letters as English gibberish. A language whose engine is
  missing is excused aloud ("I cannot speak Farsi yet: ...") rather than
  mangled. Hearing Farsi: `stt_language` now defaults to detect, and
  `voice models large-v3-turbo` fetches the multilingual model that hears
  it (exact transcript on a Persian sample, 1.3-2 s with Metal); `base.en`
  hears English only.

## Not built yet (later slices, in the design)

Wake word (openWakeWord; today is push-to-talk: `voice listen`, or
`voice on` for an open mic), streaming STT and sentence-streamed TTS
(today's turn is capture-then-transcribe-then-speak; barge-in is built,
resuming a false-alarm interruption is not), speaker
identification and per-speaker permissions, the fast intent path, the
voice scaffold for short spoken replies, Wyoming satellites, the
OpenAI-compatible endpoint for Home Assistant, the PWA, Alexa.

## On this machine, today

`whisper-cli` (whisper.cpp) with `base.en`, **Kokoro** (`kokoro-onnx`, 54 voices,
24 kHz, ~1 s per sentence on CPU; `voice models kokoro` fetches its two files,
~340 MB), `ffmpeg` capture, `afplay`. `say` remains the fallback. Homebrew's
bundled `for-tests-ggml-tiny.bin` is a fixture that hears silence; `voice
models base.en` fetches a real model (148 MB, ~5 s) and the JFK sample
then transcribes in 0.5 s. Better: `pip install faster-whisper
kokoro-onnx sounddevice`, and a real whisper model under
`workspace/voice/models/`.
