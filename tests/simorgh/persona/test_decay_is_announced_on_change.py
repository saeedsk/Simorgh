"""Mood decay is announced when it has moved, not every 5 s tick
(2026-09-18 evaluation, V6: 93% of persona:state events were decay ticks
that moved the mood by less than a hundredth)."""

import unittest
from types import SimpleNamespace

from simorgh.persona.config import Config
from simorgh.persona.mood import EmotionalState, MoodEngine
from simorgh.persona.service import Service


class _Bus:
    def __init__(self):
        self.published = []

    async def publish(self, message):
        self.published.append(message)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


class DecayIsAnnouncedOnChange(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_decay_over_a_hundred_ticks_is_announced_a_few_times(self):
        svc = Service(Config())
        bus, clock = _Bus(), _Clock()
        svc._ctx = SimpleNamespace(bus=bus, clock=clock, source="persona", ledger=SimpleNamespace(append=_noop))  # noqa: SLF001
        svc._last_decay_ts = 0.0  # noqa: SLF001
        svc._mood = MoodEngine(clock=clock, history_limit=50, baseline=_baseline())  # noqa: SLF001
        svc._mood.apply_delta(valence=0.6, arousal=0.5, cognitive_load=0.0, source="test")  # noqa: SLF001
        for _ in range(100):
            clock.t += 5.0
            await svc._on_tick_second(None)  # noqa: SLF001
        self.assertGreater(len(bus.published), 0, "a large drift is still announced")
        self.assertLess(len(bus.published), 40, f"{len(bus.published)} announcements for 100 ticks")


def _baseline():
    import inspect
    fields = inspect.signature(EmotionalState).parameters
    return EmotionalState(**{k: 0.0 for k in fields if k in ("valence", "arousal", "cognitive_load")})


async def _noop(*a, **k):
    return None
