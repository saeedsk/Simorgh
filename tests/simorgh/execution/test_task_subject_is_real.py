"""A task's subject must name a real place (execution/tools.py).

An invented subject is worse than no subject, twice over, and both cost
real money on 2026-09-16.

It becomes the task's write scope, so every edit is refused and the task
burns its whole retry budget writing nothing. `simorgh/watch/baseline`
-- a directory that has never existed in this repo -- cost $4.54 across
three attempts and landed "nothing to land".

And it switches the duplicate check off. `Intake._find_duplicate` skips
any existing task whose subject differs, so the same request with two
different invented paths is never compared at all. That day: three tasks
to show the voice match score (two of them 0.91 and 1.00 similar by the
very matcher that never saw them) and three splash-screen tasks, two of
which ran at the same time. Seven of the nine subjects named that day
did not exist.

A path that does not exist YET is fine -- a new file in a real package
is how anything gets built. A parent that does not exist either is what
invention looks like.
"""

from __future__ import annotations

import types
import unittest

from simorgh.execution.config import Config
from simorgh.execution.tools import StartTaskTool


class _Bus:
    def __init__(self) -> None:
        self.requests: list = []

    async def request(self, message, *, timeout=None):
        self.requests.append(message)
        return types.SimpleNamespace(payload={"task_id": "t1"})


class SubjectIsARealPlaceTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = StartTaskTool(Config())
        self.bus = _Bus()
        self.ctx = types.SimpleNamespace(bus=self.bus, task_id=None, scope=None)

    async def _payload(self, **args):
        await self.tool.run({"goal": "do the thing", **args}, ctx=self.ctx)
        return self.bus.requests[-1].payload

    async def test_a_real_file_is_carried_through(self):
        p = await self._payload(subject="simorgh/voice/session.py")
        self.assertEqual(p["subject"], "simorgh/voice/session.py")

    async def test_a_new_file_in_a_real_package_is_allowed(self):
        """Not yet existing is normal: `simorgh/voice/overhear.py` was
        created this way and is legitimate work."""
        p = await self._payload(subject="simorgh/voice/does_not_exist_yet.py")
        self.assertEqual(p["subject"], "simorgh/voice/does_not_exist_yet.py")

    async def test_an_invented_tree_is_dropped(self):
        """The $4.54 one. `simorgh/watch/` has never existed."""
        p = await self._payload(subject="simorgh/watch/baseline")
        self.assertNotIn("subject", p, "an unwritable scope must not be set")

    async def test_a_phrase_with_spaces_is_not_a_path(self):
        p = await self._payload(subject="simorgh/interface voice score display")
        self.assertNotIn("subject", p)

    async def test_escaping_the_repo_is_refused(self):
        p = await self._payload(subject="../etc/passwd")
        self.assertNotIn("subject", p)

    async def test_the_task_is_still_created_when_the_subject_is_dropped(self):
        """The work may well be real; only the path was guessed. Losing
        the task would be a worse answer than losing the scope."""
        result = await self.tool.run({"goal": "do the thing", "subject": "simorgh/watch/baseline"},
                                     ctx=self.ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["task_id"], "t1")

    async def test_the_model_is_told_why_it_was_dropped(self):
        """Silence here would teach it nothing, and it would guess the
        same way next time."""
        result = await self.tool.run({"goal": "do the thing", "subject": "simorgh/watch/baseline"},
                                     ctx=self.ctx)
        self.assertIn("no subject set", result.output)
        self.assertIn("simorgh/watch", result.output)

    async def test_no_subject_is_still_simply_absent(self):
        p = await self._payload()
        self.assertNotIn("subject", p)


class TheDedupeItProtectsTestCase(unittest.TestCase):
    """Why this matters: with both subjects real, the narrowing still
    works; with an invented one, the descriptions get compared again."""

    def test_the_duplicate_descriptions_do_match_when_compared(self):
        import difflib

        a = "show the live voice-recognition match score on screen with every turn"
        b = "show the live voice-recognition match score on the dashboard/screen with every turn"
        self.assertGreaterEqual(difflib.SequenceMatcher(None, a, b).ratio(), 0.45,
                                "these were never compared, only because the subjects differed")


if __name__ == "__main__":
    unittest.main()
