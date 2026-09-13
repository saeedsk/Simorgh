"""Two lanes for one voice: the quick engine for a turn, the expressive
one when there is time for it.

The creator, 2026-09-13, on Chatterbox: "the response is also slow;
how can we make Sim super responsive?" Measured that evening on the M3
Pro: Chatterbox renders 1.8-2.8 s for every second it speaks, and the
first sound of a spoken reply came 6.7-15 s after the person stopped
(the `voice:turns` stream); Kokoro's first sound comes in 0.4-1.2 s.
No setting closes that gap -- it is the model's size on this GPU. So
the honest shape is two lanes behind one door:

  fast        Kokoro -- every spoken turn, every aside
  expressive  Chatterbox (or Miso) -- a reply to a TYPED turn, `voice test`,
              a story, anything longer than `expressive_min_chars`

`[voice] expressive_lane = auto | always | off` picks the rule; the
request's `lane` carries the choice from the session to here. Both
lanes take the same voice name: Chatterbox clones a Kokoro voice from
a clip rendered once, so Sim is the same Jessica in both, only slower
and more felt in one.
"""

from __future__ import annotations

import time

from ..api import Audio

FAST, EXPRESSIVE = "fast", "expressive"


class LaneSynthesiser:
    speaks_ipa = True   # each lane's engine says for itself; `_with_tone` respells for one that cannot

    def __init__(self, fast, expressive, config) -> None:
        self._fast = fast
        self._expressive = expressive
        self._config = config
        self.last_engine = getattr(fast, "name", "")
        self.warm = False

    @property
    def name(self) -> str:
        return f"{getattr(self._fast, 'name', '')}+{getattr(self._expressive, 'name', '')}"

    def lanes(self) -> dict[str, str]:
        return {FAST: getattr(self._fast, "name", ""), EXPRESSIVE: getattr(self._expressive, "name", "")}

    def engine_for(self, lane: str):
        return self._expressive if lane == EXPRESSIVE else self._fast

    def voices(self) -> list[str]:
        out = list(self._fast.voices())
        out += [v for v in self._expressive.voices() if v not in out]
        return out

    @property
    def problems(self) -> list[str]:
        out: list[str] = []
        for engine in (self._fast, self._expressive):
            got = getattr(engine, "problems", None)
            if isinstance(got, list):
                out += got
            elif isinstance(got, dict):
                out += [f"{k}: {v}" for k, v in got.items()]
        return out

    def pace_ratio(self, lane: str = "") -> float:
        """Seconds of rendering per second of speech for `lane`, from the
        engine's last piece, or its nominal figure; 0 when unknown, and
        for the fast lane (Kokoro renders five times faster than it speaks)."""
        engine = self.engine_for(lane)
        if engine is self._fast:
            return 0.0
        own = getattr(engine, "pace_ratio", None)
        if callable(own):
            try:
                return float(own())
            except Exception:  # noqa: BLE001
                return 0.0
        took, seconds = getattr(engine, "last_took_s", 0.0), getattr(engine, "last_seconds", 0.0)
        return float(took / seconds) if took and seconds else float(getattr(engine, "nominal_pace", 0.0) or 0.0)

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "", lane: str = "") -> Audio:
        from . import _with_tone

        engine = self.engine_for(lane)
        self.last_engine = getattr(engine, "name", "")
        return await _with_tone(engine, text, voice=voice, speed=speed, tone=tone)

    async def warmup(self) -> float:
        """Both engines say one word into nothing -- the expressive one in
        the configured voice, so its reference clip is rendered and its
        conditioning cached before anyone waits on it."""
        if self.warm:
            return 0.0
        import asyncio

        started = time.monotonic()
        await self._fast.synthesise("Okay.", speed=1.0)
        self.warm = True
        # Chatterbox takes half a minute to load and condition; nobody
        # should be deaf for it. It warms behind the quick lane, and a
        # request that reaches it first simply waits on the engine's lock.
        if self._warming is None or self._warming.done():
            self._warming = asyncio.create_task(self._warm_expressive())
        return time.monotonic() - started

    async def _warm_expressive(self) -> None:
        # Not at once: Chatterbox loading beside whisper and Kokoro at
        # boot starved them -- the first spoken turn after a restart
        # waited 45 s for its transcription (2026-09-13, 15:14). The
        # quick lane gets the machine first; the slow one warms later.
        import asyncio

        delay = float(getattr(self._config, "expressive_warm_delay_s", 90.0) or 0.0)
        if delay > 0:
            await asyncio.sleep(delay)
        voice = str(getattr(self._config, "tts_voice", "") or "")
        started = time.monotonic()
        try:
            from . import _with_tone

            await _with_tone(self._expressive, "Okay.", voice=voice, speed=1.0, tone="")
            self.expressive_warmup_s = round(time.monotonic() - started, 1)
        except Exception as exc:  # noqa: BLE001 -- the slow lane's failure must not cost the fast one
            self.last_problem = f"{getattr(self._expressive, 'name', 'expressive')} warm-up failed: {exc}"

    _warming = None
    expressive_warmup_s: float = 0.0
    last_problem: str = ""

    async def warm_expressive(self) -> None:
        """Wait for the background warm-up, for callers that need it done."""
        if self._warming is not None:
            await self._warming

    async def close(self) -> None:
        if self._warming is not None and not self._warming.done():
            self._warming.cancel()
        for engine in (self._fast, self._expressive):
            close = getattr(engine, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    pass


__all__ = ["EXPRESSIVE", "FAST", "LaneSynthesiser"]
