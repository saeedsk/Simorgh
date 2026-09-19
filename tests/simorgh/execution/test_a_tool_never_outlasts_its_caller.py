"""Stage 1 item 5: a request with 2 s left never waits 60 s in a tool."""

import unittest

from simorgh.cognition.service import _within_deadline
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.execution.service import within_deadline


def _approved(deadline):
    return Message.new(topics.ACTION_APPROVED, source="guardian", deadline=deadline, payload={
        "action_id": "a1", "tool": "run_tests", "args_sha256": "x", "expires_at": 0.0, "approval_token": "t",
        "mode_at_approval": "guarded"})


class ATimeoutNeverOutlastsTheCaller(unittest.TestCase):
    def test_execution_shrinks_to_what_is_left(self):
        self.assertEqual(within_deadline(60.0, _approved(1002.0), now=1000.0), 2.0)
        self.assertEqual(within_deadline(60.0, _approved(None), now=1000.0), 60.0)
        self.assertEqual(within_deadline(5.0, _approved(2000.0), now=1000.0), 5.0)
        self.assertEqual(within_deadline(60.0, _approved(999.0), now=1000.0), 0.1)

    def test_cognition_leaves_room_for_its_reply(self):
        think = Message.new(topics.COGNITION_THINK, source="o", deadline=1010.0, payload={"purpose": "chat"})
        self.assertEqual(_within_deadline(90.0, think, 1000.0), 9.5)
        self.assertEqual(_within_deadline(5.0, think, 1000.0), 5.0)
        # Never below one Router candidate's minimum (5 s): less is a floor reply by default.
        self.assertEqual(_within_deadline(90.0, think, 1008.0), 5.0)
