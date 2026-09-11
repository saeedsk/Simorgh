"""Text-to-speech engines. Each optional; `open_synthesiser` picks.

Since 2026-09-11 the pick is per LANGUAGE, not per machine: the primary
voice (Kokoro, else `say`) speaks English, and a reply in the Arabic
script goes to Piper's Persian voice, opened on first use. Kokoro read
Farsi as English gibberish; that is what this exists to stop.
"""

from __future__ import annotations

from ..api import Audio
from ..config import Config
from ..lang import ENGLISH, language_of


class PolyglotSynthesiser:
    """One synthesiser per language, chosen by the reply's script.

    `primary` speaks everything the table does not route elsewhere.
    Engines for other languages are opened lazily, once, and a language
    whose engine cannot be opened is SAID -- in the primary voice --
    rather than mangled or dropped: "I cannot speak Farsi yet: piper
    voice not found ...". A refusal you can hear is one that gets fixed.
    """

    def __init__(self, primary, config: Config, *, openers: dict | None = None) -> None:
        self._primary = primary
        self._config = config
        self._openers = openers if openers is not None else _default_openers()
        self._engines: dict[str, object] = {ENGLISH: primary}
        self._problems: dict[str, str] = {}
        self.last_engine = getattr(primary, "name", "")

    @property
    def name(self) -> str:
        return getattr(self._primary, "name", "")

    def voices(self) -> list[str]:
        out = list(self._primary.voices())
        for engine in self._engines.values():
            if engine is not self._primary:
                out.extend(engine.voices())
        return out

    def engine_for(self, language: str):
        """The engine for `language`, opening it on first use; None
        (with the reason in `problems`) when it cannot be opened."""
        if language in self._engines:
            return self._engines[language]
        opener = self._openers.get(language)
        if opener is None:
            return self._primary
        try:
            engine = opener(self._config)
        except ImportError as exc:
            self._problems[language] = str(exc)
            return None
        self._engines[language] = engine
        return engine

    @property
    def problems(self) -> dict[str, str]:
        return dict(self._problems)

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        language = language_of(text)
        engine = self.engine_for(language)
        if engine is None:
            self.last_engine = getattr(self._primary, "name", "")
            excuse = f"I cannot speak {_LANGUAGE_NAMES.get(language, language)} yet: {self._problems[language]}"
            return await self._primary.synthesise(excuse, voice=voice, speed=speed)
        self.last_engine = getattr(engine, "name", "")
        if engine is self._primary:
            return await engine.synthesise(text, voice=voice, speed=speed)
        return await engine.synthesise(text, speed=speed)


_LANGUAGE_NAMES = {"fa": "Farsi", "en": "English"}


def _default_openers() -> dict:
    from ..lang import FARSI
    from .piper import PiperSynthesiser

    return {FARSI: lambda config: PiperSynthesiser(config, voice=config.tts_farsi_voice)}


def open_synthesiser(config: Config) -> tuple[object | None, str]:
    from .kokoro import KokoroSynthesiser
    from .piper import PiperSynthesiser
    from .say import SaySynthesiser

    if config.tts == "fake":
        from ..fakes import FakeSynthesiser

        return FakeSynthesiser(), ""
    order = {"auto": (KokoroSynthesiser, SaySynthesiser), "kokoro": (KokoroSynthesiser,),
             "piper": (PiperSynthesiser,), "say": (SaySynthesiser,)}.get(config.tts)
    if order is None:
        return None, f"unknown tts engine {config.tts!r} (auto | kokoro | piper | say | fake)"
    reasons = []
    primary = None
    for cls in order:
        try:
            primary = cls(config)
            break
        except ImportError as exc:
            reasons.append(f"{cls.name}: {exc}")
    if primary is None:
        return None, "no speech synthesiser (" + "; ".join(reasons) + ") -- pip install kokoro-onnx, or use macOS `say`"
    if not config.tts_by_language or config.tts == "piper":
        return primary, ""
    return PolyglotSynthesiser(primary, config), ""


__all__ = ["PolyglotSynthesiser", "open_synthesiser"]
