"""Stage 8 item 8: a night is bounded.

Everything in this package happens when nobody is asking for anything.
Left to itself that is an unbounded amount of work on a paid model, at
three in the morning, with nobody watching -- the exact shape of a bill
nobody meant to run up.

So: a fixed list of steps, each run once, cheapest first, against one
budget that is a cap on the DAY rather than on the function. The
acceptance case is at the bottom -- a fake-clock night runs each step
once and stops at the cap.
"""

import unittest

from simorgh.growth.night import DEFAULT_NIGHTLY_USD, Step, run_night


class _Clock:
    """A fake clock: a night must not depend on how long anything took."""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def _step(name: str, *, est_usd: float = 0.0, spent=None, raises: str = "", ran=None) -> Step:
    async def _run():
        if ran is not None:
            ran.append(name)
        if raises:
            raise RuntimeError(raises)
        return {"detail": f"{name} done", **({"spent_usd": spent} if spent is not None else {})}

    return Step(name, _run, est_usd=est_usd)


class ANight(unittest.IsolatedAsyncioTestCase):
    async def test_each_step_runs_exactly_once(self):
        ran: list[str] = []
        report = await run_night([_step("evals", ran=ran), _step("review", ran=ran),
                                  _step("diagnose", ran=ran)], clock=_Clock())
        self.assertEqual(ran, ["evals", "review", "diagnose"])
        self.assertEqual(report.ran, ["evals", "review", "diagnose"])
        self.assertEqual(report.stopped_at, "")

    async def test_it_stops_when_the_next_step_would_not_fit(self):
        ran: list[str] = []
        report = await run_night(
            [_step("free", ran=ran), _step("cheap", est_usd=0.30, spent=0.30, ran=ran),
             _step("dear", est_usd=0.40, ran=ran), _step("also_free", ran=ran)],
            budget_usd=0.50, clock=_Clock())
        self.assertEqual(ran, ["free", "cheap", "also_free"])
        self.assertEqual(report.stopped_at, "dear")
        self.assertIn("$0.40", [s.skipped for s in report.steps if s.name == "dear"][0])

    async def test_the_cap_is_checked_before_the_call_not_after(self):
        """A model call cannot be taken back once it has been made, so
        an after-the-fact cap is not a cap."""
        ran: list[str] = []
        await run_night([_step("dear", est_usd=99.0, ran=ran)], budget_usd=0.50, clock=_Clock())
        self.assertEqual(ran, [])

    async def test_what_the_day_already_spent_counts_against_the_cap(self):
        ran: list[str] = []
        report = await run_night([_step("dear", est_usd=0.30, ran=ran)],
                                 budget_usd=0.50, spent_so_far=0.40, clock=_Clock())
        self.assertEqual(ran, [], "a cap on the night alone is not a cap on the day")
        self.assertEqual(report.stopped_at, "dear")

    async def test_an_uninstrumented_step_is_charged_its_estimate(self):
        """Guessing zero for a step that does not report is how a
        budget quietly stops being one."""
        async def _quiet():
            return None

        report = await run_night([Step("quiet", _quiet, est_usd=0.20)], budget_usd=0.50,
                                 clock=_Clock())
        self.assertAlmostEqual(report.spent_usd, 0.20)

    async def test_one_bad_step_does_not_lose_the_night(self):
        ran: list[str] = []
        report = await run_night([_step("evals", ran=ran), _step("broken", raises="boom", ran=ran),
                                  _step("review", ran=ran)], clock=_Clock())
        self.assertEqual(ran, ["evals", "broken", "review"])
        self.assertEqual(report.failed, ["broken"])
        self.assertIn("boom", [s.detail for s in report.steps if s.name == "broken"][0])

    async def test_the_report_says_what_happened(self):
        report = await run_night([_step("evals"), _step("dear", est_usd=9.0)], budget_usd=0.5,
                                 clock=_Clock())
        payload = report.as_dict()
        self.assertEqual(payload["ran"], ["evals"])
        self.assertEqual(payload["stopped_at"], "dear")
        self.assertEqual(payload["budget_usd"], 0.5)

    async def test_the_default_cap_is_small_enough_to_notice(self):
        """It runs every night; a cap nobody notices is too high."""
        self.assertLessEqual(DEFAULT_NIGHTLY_USD, 1.0)


class TheRealNight(unittest.IsolatedAsyncioTestCase):
    """The steps the subsystem actually runs, in the order it runs
    them: free things first, so stopping early loses the least."""

    def _service(self):
        from simorgh.growth.service import Service

        service = Service.__new__(Service)
        service._ctx = None  # noqa: SLF001
        service._nightly_usd = DEFAULT_NIGHTLY_USD  # noqa: SLF001
        service._spent_today = 0.0  # noqa: SLF001
        service._spent_day = None  # noqa: SLF001
        from simorgh.growth.measure import MeasureConfig

        service._measure = MeasureConfig()  # noqa: SLF001 -- off, the default
        service._cases_for = None  # noqa: SLF001
        from simorgh.growth.propose import ProposeConfig

        service._propose = ProposeConfig()  # noqa: SLF001 -- off, the default
        service._think = service._agents = None  # noqa: SLF001
        service._candidates = []  # noqa: SLF001
        service.retired = 0
        service.last_night = None
        service.policies = None
        return service

    def test_the_free_steps_come_first(self):
        steps = self._service()._night_steps()  # noqa: SLF001
        self.assertEqual([s.name for s in steps], ["evals", "review", "diagnose", "propose", "measure"])
        self.assertTrue(all(s.est_usd == 0.0 for s in steps),
                        "with proposing and measuring off (the default) every step is free; "
                        "the paid steps go last when they are switched on")

    def test_the_cap_comes_from_the_config(self):
        """A setting nothing reads is the bug this codebase keeps
        finding, so the wire is pinned from this end."""
        from simorgh.growth.service import nightly_usd

        self.assertEqual(nightly_usd({"nightly_usd": 2.5}), 2.5)
        self.assertEqual(nightly_usd({}), DEFAULT_NIGHTLY_USD)

    def test_an_unreadable_cap_falls_back_rather_than_off(self):
        """A malformed number must never be the reason a night spends
        without limit."""
        from simorgh.growth.service import nightly_usd

        for bad in ({"nightly_usd": "lots"}, {"nightly_usd": None}, None):
            self.assertEqual(nightly_usd(bad), DEFAULT_NIGHTLY_USD)

    async def test_a_night_with_nothing_wired_still_completes(self):
        service = self._service()

        class _Estimate:
            _config = None

            @staticmethod
            def load_evals(_path):
                return 0

        class _Monitors:
            class _Patterns:
                @staticmethod
                def mine(_now):
                    return []

            _patterns = _Patterns()

            @staticmethod
            async def _record_candidates(_patterns):
                return []

        service._parts = {"estimate": _Estimate(), "monitors": _Monitors(),  # noqa: SLF001
                          "explore": object()}
        await service._on_sleep(None)  # noqa: SLF001
        self.assertEqual(service.last_night.ran, ["evals", "review", "diagnose"])
        self.assertEqual(service.last_night.spent_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
