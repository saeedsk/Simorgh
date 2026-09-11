# Spoken replies

Sim speaks through the `voice` subsystem (`simorgh/voice/README.md`) --
Kokoro by default, `say` as the fallback -- with barge-in and the
transcript on the console.

- Spoken turns (`voice listen`, `voice on`) are answered aloud always.
- To hear replies to TYPED turns as well:

  ```toml
  [voice]
  speak_replies = true
  tts_voice = "af_jessica"   # any of `voice voices`
  ```

There is one TTS path. An earlier `simorgh/interface/tts.py` (torch
Kokoro, in-process playback) was folded into it on 2026-09-10.
