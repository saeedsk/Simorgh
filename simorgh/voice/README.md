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

## The conversation (2026-09-11)

A spoken turn is no longer capture, transcribe, ask, synthesise the
whole reply, play it. `voice on` runs `session.py`:

    frames -> vad.FrameVad -> turns.TurnManager -> stt/streaming.IncrementalRecogniser -> Sim
           -> planner.SpokenResponsePlanner -> tts/streaming.StreamingSynthesiser -> playback.StreamingPlayer

| part | what it decides |
|---|---|
| `turns.py` | whose turn it is: idle, listening, user_speaking, thinking, agent_speaking, interrupted, error. End of turn is silence after enough speech (shortened when the partial already reads as a sentence, forced at `max_turn_ms`); barge-in stops the speaker and cancels synthesis; turn and response ids only go up, so a stale reply or chunk is dropped. |
| `stt/streaming.py` | provisional transcripts every `stt_partial_every_ms` while the person is talking (`hearing: ...` on screen), one final that replaces them |
| `planner.py` | speakable text: code, tables, links, citations and paths are named, not read; lists become first, second; "24.5" is said as words; chunks at sentence and clause boundaries with a short first one; at most one connector ("Okay," / "Yeah," / "Right," / "Ah," / "Hmm,") when the words call for it, never two turns running; long answers cut at `max_spoken_sentences` and say so |
| `tts/streaming.py` | piece-by-piece synthesis with a `tts_lookahead` bound, levelled so pieces do not jump in volume, cancellable between pieces |
| `playback.py` | ready pieces joined and played gaplessly, `stop()` within a frame, chunks from an old response never played |
| `session.py` | the loop, the clocks, the diagnostics (`voice status`, `voice:turns`) |

The model is told it is speaking (`orchestration/scaffolds.VOICE`) only
on the voice channel, so replies are written for the ear in the first
place.

**Settings** (`voice set <key> <value>`; `voice set` alone lists them):
speaking rate, volume, language, voice, barge-in, end-of-turn silence,
VAD sensitivity, engines, partials, connectors, diagnostics. A change
applies at once and is written to `~/.simorgh/simorgh.toml`.

**Measured** (`voice bench`; Apple M3 Pro, macOS 26.5, Python 3.12,
Kokoro through onnxruntime, whisper.cpp 1.9.1 large-v3-turbo with Metal):

| what | measured |
|---|---|
| Kokoro load / first synthesis | 1.2 s / 1.8 s (once per boot; `voice on` warms it) |
| time to first audio after the answer arrives | 0.31-0.55 s (median 0.51 s) on the four design samples |
| synthesis real-time factor | 0.20x |
| transcription, 4.0 s utterance | 1.9 s (rtf 0.49) -- whisper-cli reloads the 1.6 GB model per call; `faster-whisper` keeps it resident |
| barge-in | noticed after `barge_in_speech_ms` (650) + one frame; the speaker (afplay) stops 8 ms after `stop()` |
| peak memory | 684 MB |
| Piper (Farsi) load / synthesis | 2.0 s / 0.12 s for 1.7 s of audio |

The 650 ms barge-in window is the design's safety against Sim
interrupting itself on a laptop's speakers; with headphones or AEC on it
can come down (`voice set` does not expose it on purpose -- edit
`barge_in_speech_ms` in simorgh.toml).

**Privacy.** Audio, transcripts and speech stay on the machine. Raw
microphone audio is not kept (`keep_audio` is off; the streaming path
never writes it). Transcripts are ledgered (`keep_transcripts`), which
is Sim's memory of the conversation; logs carry metadata only.

**Not done.** The model's answer is not streamed token by token from
Cognition, so the first piece waits for the whole answer; time to
first audio above is measured from the answer arriving. Farsi has no
open-source female voice (every Persian Piper voice measured male);
the fluent female option is a cloud service and is deliberately not in
the path. AEC's reference is fed as pieces are synthesised, slightly
ahead of playback; an underrun mid-reply drifts it.

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
