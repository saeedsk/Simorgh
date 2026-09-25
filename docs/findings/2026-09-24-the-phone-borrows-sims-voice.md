# The phone speaks and hears with Sim's own engines

2026-09-24. Measured on the creator's MacBook Pro M3.

## The complaint

> why the voice on sim app sounds robotic, I want to have same voice chat
> experience as I have on mac with same stt and tts engines

The iOS app used Apple's `AVSpeechSynthesizer` and `SFSpeechRecognizer`.
That was a deliberate stopgap, recorded in `Voice.swift` at the time:
Sim's Kokoro and whisper.cpp are on the Mac, reaching them was supposed
to need the second `VoiceSession` and the audio socket (`voice/remote.py`,
stage 12 item 5), and waiting for those would have meant no voice at all.

## What was already there

`session._ship_to_tv` has been putting Kokoro's voice in the ledger as an
`audio/wav` blob and announcing it on `ui.tv.speech` for the TV page to
fetch, since the TV work. So shipping Sim's voice off this machine was a
solved problem — it just could not be ASKED for. `voice.speak.request`
SPEAKS in the room and returns `{seconds, engine, detail}`; there was no
synthesise-and-return path, and no transcribe-this-audio path either.

Item 5 was never the blocker for the app's voice. A request/reply pair
was.

## What was added

    voice.synthesise.request {text, voice?, speed?, lane?}
      -> {ref, seconds, engine, sample_rate}     a WAV blob, NOT played here
    voice.transcribe.request {ref, language?}
      -> {text, confidence, language, seconds, engine}

Neither handler touches the session, the echo tracker or the turn state
machine: a phone turn is not a turn in the room and must not make Sim
think it is talking here.

`POST /api/say` returns the bytes themselves rather than a ref — one
request, straight to the player — with the engine in `X-Sim-Engine`.
`POST /api/listen` takes a WAV and returns the words. Neither goes through
`_run_for_page`: no tool is asked for and no effect proposed, so there is
nothing for Guardian to weigh. `chat` is the gate.

## Measured, real engines, over real HTTP

A kernel booted with the creator's own `[voice]` settings
(`stt = whisper_server`, `tts = auto`, `tts_voice = af_bella`,
`tts_speed = 1.1`), an `HttpApi` in front of it, and a paired device token:

    POST /api/say    -> 200 audio/wav  120876 bytes
                        engine='kokoro'  seconds='2.517'
                        playable: 24000 Hz, 2.52 s
    POST /api/listen -> 200 {'text': 'Turn the porch light off and lock the
                        front door.', 'confidence': 1.0,
                        'language': 'english',
                        'engine': 'whisper_server:large-v3-turbo'}
    read-only device -> 403 chat

    said:  Turn the porch light off and lock the front door.
    heard: Turn the porch light off and lock the front door.

Verbatim, both directions. The earlier fakes-only round trip through the
bus alone gave the same result for a different sentence (5/5 keywords).

Kokoro returns **24 kHz**, not 16 kHz, so a synthesised WAV read back
takes `read_wav_bytes`' ffmpeg branch — which this run therefore also
proves works. The phone records at 16 kHz and hits the fast path.

## On the phone

- The recording is built at 16 kHz mono int16 through `AVAudioConverter`:
  what `voice/api.py::Audio` means by audio, and what `/api/listen` reads
  without ffmpeg.
- The turn is ended by **energy**, in `Voice.swift`, not by Apple's
  recogniser deciding the sentence is over — so a turn ends the same way
  whether or not Speech recognition is authorised.
- Apple's recogniser is still started, for the live words on screen while
  somebody is speaking, and its transcript is **never** what reaches Sim.
  Whisper's is. A preview that is approximately right is worth having; a
  preview that is silently what Sim hears is not.
- Apple's synthesiser stays as a fallback for one case: Sim answered but
  could not make the sound (no Kokoro, no ledger, house unreachable). A
  robot voice beats silence when somebody is holding the phone waiting,
  and the bar names it — "Speaking (this phone's voice)".

## Found on the way: a refusal that fails its own contract

`{"ok": False, "detail": ...}` does not validate. The failure branch of
every `*.reply` requires an `error` object (`registry.error_reply_payload`),
so a reply shaped that way is thrown out by `validate` at publish time and
the caller waits out its timeout knowing nothing — which is exactly how it
showed up here, as a `BusTimeout` on a request the handler had answered.

This was found once before, for `voice.control.reply`, on 2026-09-12: the
creator's `voice set ttc_voice = af_kore` got a traceback instead of "did
you mean tts_voice". It was fixed at that one call site. `speak`, `listen`,
`bench` and `models` all still had it. `Service._refused` now covers every
one, and it is invariant 6 in `simorgh/voice/CONTRACT.md`.

Another instance of the shape the project keeps finding: a bug diagnosed
correctly, fixed where it was seen, and left alive everywhere else.

## Still open

- **No partials.** The Mac shows words as whisper hears them
  (`stt_partials`, `stt_partial_every_ms = 800`); the phone sends one
  recording and waits. The on-screen preview covers the gap but is
  Apple's, not Sim's. Real partials need streaming audio up, which is what
  `voice/remote.py` (item 5) is for.
- **No barge-in.** Speaking over Sim's reply does not stop it; the app has
  a Stop button. The Mac's `EchoTracker` and level gate have no equivalent
  here.
- **Item 5 is still unbuilt** — `voice/remote.py` has its RFC 6455 frames
  and 20 tests and no session behind it. It is now an improvement to a
  working voice chat rather than a prerequisite for having one.
