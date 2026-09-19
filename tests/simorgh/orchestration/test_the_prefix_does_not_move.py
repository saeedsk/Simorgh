"""Stage 4 item 4: two chat turns send the same `task_rules`; the person's
words and the date travel in the messages instead."""

import asyncio
import unittest

from simorgh.orchestration import profiles, scaffolds
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition
from .harness import Harness, run


class ThePrefixDoesNotMove(unittest.TestCase):
    @run
    async def test_two_chat_turns_share_task_rules(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "sure"}])
            await cognition.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0)
            for i, words in enumerate(("what time is it", "and the weather?")):
                session = Session(task_id=f"t{i}", kind="chat", mode="execute", profile=profiles.CHAT,
                                  user_text=words)
                await asyncio.wait_for(runner.run(session, user_text=words), timeout=10)
            await cognition.stop()
        first, second = (c.payload for c in cognition.calls[:2])
        self.assertEqual(first["task_rules"], second["task_rules"])
        self.assertNotIn("what time is it", first["task_rules"])
        self.assertNotIn("Right now it is", first["task_rules"])
        last = first["messages"][-1]["content"]
        self.assertTrue(last.startswith("Right now it is"), last[:80])
        asked = [m for m in first["messages"] if str(m.get("content")).endswith("what time is it")]
        self.assertTrue(asked and asked[0].get("protected"))

    def test_the_note_goes_to_the_latest_user_turn(self):
        out = scaffolds.with_turn_note([{"role": "user", "content": "a"}], "NOTE")
        self.assertEqual(out[-1]["content"], "NOTE\n\na")
        out = scaffolds.with_turn_note([{"role": "tool", "content": "r"}], "NOTE")
        self.assertEqual(out[-1], {"role": "user", "content": "NOTE"})
        self.assertEqual(scaffolds.with_turn_note([], ""), [])


if __name__ == "__main__":
    unittest.main()
