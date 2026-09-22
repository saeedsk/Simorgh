"""A task that wrote no code lands nothing, and must say so.

`worktree_land` returns ok for a worktree that made no commits -- there
was nothing to refuse -- and the step line prefixed that with "landed on
main:". Live on 2026-09-22 a SWE-bench run in which NO case produced a
patch reported a clean landing for every case, and published
`learn.self_patch.applied` each time: Learning, the Self Model,
Reflection, Curiosity and Planning were told Sim had changed its own
code, with main's own sha as the "patch".
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner
from simorgh.orchestration.tools import forget_registered, note_registered

from .fakes import FakeCognition, FakeVerification
from .harness import Harness, run
from .test_worktree_flow import _SCRIPT, WorktreeExecution

# The live shape: the model believes it edited and committed -- it did,
# in a checkout that is not this worktree -- so the session reaches
# landing with nothing of its own to land.


class _EmptyLanding(WorktreeExecution):
    """`worktree_land` on a worktree that made no commits."""

    async def _on(self, message):
        if message.payload["tool"] != "worktree_land":
            await super()._on(message)
            return
        self.proposals.append(message)
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": True, "output_ref": "",
            "stdout_preview": "nothing to land: the worktree made no commits",
            "duration_ms": 1, "side_effects": [],
        }, source="execution"))


class NothingLandedIsNotALanding(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        forget_registered()
        for name in (*profiles.PATCH.tools, "worktree_open", "worktree_land", "worktree_close"):
            note_registered(name)

    def tearDown(self) -> None:
        forget_registered()
        self._tmp.cleanup()

    @run
    async def test_a_worktree_with_no_commits_is_not_a_landing(self):
        async with Harness() as h:
            patches: list = []
            sub = await h.client("t").subscribe(topics.LEARN_SELF_PATCH_APPLIED, lambda m: patches.append(m))
            cognition = FakeCognition(h.client("cognition"), script=_SCRIPT)
            gx = _EmptyLanding(h.client("guardian"), self.path)
            verification = FakeVerification(h.client("verification"), ["pass"])
            for fake in (cognition, gx, verification):
                await fake.start()

            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, worktrees=True)
            session = Session(task_id="t-empty", kind="patch", mode="execute", profile=profiles.PATCH)
            await runner.run(session, user_text="fix the bug")

            landing = next((s for s in session.steps if s.tool == "worktree_land"), None)
            self.assertIsNotNone(landing, "no landing step")
            self.assertIn("nothing landed", landing.summary)
            self.assertNotIn("landed on main", landing.summary)
            self.assertFalse(landing.ok, "nothing was landed, so nothing succeeded")
            self.assertEqual(patches, [], "Sim did not change its own code")

            await sub.unsubscribe()
            for fake in (cognition, gx, verification):
                await fake.stop()


if __name__ == "__main__":
    unittest.main()
