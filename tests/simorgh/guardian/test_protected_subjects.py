"""Stage 8 item 5: the growth loop cannot loosen its own gate.

Sim may propose a change to how it works -- that is the whole point of
the loop. It may not quietly change what decides whether that change
was good.

The interesting line here is the one that is NOT protected. `apply_skill`
writes to `simorgh_skills/` and is human-only, so every skill already
reaches a person; protecting the directory would turn that ask into a
flat denial and take away a capability Sim has today. Protection and
human-only are different tools: one says "never", the other says "not
without somebody".
"""

import unittest


class TheGrowthLoopCannotLoosenItsOwnGate(unittest.IsolatedAsyncioTestCase):
    """Stage 8 item 5: Sim may propose a change to how it works. It may
    not quietly change what decides whether that change was good."""

    @staticmethod
    def _ctx():
        from simorgh.guardian.api import DecisionContext
        from simorgh.guardian.config import Config
        from simorgh.guardian.posture import Posture

        return DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded"),
                               config=Config())

    @staticmethod
    def _write(path: str):
        from simorgh.guardian.api import Proposal

        return Proposal(action_id="a1", tool="apply_source_patch", args={"path": path, "content": "x"},
                        scope={"paths": [path]}, reversibility="irreversible", rationale="",
                        proposed_by="orchestration")

    async def _kind(self, path: str) -> str:
        from simorgh.guardian.rules import ProtectedRule

        return (await ProtectedRule().evaluate(self._write(path), self._ctx())).kind

    async def test_the_rules_an_agent_body_is_rendered_from_are_protected(self):
        self.assertEqual(await self._kind("rules/patch.md"), "deny")

    async def test_the_suite_that_judges_a_policy_is_protected(self):
        """A loop that can edit its own evals can adopt anything."""
        self.assertEqual(await self._kind("simorgh/evals/suites.py"), "deny")

    async def test_the_agent_definitions_stay_protected(self):
        self.assertEqual(await self._kind("agents/patch.md"), "deny")

    async def test_a_skill_is_asked_about_rather_than_refused(self):
        """`apply_skill` is human-only, so every skill already reaches a
        person. Protecting the directory would turn that ask into a flat
        denial and take away something Sim can do today -- protection and
        human-only are different tools."""
        self.assertEqual(await self._kind("simorgh_skills/word_count.py"), "abstain")

    async def test_ordinary_code_is_still_Sims_to_change(self):
        self.assertEqual(await self._kind("simorgh/memory/store.py"), "abstain")
