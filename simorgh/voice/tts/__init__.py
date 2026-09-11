"""Text-to-speech engines. Each optional; `open_synthesiser` picks."""

from __future__ import annotations

from ..config import Config


def open_synthesiser(config: Config) -> tuple[object | None, str]:
    from .kokoro import KokoroSynthesiser
    from .say import SaySynthesiser

    if config.tts == "fake":
        from ..fakes import FakeSynthesiser

        return FakeSynthesiser(), ""
    order = {"auto": (KokoroSynthesiser, SaySynthesiser), "kokoro": (KokoroSynthesiser,),
             "say": (SaySynthesiser,)}.get(config.tts)
    if order is None:
        return None, f"unknown tts engine {config.tts!r} (auto | kokoro | say | fake)"
    reasons = []
    for cls in order:
        try:
            return cls(config), ""
        except ImportError as exc:
            reasons.append(f"{cls.name}: {exc}")
    return None, "no speech synthesiser (" + "; ".join(reasons) + ") -- pip install kokoro-onnx, or use macOS `say`"


__all__ = ["open_synthesiser"]
