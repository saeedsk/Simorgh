import unittest

from src.agents.skills.research import SkillResearchAgent
from src.orchestrator.audit import AuditGate


class TestSkillResearchAgent(unittest.TestCase):
    def test_draft_skill_produces_a_valid_proposal(self):
        agent = SkillResearchAgent()

        proposal = agent.draft_skill("rocketry")

        self.assertEqual(proposal.subject, "src/agents/skills/rocketry.py")
        self.assertIn("rocketry", proposal.code)
        self.assertIn("deterministic_fallback", proposal.rationale)

    def test_subject_can_be_overridden(self):
        agent = SkillResearchAgent()

        proposal = agent.draft_skill("rocketry", subject="src/agents/skills/custom.py")

        self.assertEqual(proposal.subject, "src/agents/skills/custom.py")

    def test_topic_with_punctuation_produces_a_safe_subject_slug(self):
        agent = SkillResearchAgent()

        proposal = agent.draft_skill("Sim's favorite: rockets!")

        self.assertEqual(proposal.subject, "src/agents/skills/sim_s_favorite_rockets.py")

    def test_drafted_skill_passes_the_audit_gate_sandbox_cleanly(self):
        agent = SkillResearchAgent()
        gate = AuditGate()

        proposal = agent.draft_skill("rocketry")
        verdict = gate.review(proposal)

        self.assertTrue(verdict.approved_by_automation)
        self.assertTrue(verdict.requires_human_approval)

    def test_drafted_skill_code_actually_runs_and_returns_the_topic_note(self):
        agent = SkillResearchAgent()
        proposal = agent.draft_skill("rocketry")

        namespace: dict = {}
        exec(proposal.code, namespace)  # noqa: S102 -- test-only, trusted local code

        self.assertIn("rocketry", namespace["run"]())


if __name__ == "__main__":
    unittest.main()
