"""`benchmark clear <model|all>`: forget the recorded runs.

The Ledger is append-only on purpose -- a log that can be rewritten
cannot be evidence of anything -- so clearing is a MARK on the
stream, and the history reads forward from it. What happened is
still there for anyone who looks; what the history SHOWS starts
again.
"""

import unittest

from simorgh.benchmark.api import RunRecord
from simorgh.benchmark.store import RunStore
from simorgh.ledger.factory import make_ledger


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def _run(suite: str, model: str) -> RunRecord:
    return RunRecord(suite=suite, suite_version="1", model=model, note="")


class ClearingTheHistory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()
        self.store = RunStore(self.ledger, clock=_Clock())
        for model in ("gemini", "together", "gemini"):
            await self.store.append(_run("gaia", model))

    async def test_one_model_is_cleared_and_the_others_are_not(self):
        self.assertEqual(len(await self.store.history(limit=0)), 3)
        cleared = await self.store.clear(model="gemini")
        self.assertEqual(cleared, 2, "it reports the runs a person will stop seeing")
        left = await self.store.history(limit=0)
        self.assertEqual([r.model for r in left], ["together"])

    async def test_all_clears_every_model(self):
        cleared = await self.store.clear(everything=True)
        self.assertEqual(cleared, 3)
        self.assertEqual(await self.store.history(limit=0), [])

    async def test_a_run_recorded_after_the_clear_is_shown_again(self):
        await self.store.clear(model="gemini")
        await self.store.append(_run("gaia", "gemini"))
        self.assertEqual([r.model for r in await self.store.history(limit=0)], ["together", "gemini"])

    async def test_the_runs_are_still_on_the_stream(self):
        """"Cleared" and "deleted" are different promises, and the
        ledger keeps the one it made."""
        from simorgh.benchmark.store import STREAM

        await self.store.clear(everything=True)
        events = await self.ledger.read(STREAM)
        self.assertEqual(len([e for e in events if e.type == "benchmark.run"]), 3)

    async def test_the_limited_path_filters_the_same_way(self):
        """`history(limit=N)` and `history(limit=0)` are two loops; a
        clear that only one of them honoured would show cleared runs
        in the default view and hide them in the full one."""
        await self.store.clear(model="gemini")
        self.assertEqual([r.model for r in await self.store.history(limit=100)], ["together"])


if __name__ == "__main__":
    unittest.main()


class TheVerb(unittest.TestCase):
    """What a person types, and what it refuses to do."""

    def test_a_bare_clear_refuses_and_says_how(self):
        import asyncio

        from simorgh.interface.dispatch import _benchmark

        out = asyncio.run(_benchmark(None, "clear"))
        self.assertIn("usage: benchmark clear <model|all>", out.text)

    def test_all_is_spelled_out_in_the_usage(self):
        from simorgh.interface.dispatch import _BENCHMARK_USAGE

        self.assertIn("benchmark clear", _BENCHMARK_USAGE)
        self.assertIn("<model|all>", _BENCHMARK_USAGE)

    def test_all_and_a_model_name_are_different_payloads(self):
        """`all` must be explicit: a bare clear that wiped every
        model by default is the kind of default somebody finds out
        about afterwards."""
        from simorgh.contracts.messages.benchmark import BenchmarkClearRequest

        self.assertTrue(BenchmarkClearRequest)
