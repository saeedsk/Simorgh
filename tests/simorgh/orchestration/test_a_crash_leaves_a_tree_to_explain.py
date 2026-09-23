"""A session that inherits a half-done tree is told so, note or no note.

The "this is attempt N, here is what earlier ones did" block was gated
on `session.carried` -- a summary an attempt writes when it ENDS. A
SIGKILL writes none, and on a first attempt there is no earlier attempt
to summarise either. So the resumed session saw a file it had no memory
of writing and wrote it again: `redone_steps: [2]` in the
kill-and-resume drill, every run (2026-09-23).

The edits are the fact. The note about them is optional.
"""

from __future__ import annotations

import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler

from .harness import Harness, run


class ACrashLeavesATreeToExplain(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = Session(task_id="t", kind="patch", mode="execute", profile=profiles.PATCH)
        self.session.attempt = 1

    async def _text(self) -> str:
        async with Harness() as h:
            assembler = Assembler(h.client("orchestration"))
            blocks = await assembler.assemble(self.session, purpose="draft", user_text="write the thing")
        return " ".join(str(b.get("content", "")) for b in blocks)

    async def test_an_interrupted_session_is_told_what_is_in_the_tree(self):
        self.session.uncommitted.add("tools/kill_resume_notes.py")
        text = await self._text()
        self.assertIn("STILL IN THE TREE", text)
        self.assertIn("tools/kill_resume_notes.py", text)
        self.assertIn("interrupted", text, "and told WHY it has no memory of writing it")

    async def test_a_retry_with_a_note_reads_as_before(self):
        self.session.carried = "attempt 1 read three files and stopped"
        self.session.attempt = 2
        text = await self._text()
        self.assertIn("Earlier attempts ran out of steps", text)
        self.assertIn("attempt 1 read three files", text)

    async def test_a_clean_first_attempt_is_told_nothing_of_the_kind(self):
        self.assertNotIn("This is attempt", await self._text())


if __name__ == "__main__":
    unittest.main()
