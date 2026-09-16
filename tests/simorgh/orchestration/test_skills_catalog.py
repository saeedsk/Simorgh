"""Agent Skills in a session: the catalog in `task_rules`, and `use_skill`
returning one skill's instructions (docs/plans/agent-skills-design.md step 2)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

PDF = """---
name: pdf-reading
description: Read household PDFs -- bills, statements, school letters
---
# Reading a PDF

1. Extract the text with the pdf tool.
2. Quote the figure, never guess it.
"""


def _root(tmp: str) -> Path:
    folder = Path(tmp) / "skills" / "pdf-reading"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(PDF, encoding="utf-8")
    return Path(tmp) / "skills"


class SkillsInASession(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _runner(self, h, *, enabled: bool) -> SessionRunner:
        return SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now,
                             skills_enabled=enabled, skills_roots=(str(self.root),))

    @run
    async def test_the_catalog_is_in_the_rules_and_the_skill_loads(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"text": "USE_SKILL: pdf-reading", "tool_calls": [{"tool": "use_skill", "args": {"argument": "pdf-reading"}}]},
                {"text": "The total is £81.20."},
            ])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start()
            await gx.start()
            session = Session(task_id="t-skill", kind="chat", mode="execute", profile=profiles.CHAT)
            outcome = await self._runner(h, enabled=True).run(session, user_text="what is the total on this bill?")
            await cognition.stop()
            await gx.stop()

            rules = cognition.calls[0].payload["task_rules"]
            self.assertIn("pdf-reading: Read household PDFs", rules)
            self.assertIn("USE_SKILL", rules)
            self.assertIn("use_skill", cognition.calls[0].payload["tools"])
            # The instructions arrive only when asked for, as the result.
            fed_back = "\n".join(m["content"] for m in cognition.calls[1].payload["messages"])
            self.assertIn("Extract the text with the pdf tool", fed_back)
            self.assertIn("Skill pdf-reading", fed_back)
            self.assertEqual(gx.proposals, [], "a skill is instructions, not an action to approve")
            self.assertEqual(outcome.kind, "completed")
            self.assertEqual([s.tool for s in session.steps if s.tool], ["use_skill"])

    @run
    async def test_nothing_when_skills_are_off(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "The total is £81.20."}])
            await cognition.start()
            session = Session(task_id="t-noskill", kind="chat", mode="execute", profile=profiles.CHAT)
            await self._runner(h, enabled=False).run(session, user_text="what is the total?")
            await cognition.stop()
            rules = cognition.calls[0].payload["task_rules"]
            self.assertNotIn("pdf-reading", rules)
            self.assertNotIn("use_skill", cognition.calls[0].payload["tools"])

    @run
    async def test_a_name_that_is_not_a_skill_says_what_is(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"text": "USE_SKILL: spreadsheets", "tool_calls": [{"tool": "use_skill", "args": {"argument": "spreadsheets"}}]},
                {"text": "I do not have that skill."},
            ])
            await cognition.start()
            session = Session(task_id="t-badskill", kind="chat", mode="execute", profile=profiles.CHAT)
            await self._runner(h, enabled=True).run(session, user_text="use the spreadsheet skill")
            await cognition.stop()
            fed_back = "\n".join(m["content"] for m in cognition.calls[1].payload["messages"])
            self.assertIn("no skill called 'spreadsheets'", fed_back)
            self.assertIn("pdf-reading", fed_back)


if __name__ == "__main__":
    unittest.main()
