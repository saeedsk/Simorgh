import tempfile
import unittest
from pathlib import Path

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


class ScriptedProvider:
    """Returns each of `responses` (a list of (text, provider_name) pairs)
    in order across successive complete() calls, repeating the last one if
    called more times than scripted.
    """

    def __init__(self, responses, name="scripted"):
        self.name = name
        self._responses = responses
        self.prompts = []

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self._responses) - 1)
        text, provider_name = self._responses[index]
        return LLMResponse(text=text, provider_name=provider_name or self.name)


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


class TestSkillResearchAgentToolLoop(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src").mkdir()
        (self.repo_root / "src" / "example.py").write_text("EXAMPLE_CONSTANT = 42\n")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_read_tool_feeds_file_content_back_and_continues(self):
        final_code = "def run():\n    return 1\n"
        provider = ScriptedProvider(
            [
                ("READ: src/example.py", None),
                (final_code, None),
            ]
        )
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        proposal = agent.draft_skill("uses example")

        self.assertEqual(len(provider.prompts), 2)
        self.assertIn("EXAMPLE_CONSTANT", provider.prompts[1])
        self.assertEqual(proposal.code.strip(), final_code.strip())

    def test_read_tool_refuses_path_traversal(self):
        provider = ScriptedProvider(
            [("READ: ../../etc/passwd", None), ("def run():\n    return 1\n", None)]
        )
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_skill("escape attempt")

        self.assertIn("refused", provider.prompts[1])

    def test_read_tool_refuses_absolute_path(self):
        provider = ScriptedProvider(
            [("READ: /etc/passwd", None), ("def run():\n    return 1\n", None)]
        )
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_skill("absolute path attempt")

        self.assertIn("refused", provider.prompts[1])

    def test_read_tool_refuses_paths_outside_allowed_roots(self):
        provider = ScriptedProvider(
            [("READ: requirements.txt", None), ("def run():\n    return 1\n", None)]
        )
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_skill("outside allowed roots")

        self.assertIn("refused", provider.prompts[1])

    def test_read_tool_refuses_credential_looking_paths(self):
        provider = ScriptedProvider(
            [("READ: src/.env", None), ("def run():\n    return 1\n", None)]
        )
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_skill("credential path attempt")

        self.assertIn("refused", provider.prompts[1])
        self.assertIn("credentials", provider.prompts[1])

    def test_draft_tool_reports_pass_and_continues(self):
        good_code = "def run():\n    return 1\n"
        provider = ScriptedProvider(
            [
                (f"DRAFT: {good_code}", None),
                (good_code, None),
            ]
        )
        agent = SkillResearchAgent(
            CognitionRouter([provider]), audit_gate=AuditGate(), repo_root=self.repo_root
        )

        agent.draft_skill("passes cleanly")

        self.assertIn("PASSED", provider.prompts[1])

    def test_draft_tool_reports_rejection_reasons_and_continues(self):
        bad_code = "eval('1')"
        good_code = "def run():\n    return 1\n"
        provider = ScriptedProvider(
            [
                (f"DRAFT: {bad_code}", None),
                (good_code, None),
            ]
        )
        agent = SkillResearchAgent(
            CognitionRouter([provider]), audit_gate=AuditGate(), repo_root=self.repo_root
        )

        proposal = agent.draft_skill("self-corrects")

        self.assertIn("REJECTED", provider.prompts[1])
        self.assertIn("eval", provider.prompts[1])
        self.assertEqual(proposal.code.strip(), good_code.strip())

    def test_draft_tool_without_audit_gate_reports_cannot_test(self):
        provider = ScriptedProvider(
            [("DRAFT: def run():\n    return 1\n", None), ("def run():\n    return 1\n", None)]
        )
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_skill("no audit gate given")

        self.assertIn("cannot test", provider.prompts[1])

    def test_loop_is_bounded_by_max_tool_steps(self):
        provider = ScriptedProvider([("READ: src/example.py", None)] * 10)
        agent = SkillResearchAgent(
            CognitionRouter([provider]), repo_root=self.repo_root, max_tool_steps=3
        )

        agent.draft_skill("never stops reading")

        self.assertEqual(len(provider.prompts), 3)

    def test_provider_falling_back_mid_loop_stops_and_uses_safe_template(self):
        provider = ScriptedProvider(
            [
                ("READ: src/example.py", None),
                ("[offline reasoning] budget exhausted", "deterministic_fallback"),
            ]
        )
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        proposal = agent.draft_skill("budget runs out mid draft")

        self.assertEqual(len(provider.prompts), 2)
        namespace: dict = {}
        exec(proposal.code, namespace)  # noqa: S102 -- test-only, trusted local code
        self.assertIn("budget exhausted", namespace["run"]())

    def test_final_answer_with_no_tool_use_works_as_before(self):
        code = "def run():\n    return 7\n"
        provider = FakeProvider(text=code)
        agent = SkillResearchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        proposal = agent.draft_skill("no tools needed")

        self.assertEqual(proposal.code.strip(), code.strip())


if __name__ == "__main__":
    unittest.main()
