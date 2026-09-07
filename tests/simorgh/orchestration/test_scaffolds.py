"""`Profile.scaffold` -> Cognition's protected `task_rules` block.

Before this, `scaffold` was carried from `profiles.py` into
`Assembler.assemble(session, purpose)` and dropped, and nobody ever
filled Cognition's `task_rules` slot. A patch session reached the model
with a bare list of tool names and no statement of what finishing means
-- live 2026-09-07, a run applied its edit and never committed it.
"""

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles, scaffolds
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run


class TestRenderedRules(unittest.TestCase):
    def test_the_patch_scaffold_says_to_commit_what_it_applied(self):
        text = scaffolds.render(profiles.PATCH)
        self.assertIn("git_commit", text)
        self.assertIn("apply_source_patch", text)
        self.assertIn("uncommitted", text)

    def test_every_tool_the_profile_allows_is_named(self):
        for profile in (profiles.CHAT, profiles.PATCH, profiles.RESEARCH, profiles.PLAN, profiles.SKILL):
            text = scaffolds.render(profile)
            for tool in profile.tools:
                self.assertIn(tool, text, f"{profile.name} scaffold never mentions {tool}")

    def test_a_tool_with_no_note_is_still_listed_by_name(self):
        """The note table must never be able to silently drop a tool from
        the prompt just because it has not caught up with a new one."""
        profile = profiles.Profile(
            name="x", tools=("read_file", "brand_new_tool"), read_only=False,
            max_steps=1, max_revisions=0, scaffold="patch",
        )
        self.assertIn("brand_new_tool", scaffolds.render(profile))

    def test_a_read_only_profile_is_not_told_to_commit(self):
        for profile in (profiles.RESEARCH, profiles.PLAN):
            self.assertNotIn("git_commit", scaffolds.render(profile))

    def test_an_unknown_scaffold_key_still_renders_the_tool_list(self):
        profile = profiles.Profile(
            name="x", tools=("read_file",), read_only=True, max_steps=1, max_revisions=0, scaffold="nope",
        )
        self.assertIn("read_file", scaffolds.render(profile))


class TestTheRulesReachCognition(unittest.TestCase):
    async def _task_rules_for(self, profile) -> str:
        async with Harness() as h:
            bus = h.client("orchestration")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "done"}])
            await cognition.start()
            acts = FakeGuardianExecution(h.client("execution"))
            await acts.start()

            runner = SessionRunner(bus, h.ledger, clock=h.clock.now)
            session = Session(task_id="t-rules", kind=profile.name, mode="execute", profile=profile)
            await runner.run(session, user_text="do the thing")

            await acts.stop()
            await cognition.stop()
            self.assertTrue(cognition.calls)
            return cognition.calls[0].payload.get("task_rules", "")

    @run
    async def test_a_patch_session_sends_its_commit_rule_to_cognition(self):
        rules = await self._task_rules_for(profiles.PATCH)
        self.assertIn("git_commit", rules)

    @run
    async def test_a_chat_session_sends_the_chat_rules(self):
        rules = await self._task_rules_for(profiles.CHAT)
        self.assertIn("read_file", rules)
        self.assertNotIn("git_commit", rules)


if __name__ == "__main__":
    unittest.main()
