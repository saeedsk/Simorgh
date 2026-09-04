import unittest

from src.agents.skills.research import SkillResearchAgent
from src.cognition.provider import CognitionRouter, LLMResponse
from src.orchestrator.audit import AuditGate


class FakeProvider:
    def __init__(self, name="fake", text=""):
        self.name = name
        self._text = text
        self.prompts = []

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return LLMResponse(text=self._text, provider_name=self.name)


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
        self.assertFalse(verdict.requires_human_approval)

    def test_drafted_skill_code_actually_runs_and_returns_the_topic_note(self):
        agent = SkillResearchAgent()
        proposal = agent.draft_skill("rocketry")

        namespace: dict = {}
        exec(proposal.code, namespace)  # noqa: S102 -- test-only, trusted local code

        self.assertIn("rocketry", namespace["run"]())


class TestSkillResearchAgentWithRealProvider(unittest.TestCase):
    def test_real_provider_code_is_used_as_is(self):
        code = "def run():\n    return 2 + 2\n"
        provider = FakeProvider(text=code)
        agent = SkillResearchAgent(CognitionRouter([provider]))

        proposal = agent.draft_skill("addition")

        self.assertEqual(proposal.code.strip(), code.strip())
        self.assertIn("fake", proposal.rationale)

    def test_markdown_fence_is_stripped(self):
        code = "def run():\n    return 42\n"
        provider = FakeProvider(text=f"```python\n{code}```")
        agent = SkillResearchAgent(CognitionRouter([provider]))

        proposal = agent.draft_skill("answer")

        self.assertEqual(proposal.code.strip(), code.strip())
        self.assertNotIn("```", proposal.code)

    def test_invalid_python_falls_back_to_the_safe_note_template(self):
        provider = FakeProvider(text="this is not python code at all {{{")
        agent = SkillResearchAgent(CognitionRouter([provider]))

        proposal = agent.draft_skill("broken")

        namespace: dict = {}
        exec(proposal.code, namespace)  # noqa: S102 -- test-only, trusted local code
        self.assertIn("this is not python code", namespace["run"]())

    def test_prior_reasons_are_included_in_the_retry_prompt(self):
        provider = FakeProvider(text="def run():\n    return 1\n")
        agent = SkillResearchAgent(CognitionRouter([provider]))

        agent.draft_skill("addition", prior_reasons=["denied: used eval"])

        self.assertIn("denied: used eval", provider.prompts[0])

    def test_no_prior_reasons_means_no_retry_language_in_prompt(self):
        provider = FakeProvider(text="def run():\n    return 1\n")
        agent = SkillResearchAgent(CognitionRouter([provider]))

        agent.draft_skill("addition")

        self.assertNotIn("previous attempt", provider.prompts[0].lower())


if __name__ == "__main__":
    unittest.main()
