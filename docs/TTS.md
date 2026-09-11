# TTS (spoken replies)

Simorgh can speak its replies aloud using [Kokoro TTS](https://github.com/hexgrad/kokoro),
voice **`af_jessica`** by default.

## How to trigger it

1. **Speak every reply** — set the flag in config:

   ```toml
   [interface]
   tts_enabled = true
   ```

   Every chat reply is then spoken after being printed. The voice comes from
   `[interface] tts_voice` (default `af_jessica`; change it to any Kokoro
   voice id, e.g. `af_bella`, `af_sky`).

2. **Speak on demand** — from Python / a skill:

   ```python
   from simorgh.interface import tts

   tts.say("Hello, I am Simorgh.")              # synthesize + play
   tts.synthesize("text", "/tmp/out.wav")       # write a wav without playing
   tts.available()                              # kokoro + audio backend present?
   ```

## Implementation

- `simorgh/interface/tts.py` — lazy Kokoro `KPipeline` (built on first use, so
  startup cost is zero when the flag is off), 24 kHz wav output, in-process
  playback via `sounddevice`/`soundfile`. Speech is best-effort: a TTS failure
  never breaks the reply path.
- `simorgh/interface/service.py` — after a chat reply is printed, `_handle_chat`
  calls `tts.say(reply_text)` when `tts_enabled` is on and TTS is available.
- `simorgh/interface/config.py` — `tts_enabled` (default `False`) and
  `tts_voice` (default `af_jessica`).

## Dependencies

`pip install kokoro sounddevice soundfile` (kokoro pulls in torch, misaki and
friends; the Kokoro-82M model weights are downloaded from Hugging Face on
first use and cached).
