"""Stage 7 item 6, the session half: one drifting verdict is a bad patch,
two in a row is a direction -- the attempt ends for re-planning instead
of spending the rest of the budget going further the wrong way."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.progress import ProgressNote
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run

NOTE = ProgressNote(goal="add the docstring", done=["read the file"], learned=[], next="read it again")


class TheCritic(unittest.TestCase):
    async def _verdicts(self, h, answers):
        bus, asked = h.client("verification"), []

        async def _critic(message):
            asked.append(message.payload)
            await bus.reply(message, type=topics.VERIFY_CHECKPOINT_REPLY,
                            payload=answers[min(len(asked) - 1, len(answers) - 1)])

        return await bus.subscribe(topics.VERIFY_CHECKPOINT_REQUEST, _critic), asked

    @run
    async def test_two_drifting_verdicts_end_the_attempt(self):
        async with Harness() as h:
            sub, asked = await self._verdicts(h, [{"verdict": "drifting", "unmet": ["nothing written yet"],
                                                   "next": "write the file"}])
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH,
                              user_text="add the docstring")
            session.acceptance = ["the file has a docstring"]
            await runner._checkpoint_critic(session, NOTE)  # noqa: SLF001
            self.assertEqual(session.drifting, 1)
            self.assertEqual(session.replan, "", "one wobble is not a direction")
            self.assertIn("write the file", session.messages[-1]["content"])

            await runner._checkpoint_critic(session, NOTE)  # noqa: SLF001
            await sub.unsubscribe()
        self.assertEqual(session.drifting, 2)
        self.assertIn("nothing written yet", session.replan)
        self.assertEqual(asked[0]["acceptance"], ["the file has a docstring"])

    @run
    async def test_blocked_ends_it_at_once_and_on_track_resets(self):
        async with Harness() as h:
            sub, _ = await self._verdicts(h, [{"verdict": "blocked", "why": "the tool is refused"}])
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t2", kind="patch", mode="execute", profile=profiles.PATCH)
            await runner._checkpoint_critic(session, NOTE)  # noqa: SLF001
            await sub.unsubscribe()
        self.assertIn("blocked", session.replan)

    @run
    async def test_insufficient_evidence_changes_nothing(self):
        async with Harness() as h:
            sub, _ = await self._verdicts(h, [{"verdict": "insufficient_evidence", "why": "the note says little"}])
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t3", kind="patch", mode="execute", profile=profiles.PATCH)
            session.drifting = 1
            await runner._checkpoint_critic(session, NOTE)  # noqa: SLF001
            await sub.unsubscribe()
        self.assertEqual((session.drifting, session.replan), (0, ""), "not knowing is not drifting")

    @run
    async def test_no_critic_is_not_a_verdict(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, think_timeout_s=0.05)
            session = Session(task_id="t4", kind="patch", mode="execute", profile=profiles.PATCH)
            await runner._checkpoint_critic(session, NOTE)  # noqa: SLF001
        self.assertEqual((session.drifting, session.replan), (0, ""))


if __name__ == "__main__":
    unittest.main()
