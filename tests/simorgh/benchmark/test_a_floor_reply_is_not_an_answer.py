"""A case Cognition's offline floor answered is skipped, not scored wrong.

2026-09-14, a ten-copy benchmark wave: one `RemoteDisconnected` from
Together put copy 1 on the floor for its cooldown, and 16 of a 20-case
BFCL run "completed in 0.0s -- no real drafting intelligence available",
each scored as a wrong answer against GLM-5.3-Flash. The model had not
been asked. `task.completed` now says `floor`, and the runner skips it.
"""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.benchmark.api import Case
from simorgh.benchmark.config import Config
from simorgh.benchmark.runner import Runner, _AnswerWatch, _FLOORED
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message


class _Bus:
    def __init__(self):
        self.handlers: dict[str, list] = {}

    async def subscribe(self, topic, handler, **_):
        self.handlers.setdefault(topic, []).append(handler)

        class _Sub:
            async def unsubscribe(self_inner):
                pass
        return _Sub()

    async def deliver(self, topic, payload):
        for h in self.handlers.get(topic, []):
            await h(Message.new(topic, source="test", payload=payload))


class AFloorCompletionTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_the_watch_reports_it_as_not_the_model(self):
        watch = _AnswerWatch(_Bus())
        await watch.start()
        await watch._bus.deliver(topics.TASK_COMPLETED, {  # noqa: SLF001
            "task_id": "t1", "result_summary": "[floor] no real drafting intelligence available -- nothing drafted",
            "artifacts": [], "verification_ref": None, "floor": True})
        text, _steps, error = await watch.wait("t1", 0.1)
        self.assertEqual(text, "")
        self.assertTrue(error.startswith(_FLOORED))

    async def test_a_real_completion_is_still_the_answer(self):
        watch = _AnswerWatch(_Bus())
        await watch.start()
        await watch._bus.deliver(topics.TASK_COMPLETED, {  # noqa: SLF001
            "task_id": "t1", "result_summary": "FINAL ANSWER: 3", "artifacts": [], "verification_ref": None})
        self.assertEqual(await watch.wait("t1", 0.1), ("FINAL ANSWER: 3", 0, ""))

    async def test_the_case_is_skipped_not_wrong(self):
        runner = Runner.__new__(Runner)
        runner._config = Config()
        case = Case(id="c1", question="q", answer="3", level="1", suite="gaia", mode="gaia")
        floored = ("", 1, 0.0, f"{_FLOORED} the offline floor answered, with no model available")
        with mock.patch.object(Runner, "_ask", return_value=floored):
            result = await runner.run_case(case)
        self.assertTrue(result.skipped)
        self.assertFalse(result.correct)


class TheCaseWaitsOutTheOutage(unittest.IsolatedAsyncioTestCase):
    """2026-09-15, arm 25: one Together 503 put the copy on the floor and
    21 of 26 GAIA cases were skipped in two seconds. A floored case now
    waits for the model and runs again."""

    FLOORED = ("", 1, 0.0, f"{_FLOORED} the offline floor answered, with no model available")

    def _runner(self, sleeps):
        async def sleep(seconds):
            sleeps.append(seconds)
        return Runner(_Bus(), config=Config(floor_retries=3, floor_retry_wait_s=60.0), sleep=sleep)

    async def test_it_runs_again_once_the_model_is_back(self):
        from simorgh.benchmark.api import Suite

        sleeps: list[float] = []
        runner = self._runner(sleeps)
        case = Case(id="c1", question="q", answer="3", level="1", suite="gaia", mode="gaia")
        answers = [self.FLOORED, self.FLOORED, ("FINAL ANSWER: 3", 4, 0.01, "")]
        with mock.patch.object(Runner, "_ask", side_effect=answers):
            record = await runner.run(Suite(name="gaia", cases=(case,)))
        self.assertEqual(sleeps, [60.0, 120.0])
        self.assertEqual(len(record.results), 1)
        self.assertTrue(record.results[0].correct)
        self.assertFalse(record.results[0].skipped)

    async def test_it_stays_skipped_if_the_model_never_returns(self):
        from simorgh.benchmark.api import Suite

        sleeps: list[float] = []
        runner = self._runner(sleeps)
        case = Case(id="c1", question="q", answer="3", level="1", suite="gaia", mode="gaia")
        with mock.patch.object(Runner, "_ask", return_value=self.FLOORED):
            record = await runner.run(Suite(name="gaia", cases=(case,)))
        self.assertEqual(sleeps, [60.0, 120.0, 240.0])
        self.assertTrue(record.results[0].skipped)


if __name__ == "__main__":
    unittest.main()
