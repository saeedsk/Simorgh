"""TTS output for Simorgh -- Kokoro, voice af_jessica.

The reader for the `[interface] tts_enabled` / `tts_voice` config
fields (kernel/configcheck.py flagged them as unread before this
module existed). Everything is lazy: the Kokoro pipeline (and its
torch import) is only built on the first `say()`/`synthesize()` call,
so an unused install costs nothing at startup.

How to trigger a spoken reply:
  * set `[interface] tts_enabled = true` in config -- every chat reply
    is then spoken after being printed (the interface service calls
    `say()` for this);
  * or call `tts.say(text)` / `tts.synthesize(text, path)` directly.

Voice defaults to `af_jessica`; change `tts_voice` to switch.
Playback is in-process only (sounddevice via soundfile) -- no
subprocesses are spawned.
"""

from __future__ import annotations

import tempfile
import threading
from typing import Optional

from simorgh.interface import config as _cfg

_LOCK = threading.Lock()
_PIPELINE = None  # lazy KPipeline
_PLAYED_LOCK = threading.Lock()  # one utterance at a time

_SAMPLE_RATE = 24000  # Kokoro outputs 24 kHz


def _voice() -> str:
    return getattr(_cfg.Config, "tts_voice", "af_jessica") or "af_jessica"


def _get_pipeline():
    """Build the Kokoro pipeline once. Raises if kokoro is not
    installed or the model cannot be loaded -- callers decide whether
    that is fatal."""
    global _PIPELINE
    with _LOCK:
        if _PIPELINE is None:
            from kokoro import KPipeline  # heavy import: torch, misaki

            _PIPELINE = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    return _PIPELINE


def synthesize(text: str, out_path: str, voice: Optional[str] = None) -> str:
    """Synthesize `text` to a wav at `out_path`; returns the path."""
    pipe = _get_pipeline()
    v = voice or _voice()
    audio = None
    for _gs, _ps, audio in pipe(text, voice=v):
        pass  # keep the last (full) chunk
    if audio is None:
        raise RuntimeError("kokoro produced no audio")
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    import soundfile as sf

    sf.write(out_path, audio, _SAMPLE_RATE)
    return out_path


def say(text: str, voice: Optional[str] = None) -> Optional[str]:
    """Speak `text` aloud. Returns the temp wav path, or None if TTS
    is unavailable. Never raises into the reply path."""
    try:
        with _PLAYED_LOCK:  # one utterance at a time
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                path = f.name
            synthesize(text, path, voice=voice)
            _play(path)
            return path
    except Exception:  # noqa: BLE001 -- speech is best-effort, replies must not break
        return None


def _play(path: str) -> None:
    """Play a wav in-process via sounddevice/soundfile."""
    import sounddevice as sd
    import soundfile as sf

    data, sr = sf.read(path)
    sd.play(data, sr)
    sd.wait()


def enabled() -> bool:
    """Whether the config flag turns speech on for chat replies."""
    return bool(getattr(_cfg.Config, "tts_enabled", False))


def available() -> bool:
    """True if kokoro imports and sounddevice/soundfile are present."""
    try:
        import sounddevice  # noqa: F401
        import soundfile  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    try:
        _get_pipeline()
        return True
    except Exception:  # noqa: BLE001
        return False
