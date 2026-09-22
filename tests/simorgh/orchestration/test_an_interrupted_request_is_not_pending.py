"""An interrupted request is recorded as dropped, not as still waiting.

Live, 2026-09-22: "صدای تلویزیون رو کم کن" (turn the TV down) was cancelled
by the next sentence and written into the conversation with no answer.
Seven minutes later "Hey Sim, who is talking now?" -- misheard as "You
see him, he's talking now" -- arrived, and the model turned the TV down.
"""

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Outcome, Session
from simorgh.orchestration.transcript import conversation_id, recent_lines
from simorgh.orchestration.worker import UNANSWERED_NOTE, Worker


class _Clock:
    def now(self):
        return 1_000.0


class AnInterruptedTurn(unittest.IsolatedAsyncioTestCase):
    async def test_it_is_written_down_as_not_done(self):
        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        worker = Worker.__new__(Worker)
        worker._ledger, worker._clock = ledger, _Clock()   # noqa: SLF001 -- only what _remember_exchange reads
        session = Session(task_id="s", kind="chat", mode="execute", profile=profiles.CHAT,
                          channel="voice", speaker="Saeed")
        await worker._remember_exchange(session, "صدای تلویزیون رو کم کن",  # noqa: SLF001
                                        Outcome("failed", reason="cancelled"))
        lines = await recent_lines(ledger, conversation_id("voice", "Saeed"), 10)
        self.assertEqual(lines[0], "Saeed: صدای تلویزیون رو کم کن")
        self.assertIn("not pending", lines[1])
        self.assertIn(UNANSWERED_NOTE, lines[1])


if __name__ == "__main__":
    unittest.main()
