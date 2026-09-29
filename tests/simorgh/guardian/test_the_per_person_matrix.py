"""Stage 6 item 5, the per-person matrix: one tool, one person, above or
below their role. "Iris may play music without asking", "Ira asks before
the TV", "Aran may not use run_shell" -- set by a person with `people
set_tool`, read here from the People store."""

from __future__ import annotations

import unittest

from simorgh.guardian.api import DecisionContext
from simorgh.guardian.config import Config
from simorgh.guardian.posture import Posture
from simorgh.guardian.tiers import PersonRule

from .test_tiers import _proposal


def _ctx(answers: dict) -> DecisionContext:
    async def tool_answer(person: str, tool: str) -> str:
        return answers.get((person, tool), "")
    return DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded"),
                           config=Config(mode="guarded"), tool_answer=tool_answer)


class ThePerPersonMatrix(unittest.IsolatedAsyncioTestCase):
    async def test_allow_lifts_a_child_above_their_ceiling_up_to_tier_2(self):
        commit = _proposal("git_commit", requester="Ira", channel="voice")          # tier 2, above a child's 1
        self.assertEqual((await PersonRule().evaluate(commit, _ctx({}))).kind, "escalate")
        allowed = _ctx({("Ira", "git_commit"): "allow"})
        self.assertEqual((await PersonRule().evaluate(commit, allowed)).kind, "abstain")

    async def test_allow_never_reaches_tier_3(self):
        from simorgh.contracts.tiers import REACHES_OUTSIDE
        tool = sorted(REACHES_OUTSIDE)[0]
        outside = _proposal(tool, requester="Ira", channel="voice")
        decision = await PersonRule().evaluate(outside, _ctx({("Ira", tool): "allow"}))
        self.assertEqual(decision.kind, "escalate", "tier 3 stays a person's yes whoever asks")

    async def test_allow_on_home_call_does_not_let_a_child_unlock(self):
        """Unlock is tier 2 by reach; PhysicalRule is what makes it a
        person's yes in every posture, and an allow here must not undo it."""
        from simorgh.guardian.api import ToolInfo
        from simorgh.guardian.pipeline import Pipeline
        from simorgh.guardian.rules import DEFAULT_PIPELINE

        async def tool_answer(person, tool):
            return "allow"
        unlock = _proposal("home_call", requester="Ira", channel="voice", reversibility="reversible",
                           args={"service": "lock.unlock", "target": "lock.front_door"})
        ctx = DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded", baseline="guarded"),
                              config=Config(irreversible_requires_human=False), tool_answer=tool_answer,
                              tool=ToolInfo(name="home_call", read_only=False, reversibility="reversible"))
        verdict = await Pipeline(DEFAULT_PIPELINE).decide(unlock, ctx)
        self.assertNotEqual(verdict.kind, "allow")

    async def test_ask_sends_it_to_an_adult_even_within_the_ceiling(self):
        light = _proposal("home_call", requester="Ira", channel="voice", reversibility="reversible",
                          args={"service": "light.turn_on", "target": "light.kitchen"})
        self.assertEqual((await PersonRule().evaluate(light, _ctx({}))).kind, "abstain")
        decision = await PersonRule().evaluate(light, _ctx({("Ira", "home_call"): "ask"}))
        self.assertEqual(decision.kind, "escalate")
        self.assertIn("a person said so", decision.reasons[0])

    async def test_deny_refuses_even_an_adult(self):
        commit = _proposal("git_commit", requester="Saeed", channel="voice")
        decision = await PersonRule().evaluate(commit, _ctx({("Saeed", "git_commit"): "deny"}))
        self.assertEqual(decision.kind, "deny")
        self.assertIn("may not use git_commit", decision.reasons[0])

    async def test_a_voice_nobody_placed_gets_no_matrix(self):
        asked: list = []

        async def tool_answer(person, tool):
            asked.append(person)
            return "allow"
        ctx = DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded"),
                              config=Config(mode="guarded"), tool_answer=tool_answer)
        decision = await PersonRule().evaluate(_proposal("home_call", channel="voice", reversibility="reversible"), ctx)
        self.assertEqual(decision.kind, "deny")
        self.assertEqual(asked, [])

    async def test_no_entry_is_the_role_as_before(self):
        commit = _proposal("git_commit", requester="Saeed", channel="voice")
        self.assertEqual((await PersonRule().evaluate(commit, _ctx({}))).kind, "abstain")


if __name__ == "__main__":
    unittest.main()
