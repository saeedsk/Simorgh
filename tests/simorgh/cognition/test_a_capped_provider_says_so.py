"""A provider its own budget refuses is announced -- once.

Live, 2026-09-22: `together_strong` hit its 200-call daily cap at 16:16.
For the next three hours every escalation to the strong tier was
answered by the cheap model instead, and the log kept printing
`cognition.escalated route=['together_strong', 'together']` as though
the strong one had been tried. A whole SWE-bench run was scored on the
wrong model, and the only way to find out was to read the budget stream
and notice the calls had stopped.

The cause was one bare `continue`: the neighbouring "no time for this
candidate" branch logged, and this one said nothing. Guards must be
symmetric -- the silent one is always the one that hides an outage.
"""

import unittest

from simorgh.cognition.api import Purpose
from simorgh.cognition.providers.base import FloorProvider
from simorgh.cognition.router import Router

from .test_router import _budget, _FakeProvider, _FakeProviderBudget
from tests.simorgh.helpers import FakeClock


class _Logger:
    def __init__(self):
        self.lines: list[tuple[str, dict]] = []

    def warning(self, event, **kw):
        self.lines.append((event, kw))

    def info(self, event, **kw):
        self.lines.append((event, kw))

    debug = error = info

    def events(self, name):
        return [kw for event, kw in self.lines if event == name]


class ACappedProviderSaysSo(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.logger = _Logger()

    def _router(self, spendable: bool):
        strong = _FakeProvider("together_strong")
        cheap = _FakeProvider("together")
        self.strong, self.cheap = strong, cheap
        self.budget = _FakeProviderBudget(spendable=spendable)
        return Router([strong, cheap], {"together_strong": self.budget}, FloorProvider(),
                      order=("together_strong", "together"), clock=self.clock, logger=self.logger)

    async def test_the_cap_is_announced_and_the_work_goes_elsewhere(self):
        router = self._router(spendable=False)
        response, _ = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=30.0)
        self.assertEqual(response.provider, "together", "the work still gets done")
        self.assertEqual(self.strong.calls, 0)
        capped = self.logger.events("cognition.provider_capped")
        self.assertEqual(len(capped), 1)
        self.assertEqual(capped[0]["provider"], "together_strong")

    async def test_it_is_said_once_not_on_every_call(self):
        router = self._router(spendable=False)
        for _ in range(5):
            await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=30.0)
        self.assertEqual(len(self.logger.events("cognition.provider_capped")), 1,
                         "hundreds of calls an hour ask for it; one line is the news")

    async def test_and_again_when_the_window_rolls_over(self):
        router = self._router(spendable=False)
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=30.0)
        self.budget._spendable = True                     # noqa: SLF001 -- the window rolled over
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=30.0)
        self.assertEqual(len(self.logger.events("cognition.provider_uncapped")), 1)
        self.assertEqual(self.strong.calls, 1, "it is used again")


if __name__ == "__main__":
    unittest.main()
