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

    Marks for IPA pass through; each engine underneath says whether it
    reads them (`speaks_ipa`) and `_with_tone` respells for one that does not.

    `primary` speaks everything the table does not route elsewhere.
    Engines for other languages are opened lazily, once, and a language
    whose engine cannot be opened is SAID -- in the primary voice --
    rather than mangled or dropped: "I cannot speak Farsi yet: piper
    voice not found ...". A refusal you can hear is one that gets fixed.
    """

    speaks_ipa = True

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

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "", lane: str = "") -> Audio:
        language = language_of(text)
        engine = self.engine_for(language)
        if engine is None:
            self.last_engine = getattr(self._primary, "name", "")
            excuse = f"I cannot speak {_LANGUAGE_NAMES.get(language, language)} yet: {self._problems[language]}"
            return await _with_tone(self._primary, excuse, voice=voice, speed=speed, tone=tone, lane=lane)
        if engine is self._primary:
            audio = await _with_tone(engine, text, voice=voice, speed=speed, tone=tone, lane=lane)
        else:
            audio = await _with_tone(engine, text, voice="", speed=speed, tone=tone)
        # The engine that actually spoke -- a lane pair reports the lane's engine.
        self.last_engine = getattr(engine, "last_engine", None) or getattr(engine, "name", "")
        return audio

    def pace_ratio(self, lane: str = "") -> float:
        own = getattr(self._primary, "pace_ratio", None)
        return float(own(lane)) if callable(own) else 0.0

    async def warmup(self) -> float:
        own = getattr(self._primary, "warmup", None)
        if callable(own):
            return float(await own())
        await self._primary.synthesise("Okay.", speed=1.0)
        return 0.0

    async def close(self) -> None:
        for engine in self._engines.values():
            close = getattr(engine, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    pass


async def _with_tone(engine, text: str, *, voice: str, speed: float, tone: str, lane: str = "") -> Audio:
    """Call an engine's synthesise, with the tone (and lane) when it takes
    one, and the IPA marks respelled for an engine that reads letters."""
    import inspect

    if not getattr(engine, "speaks_ipa", False):
        from ..pronounce import strip_marks

        text = strip_marks(text)
    kwargs = {"speed": speed}
    if voice:
        kwargs["voice"] = voice
    try:
        params = inspect.signature(engine.synthesise).parameters
        takes_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        if tone and ("tone" in params or takes_any):
            kwargs["tone"] = tone
        if lane and ("lane" in params or takes_any):
            kwargs["lane"] = lane
    except (TypeError, ValueError):
        pass
    return await engine.synthesise(text, **kwargs)


_LANGUAGE_NAMES = {"fa": "Farsi", "en": "English"}


def _farsi_synthesiser(config):
    """Whichever engine `[voice] tts_farsi` names, or the one that works.

    "auto" keeps Piper first -- it is a 63 MB download that speaks at
    22.05 kHz and is already on this machine -- and reaches for MMS only
    when Piper refuses (not installed, voice not fetched). Naming an
    engine means it or nothing: a person who asked for MMS and silently
    got Piper would think MMS sounds exactly like Piper.
    """
    from .mms import MmsSynthesiser
    from .piper import PiperSynthesiser

    choice = (getattr(config, "tts_farsi", "auto") or "auto").strip().lower()
    if choice == "mms":
        return MmsSynthesiser(config, model_id=getattr(config, "tts_farsi_mms_model", ""))
    if choice == "piper":
        return PiperSynthesiser(config, voice=config.tts_farsi_voice)
    try:
        return PiperSynthesiser(config, voice=config.tts_farsi_voice)
    except ImportError:
        return MmsSynthesiser(config, model_id=getattr(config, "tts_farsi_mms_model", ""))


def _default_openers() -> dict:
    from ..lang import FARSI

    return {FARSI: _farsi_synthesiser}


def open_synthesiser(config: Config) -> tuple[object | None, str]:
    from .kokoro import KokoroSynthesiser
    from .piper import PiperSynthesiser
    from .say import SaySynthesiser

    if config.tts == "fake":
        from ..fakes import FakeSynthesiser

        return FakeSynthesiser(), ""
    from .chatterbox import ChatterboxSynthesiser
    from .miso import MisoSynthesiser
    from .styletts2 import StyleTTS2Synthesiser

    # The expressive engines fall back to Kokoro when their environment is
    # missing, so `tts = "chatterbox"` before `voice models chatterbox`
    # still speaks -- and says why in the boot line.
    order = {"auto": (KokoroSynthesiser, SaySynthesiser), "kokoro": (KokoroSynthesiser,),
             "piper": (PiperSynthesiser,), "say": (SaySynthesiser,),
             "chatterbox": (ChatterboxSynthesiser, KokoroSynthesiser, SaySynthesiser),
             "styletts2": (StyleTTS2Synthesiser, KokoroSynthesiser, SaySynthesiser),
             "miso": (MisoSynthesiser, KokoroSynthesiser, SaySynthesiser)}.get(config.tts)
    if order is None:
        return None, f"unknown tts engine {config.tts!r} (auto | kokoro | piper | say | chatterbox | styletts2 | miso | fake)"
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
    # StyleTTS 2 is NOT in this tuple, on purpose. The lane pair exists
    # because Chatterbox (~1.8x) and Miso (~10x) are slower than speech,
    # so a spoken turn cannot wait for them and Kokoro takes the turns
    # beside them. StyleTTS 2 measured 0.42x warm -- faster than it
    # speaks -- so wrapping it would relegate a quick engine to answering
    # typed replies only, which is the opposite of the point.
    if isinstance(primary, (ChatterboxSynthesiser, MisoSynthesiser)) and \
            str(getattr(config, "expressive_lane", "auto")) != "always":
        # The expressive engine answers in seconds; a spoken turn cannot
        # wait for it. Kokoro (else `say`) takes the turns beside it.
        from .lanes import LaneSynthesiser

        for cls in (KokoroSynthesiser, SaySynthesiser):
            try:
                primary = LaneSynthesiser(cls(config), primary, config)
                break
            except ImportError as exc:
                reasons.append(f"{cls.name}: {exc}")
    # A first choice that fell through is said, not swallowed: `tts =
    # chatterbox` without its environment came up as Kokoro with
    # `problems=[]` (observer, 2026-09-13).
    why = "; ".join(reasons) if reasons else ""
    if not config.tts_by_language or config.tts == "piper":
        return primary, why
    return PolyglotSynthesiser(primary, config), why


__all__ = ["PolyglotSynthesiser", "open_synthesiser"]
