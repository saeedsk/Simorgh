"""Speech-to-text engines. Each is optional; `open_recogniser` picks."""

from __future__ import annotations

from ..config import Config


def open_recogniser(config: Config, *, repo_root=None) -> tuple[object | None, str]:
    """`(recogniser, why not)`: the configured engine, or for "auto" the
    best one present -- faster-whisper, then whisper.cpp's CLI. Never a
    cloud engine (design section 0)."""
    from .faster_whisper import FasterWhisperRecogniser
    from .whisper_cli import WhisperCliRecogniser

    if config.stt == "fake":
        from ..fakes import FakeRecogniser

        return FakeRecogniser(config.fake_transcript), ""
    order = {"auto": (FasterWhisperRecogniser, WhisperCliRecogniser),
             "faster_whisper": (FasterWhisperRecogniser,),
             "whisper_cli": (WhisperCliRecogniser,)}.get(config.stt)
    if order is None:
        return None, f"unknown stt engine {config.stt!r} (auto | faster_whisper | whisper_cli | fake)"
    reasons = []
    for cls in order:
        try:
            return cls(config, repo_root=repo_root), ""
        except ImportError as exc:
            reasons.append(f"{cls.name}: {exc}")
    return None, ("no speech recogniser (" + "; ".join(reasons)
                  + ") -- pip install faster-whisper, or brew install whisper-cpp")


__all__ = ["open_recogniser"]
