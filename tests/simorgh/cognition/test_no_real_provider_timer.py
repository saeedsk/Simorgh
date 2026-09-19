"""`health()` degrades after 300 s of floor-only replies, counted from the
FIRST floor reply (2026-09-18 evaluation, C12: the timer was reset on
every floor reply, so it never fired while the system was still asking)."""

import unittest

from simorgh.cognition.service import Service


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t


class TheTimerStartsAtTheFirstFloor(unittest.IsolatedAsyncioTestCase):
    async def test_floor_replies_every_minute_degrade_after_five(self):
        from types import SimpleNamespace

        svc = Service()
        clock = _Clock()
        svc._ctx = SimpleNamespace(clock=clock)  # noqa: SLF001
        for _ in range(6):
            svc._note_reply(floor=True)  # noqa: SLF001
            clock.t += 60.0
        self.assertEqual((await svc.health()).status, "degraded")
        svc._note_reply(floor=False)  # noqa: SLF001
        self.assertEqual((await svc.health()).status, "ok")
