"""A chat turn writes only under workspace/ (live 2026-09-19: a typo became
a chat turn that edited simorgh/growth/estimate/ in the live checkout)."""

import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner, chat_outside_workspace_refusal

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run


def _chat():
    return Session(task_id="c1", kind="chat", mode="execute", profile=profiles.CHAT)


class ChatWritesOnlyInWorkspace(unittest.TestCase):
    def test_the_rule(self):
        self.assertIn("start_task", chat_outside_workspace_refusal(_chat(), "replace_in_file",
                                                                   {"path": "simorgh/growth/estimate/models.py"}))
        self.assertTrue(chat_outside_workspace_refusal(_chat(), "apply_source_patch", {"subject": "README.md"}))
        self.assertEqual(chat_outside_workspace_refusal(_chat(), "apply_source_patch", {"subject": "workspace/deck/make.py"}), "")
        self.assertEqual(chat_outside_workspace_refusal(_chat(), "read_file", {"path": "simorgh/x.py"}), "")
        patch = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        self.assertEqual(chat_outside_workspace_refusal(patch, "replace_in_file", {"path": "simorgh/x.py"}), "")

    @run
    async def test_a_chat_edit_of_source_is_never_proposed(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "replace_in_file",
                                 "args": {"path": "simorgh/growth/estimate/models.py", "code": "<<<<<<< SEARCH\\na\\n=======\\nb\\n>>>>>>> REPLACE"}}]},
                {"text": "ok"},
            ])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start()
            await gx.start()
            session = _chat()
            await SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now).run(session, user_text="?/tas")
            self.assertEqual(gx.proposals, [])
            self.assertIn("writes only under workspace/", session.steps[0].summary)
            await cognition.stop()
            await gx.stop()
