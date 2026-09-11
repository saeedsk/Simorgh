"""Speak Simorgh's replies out loud -- the interface side of TTS.

Synthesis itself lives in `simorgh/voice/` (Kokoro-82M via
`kokoro-onnx`; default voice `af_jessica`, the creator's pick, in
`simorgh/voice/config.py`). This module is the thin hook the
interface -- and any code embedding Simorgh -- calls to turn a reply
into audio.

Two paths:

- `speak_reply(text, bus=...)` -- the usual one. Sends a
  `voice.speak.request` over the bus so the running voice service
  synthesises and plays it (identical to the `voice speak` command,
  barge-in and muting included). `bus` is a `BusClient`; the request
  is built with `bus.new` and sent with `bus.request`, same as
  `simorgh/interface/dispatch.py`'s `_request` helper.
- `synthesise_reply(text)` -- standalone. Builds a synthesiser from
  the voice config and returns an `Audio`: `.play()` to hear it,
  `.write_wav(path)` to save it. No bus or service needed.

Triggering, three ways (documented in docs/TTS.md):

1. `voice speak <text>` in the TUI/CLI.
2. `await speak_reply("...", bus=client)` from code.
3. `python -m simorgh.interface.tts "..."` from a shell.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..voice.config import VoiceConfig
from ..voice.tts import build_synthesiser

#: Bus round-trip timeout: synthesis is ~1 s per sentence on CPU, but
#: the first call also loads the ONNX model.
BUS_TIMEOUT = 120.0

DEFAULT_WAV = Path("workspace") / "last_reply.wav"


async def speak_reply(text: str, *, voice: str = "", bus=None) -> str | None:
    """Speak a reply. Via the voice service when `bus` is given
    (returns the text it confirmed saying, else None on refusal);
    otherwise synthesises locally and plays on the default speaker.
    """
    if not text.strip():
        return None
    if bus is not None and hasattr(bus, "new") and hasattr(bus, "request"):
        from ..bus import topics

        reply = await bus.request(
            bus.new(topics.VOICE_SPEAK_REQUEST, {"text": text, "voice": voice}),
            timeout=BUS_TIMEOUT,
        )
        payload = getattr(reply, "payload", None) or {}
        if payload.get("ok") is False:
            return None
        return str(payload.get("said") or text)
    audio = await synthesise_reply(text, voice=voice)
    audio.play()
    return text


async def synthesise_reply(text: str, *, voice: str = "", config: VoiceConfig | None = None):
    """Synthesise a reply to an `Audio` without the voice service.

    Raises RuntimeError with the reason when no synthesiser can be
    built (usually: `pip install kokoro-onnx`).
    """
    cfg = config or VoiceConfig()
    synth, why = build_synthesiser(cfg)
    if synth is None:
        raise RuntimeError(f"no speech synthesiser available ({why}) -- pip install kokoro-onnx")
    return await synth.synthesise(text, voice=voice or cfg.tts_voice)


def say(text: str, *, voice: str = "", wav: Path | None = None, play: bool = True) -> Path:
    """Synchronous one-liner: synthesise `text`, write a WAV, optionally
    play it. Returns the WAV path. Used by `python -m simorgh.interface.tts`.
    """
    audio = asyncio.run(synthesise_reply(text, voice=voice))
    path = audio.write_wav(wav or DEFAULT_WAV)
    if play:
        audio.play()
    return path


if __name__ == "__main__":  # pragma: no cover
    import sys

    text = " ".join(sys.argv[1:]) or "Simorgh here, voice online."
    print(f"spoken; wav written to {say(text, play=False)}")
