"""A crashed attempt's edits belong to the attempt that resumes them.

`kept`/`created` come from the `task.edits_kept` record an attempt
writes when it ENDS. A SIGKILL writes nothing -- which is the case
resume exists for -- so the resumed session did not know it owned the
files the dead one had written:

    git_commit  refused: this task did not write tools/kill_resume_notes.py,
                so it may not commit it. What it wrote: nothing.

twice, and the task could never finish. Found by the kill-and-resume
drill on 2026-09-23, and only by reading its step log: the drill itself
reported "unfinished", which is true and says nothing.

A step records its side effects as it happens, so the steps are the
record a crash cannot destroy.
"""

from __future__ import annotations

import unittest

from simorgh.orchestration.api import Session
from simorgh.orchestration.resume import _claim_written  # noqa: PLC2701 -- the thing under test


def _attempt(*effects: tuple[str, ...]) -> dict:
    return {"steps": [{"tool": "apply_source_patch", "side_effects": list(e)} for e in effects],
            "kept": [], "created": [], "ended": None, "reason": "", "note": "", "note_at": 0}


class AKilledAttemptStillOwnsItsEdits(unittest.TestCase):
    def setUp(self):
        self.session = Session(task_id="t", kind="patch", mode="execute", profile=None)

    def test_a_file_written_before_the_kill_is_this_sessions_to_commit(self):
        _claim_written(self.session, [_attempt(("file_create:tools/kill_resume_notes.py",))])
        self.assertIn("tools/kill_resume_notes.py", self.session.wrote)
        self.assertIn("tools/kill_resume_notes.py", self.session.uncommitted)
        self.assertIn("tools/kill_resume_notes.py", self.session.created)

    def test_a_scratch_file_is_written_but_never_uncommitted(self):
        """`workspace/` is gitignored by design: there is no commit to
        make, and treating it as source would block the task and have
        cleanup delete it."""
        _claim_written(self.session, [_attempt(("file_write:workspace/scratch/notes.md",))])
        self.assertIn("workspace/scratch/notes.md", self.session.wrote)
        self.assertEqual(self.session.uncommitted, set())

    def test_effects_that_are_not_writes_are_ignored(self):
        _claim_written(self.session, [_attempt(("git_commit:tools/x.py", "worktree_land:abc123"))])
        self.assertEqual((self.session.wrote, self.session.uncommitted), (set(), set()))

    def test_several_attempts_all_count(self):
        _claim_written(self.session, [_attempt(("file_create:a.py",)), _attempt(("file_write:b.py",))])
        self.assertEqual(self.session.wrote, {"a.py", "b.py"})

    def test_no_steps_no_claim(self):
        _claim_written(self.session, [])
        self.assertEqual(self.session.wrote, set())


if __name__ == "__main__":
    unittest.main()
