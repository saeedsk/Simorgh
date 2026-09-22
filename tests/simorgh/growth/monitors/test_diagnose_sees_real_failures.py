"""The monitors hand `diagnose` the failures they actually saw.

`_record_candidates` passed `diagnose.candidates([], ...)` -- an empty
list -- so a cluster of the same failure could never become a lesson;
only a falling success rate could (found 2026-09-22 building the night's
proposing step). A failure now carries its failing verify check and the
tool Guardian denied it, and a benchmark case is not the house's work.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

from . import test_service_stall as _stall


class RealFailures(_stall.StallDetectionTestCase):
    async def _fail(self, task_id: str, *, check: str = "full_suite_ran", origin: str = "human") -> None:
        await self.driver.publish(Message.new(
            topics.TASK_CREATED, source="test", clock=self.clock.now,
            payload={"task_id": task_id, "kind": "patch", "description": "fix it",
                     "depends_on": [], "mode": "execute", "origin": origin, "risk": "low"}))
        await self._pump()
        await self.driver.publish(Message.new(
            topics.VERIFY_RESULT, source="test", clock=self.clock.now,
            payload={"verification_id": f"v-{task_id}", "task_id": task_id, "verdict": "fail", "checklist": [],
                     "mechanical": {check: {"status": "failed", "detail": "x"}, "syntax": {"status": "passed"}},
                     "trajectory": {"steps": 3, "wasted": 0, "recovered_errors": 0}}))
        await self._pump()
        await self.driver.publish(Message.new(
            topics.TASK_BLOCKED, source="test", clock=self.clock.now,
            payload={"task_id": task_id, "reason": "verification failed after max revisions"}))
        await self._pump()

    async def test_three_of_the_same_failure_become_a_candidate_citing_them(self) -> None:
        for n in range(3):
            await self._fail(f"t{n}")
        found = await self.service._record_candidates([])  # noqa: SLF001
        clustered = [c for c in found if c.subject == "patch"]
        self.assertTrue(clustered, f"no cluster from three identical failures: {found}")
        self.assertIn("full_suite_ran", clustered[0].what)
        self.assertEqual(clustered[0].count, 3)

    async def test_a_benchmark_case_is_not_the_houses_work(self) -> None:
        for n in range(3):
            await self._fail(f"b{n}", origin="benchmark")
        found = await self.service._record_candidates([])  # noqa: SLF001
        self.assertFalse([c for c in found if c.subject == "patch"])


# Only the fixture is borrowed; the stall tests run in their own module.
for _name in [n for n in dir(_stall.StallDetectionTestCase) if n.startswith("test_")]:
    setattr(RealFailures, _name, None)


if __name__ == "__main__":
    unittest.main()

