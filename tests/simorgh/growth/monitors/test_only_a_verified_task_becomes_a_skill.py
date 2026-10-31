"""Only a task Verification passed is turned into a skill.

Live 2026-10-30: the build of a listings page for 95120 (task
ca3e8e68cc75) ended mid-sentence ("Let me verify the page renders."),
landed nothing, and Verification said insufficient_evidence -- five of six
required checks unanswered. It was still `task.completed`, and the
distiller took that as solved: it queued a skill task that ran 57 steps
and asked the creator four times to approve it while his real request
was still being built. The creator: "that was a wrong decision".
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from simorgh.growth.monitors.service import Service, _TaskMeta
from tests.simorgh.helpers import FakeClock

META = dict(kind="patch", origin="human",
            description="build a web page of real estate listings in 95120 with a map",
            tools_used={"search_listings", "geocode", "browse_page", "apply_source_patch"})


class OnlyAVerifiedTaskBecomesASkill(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = Service()
        self.service._ctx = SimpleNamespace(clock=FakeClock())  # noqa: SLF001
        self.created: list[dict] = []

        async def _publish(_message, topic, payload):
            self.created.append(payload)

        async def _append(*_a, **_k):
            return None

        self.service._publish = _publish  # noqa: SLF001
        self.service._append = _append  # noqa: SLF001
        self.service._existing_skills = lambda: set()  # noqa: SLF001

    async def _finish(self, task_id: str, verdict: str | None) -> None:
        if verdict is not None:
            await self.service._on_verify_result(SimpleNamespace(  # noqa: SLF001
                payload={"task_id": task_id, "verdict": verdict}))
        await self.service._maybe_distil(SimpleNamespace(ts=0.0), task_id,  # noqa: SLF001
                                         _TaskMeta(**META), True)

    async def test_completed_with_insufficient_evidence_is_not_distilled(self):
        await self._finish("ca3e8e68cc75", "insufficient_evidence")
        self.assertEqual(self.created, [])

    async def test_completed_with_no_verdict_is_not_distilled(self):
        await self._finish("t-unverified", None)
        self.assertEqual(self.created, [])

    async def test_a_verified_pass_still_is(self):
        await self._finish("t-pass", "pass")
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.created[0]["kind"], "skill")


if __name__ == "__main__":
    unittest.main()
