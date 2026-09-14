"""Speech-to-text engines. Each is optional; `open_recogniser` picks."""

from __future__ import annotations

from ..config import Config


def open_recogniser(config: Config, *, repo_root=None) -> tuple[object | None, str]:
    """`(recogniser, why not)`: the configured engine, or for "auto" the
    best one present -- whisper.cpp's server, then faster-whisper, then
    whisper.cpp's CLI. Never a cloud engine (design section 0)."""
    from .faster_whisper import FasterWhisperRecogniser
    from .whisper_cli import WhisperCliRecogniser
    from .whisper_server import WhisperServerRecogniser

    if config.stt == "fake":
        from ..fakes import FakeRecogniser

        return FakeRecogniser(config.fake_transcript), ""
    # The server before the CLI: same model, same words, 2.5 s less per
    # turn (whisper_server.py has the measurement). And before faster-whisper:
    # that one runs on the CPU, so once it was installed "auto" chose it over
    # the Metal server and every turn took ~20 s to hear, low enough in
    # confidence that Sim asked "did you say ...?" of plain words
    # (2026-09-14, live).
    order = {"auto": (WhisperServerRecogniser, FasterWhisperRecogniser, WhisperCliRecogniser),
             "faster_whisper": (FasterWhisperRecogniser,),
             "whisper_server": (WhisperServerRecogniser,),
             "whisper_cli": (WhisperCliRecogniser,)}.get(config.stt)
    if order is None:
        return None, f"unknown stt engine {config.stt!r} (auto | faster_whisper | whisper_server | whisper_cli | fake)"
    reasons = []
    for cls in order:
        try:
            return cls(config, repo_root=repo_root), ""
        except ImportError as exc:
            reasons.append(f"{cls.name}: {exc}")
    return None, ("no speech recogniser (" + "; ".join(reasons)
                  + ") -- pip install faster-whisper, or brew install whisper-cpp")


__all__ = ["open_recogniser"]
