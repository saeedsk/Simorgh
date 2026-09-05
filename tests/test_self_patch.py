import subprocess
import tempfile
import unittest
from pathlib import Path

from src.cognition.provider import CognitionRouter, LLMResponse
from src.orchestrator.audit import AuditGate
from src.orchestrator.self_patch import (
    SelfPatchAgent,
    SuiteRunResult,
    check_main_py_invariants,
    relaunch,
    run_isolated_test_suite,
)


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


class TestSelfPatchAgent(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src" / "orchestrator").mkdir(parents=True)
        (self.repo_root / "src" / "orchestrator" / "target.py").write_text(
            "def old():\n    return 1\n"
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_no_real_provider_returns_none(self):
        agent = SelfPatchAgent(CognitionRouter(), repo_root=self.repo_root)

        proposal, reason = agent.draft_patch("src/orchestrator/target.py", "improve it")

        self.assertIsNone(proposal)
        self.assertEqual(reason, "deterministic_fallback")

    def test_real_provider_seeds_prompt_with_current_content(self):
        provider = FakeProvider(text="def new():\n    return 2\n")
        agent = SelfPatchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        proposal, reason = agent.draft_patch("src/orchestrator/target.py", "improve it")

        self.assertIn("def old():", provider.prompts[0])
        self.assertIsNone(reason)
        self.assertEqual(proposal.subject, "src/orchestrator/target.py")
        self.assertEqual(proposal.code.strip(), "def new():\n    return 2")
        self.assertIn("fake", proposal.rationale)

    def test_seeds_the_prompt_with_the_complete_file_not_a_chat_bounded_prefix(self):
        # Live-caught bug: a chat-bounded READ (safe_read_file, capped at
        # 20,000 chars) used to seed this prompt -- for a large file the
        # model was silently shown only a prefix while still being asked
        # to write "the COMPLETE new content," which it visibly couldn't
        # do honestly (it tried to invent an offset-based read protocol
        # that doesn't exist here, and drafting failed outright).
        big_content = "x = 1\n" * 5000  # comfortably over the old 20,000-char cap
        (self.repo_root / "src" / "orchestrator" / "big.py").write_text(big_content)
        provider = FakeProvider(text="y = 2\n")
        agent = SelfPatchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_patch("src/orchestrator/big.py", "improve it")

        self.assertIn(big_content, provider.prompts[0])

    def test_a_file_too_large_to_safely_seed_returns_none_without_calling_the_llm(self):
        from src.cognition.tool_protocol import _MAX_PATCH_SEED_CHARS

        huge_content = "x" * (_MAX_PATCH_SEED_CHARS + 1)
        (self.repo_root / "src" / "orchestrator" / "huge.py").write_text(huge_content)
        provider = FakeProvider(text="y = 2\n")
        agent = SelfPatchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        proposal, reason = agent.draft_patch("src/orchestrator/huge.py", "improve it")

        self.assertIsNone(proposal)
        self.assertTrue(reason.startswith("refused: "))
        self.assertEqual(provider.prompts, [])  # never even called -- refused up front

    def test_a_nonexistent_subject_returns_none_without_calling_the_llm(self):
        provider = FakeProvider(text="y = 2\n")
        agent = SelfPatchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        proposal, reason = agent.draft_patch("src/orchestrator/does_not_exist.py", "improve it")

        self.assertIsNone(proposal)
        self.assertTrue(reason.startswith("refused: "))
        self.assertEqual(provider.prompts, [])

    def test_invalid_python_returns_none_with_a_retryable_reason(self):
        provider = FakeProvider(text="not valid python {{{")
        agent = SelfPatchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        proposal, reason = agent.draft_patch("src/orchestrator/target.py", "improve it")

        self.assertIsNone(proposal)
        # Distinguishable from both "deterministic_fallback" and a
        # "refused: ..." target problem -- a real provider DID answer
        # here, it just didn't produce valid Python, which is a
        # genuinely different, retryable failure class (see
        # propose_self_patch in main.py).
        self.assertNotEqual(reason, "deterministic_fallback")
        self.assertFalse(reason.startswith("refused: "))
        self.assertIn("fake", reason)

    def test_read_tool_pulls_in_other_files_for_context(self):
        (self.repo_root / "src" / "orchestrator" / "other.py").write_text("OTHER = 1\n")
        provider = ScriptedProvider(
            [
                ("READ: src/orchestrator/other.py", None),
                ("def new():\n    return 2\n", None),
            ]
        )
        agent = SelfPatchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_patch("src/orchestrator/target.py", "improve it")

        self.assertIn("OTHER", provider.prompts[1])

    def test_draft_tool_checks_against_real_audit_gate(self):
        bad_code = "eval('1')"
        good_code = "def new():\n    return 2\n"
        provider = ScriptedProvider([(f"DRAFT: {bad_code}", None), (good_code, None)])
        agent = SelfPatchAgent(
            CognitionRouter([provider]), audit_gate=AuditGate(), repo_root=self.repo_root
        )

        proposal, reason = agent.draft_patch("src/orchestrator/target.py", "improve it")

        self.assertIn("REJECTED", provider.prompts[1])
        self.assertIsNone(reason)
        self.assertEqual(proposal.code.strip(), good_code.strip())

    def test_prior_reasons_feed_into_retry_prompt(self):
        provider = FakeProvider(text="def new():\n    return 2\n")
        agent = SelfPatchAgent(CognitionRouter([provider]), repo_root=self.repo_root)

        agent.draft_patch(
            "src/orchestrator/target.py", "improve it", prior_reasons=["denied: used eval"]
        )

        self.assertIn("denied: used eval", provider.prompts[0])

    def test_loop_is_bounded_by_max_tool_steps(self):
        provider = ScriptedProvider([("READ: src/orchestrator/target.py", None)] * 10)
        agent = SelfPatchAgent(
            CognitionRouter([provider]), repo_root=self.repo_root, max_tool_steps=3
        )

        agent.draft_patch("src/orchestrator/target.py", "never stops reading")

        self.assertEqual(len(provider.prompts), 3)

    def test_activity_log_records_tool_calls(self):
        class RecordingLog:
            def __init__(self):
                self.calls = []

            def record_tool_call(self, agent, tool, request, result_summary, succeeded):
                self.calls.append((agent, tool, request, succeeded))

        provider = ScriptedProvider(
            [("READ: src/orchestrator/target.py", None), ("def new():\n    return 2\n", None)]
        )
        log = RecordingLog()
        agent = SelfPatchAgent(
            CognitionRouter([provider]), repo_root=self.repo_root, activity_log=log
        )

        agent.draft_patch("src/orchestrator/target.py", "improve it")

        self.assertEqual(len(log.calls), 1)
        self.assertEqual(log.calls[0][0], "self_patch")
        self.assertEqual(log.calls[0][1], "READ")


class TestCheckMainPyInvariants(unittest.TestCase):
    def test_content_missing_audit_wiring_is_refused(self):
        reason = check_main_py_invariants("print('hello')")

        self.assertIsNotNone(reason)
        self.assertIn("AuditGate(", reason)

    def test_content_with_wiring_intact_passes(self):
        content = "AuditGate()\naudit_gate.review(x)\napply_proposal(y)\n"

        reason = check_main_py_invariants(content)

        self.assertIsNone(reason)


class TestRunIsolatedTestSuite(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src").mkdir()
        (self.repo_root / "src" / "target.py").write_text("VALUE = 1\n")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _fake_runner(self, sequence):
        calls = {"n": 0}

        def runner(repo_copy, timeout):
            result = sequence[min(calls["n"], len(sequence) - 1)]
            calls["n"] += 1
            return result

        return runner

    def _completed(self, returncode, ran):
        return subprocess.CompletedProcess(
            args=["fake"], returncode=returncode, stdout="", stderr=f"Ran {ran} tests in 0.1s\n"
        )

    def test_passing_patch_with_same_test_count_passes(self):
        runner = self._fake_runner([self._completed(0, 10), self._completed(0, 10)])

        result = run_isolated_test_suite(
            self.repo_root, "src/target.py", "VALUE = 2\n", runner=runner
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.test_count, 10)
        self.assertEqual(result.baseline_test_count, 10)

    def test_patch_that_reduces_test_count_fails(self):
        runner = self._fake_runner([self._completed(0, 10), self._completed(0, 8)])

        result = run_isolated_test_suite(
            self.repo_root, "src/target.py", "VALUE = 2\n", runner=runner
        )

        self.assertFalse(result.passed)

    def test_patch_with_nonzero_exit_fails(self):
        runner = self._fake_runner([self._completed(0, 10), self._completed(1, 10)])

        result = run_isolated_test_suite(
            self.repo_root, "src/target.py", "VALUE = 2\n", runner=runner
        )

        self.assertFalse(result.passed)

    def test_does_not_mutate_the_real_repository(self):
        runner = self._fake_runner([self._completed(0, 1), self._completed(0, 1)])

        run_isolated_test_suite(self.repo_root, "src/target.py", "VALUE = 999\n", runner=runner)

        self.assertEqual((self.repo_root / "src" / "target.py").read_text(), "VALUE = 1\n")

    def test_real_subprocess_runner_against_a_toy_repo(self):
        (self.repo_root / "tests").mkdir()
        (self.repo_root / "tests" / "__init__.py").write_text("")
        (self.repo_root / "tests" / "test_toy.py").write_text(
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n"
        )

        result = run_isolated_test_suite(self.repo_root, "src/target.py", "VALUE = 2\n")

        self.assertTrue(result.passed)
        self.assertEqual(result.test_count, 1)


class TestRelaunch(unittest.TestCase):
    @staticmethod
    def _passing_check_runner(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="[self-check] OK", stderr="")

    @staticmethod
    def _failing_check_runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout="", stderr="[self-check] FAILED: ImportError(...)"
        )

    def test_execs_with_current_interpreter_and_argv_when_self_check_passes(self):
        calls = []

        relaunch(
            exec_func=lambda exe, argv: calls.append((exe, argv)),
            check_runner=self._passing_check_runner,
        )

        self.assertEqual(len(calls), 1)
        exe, argv = calls[0]
        self.assertTrue(exe)
        self.assertEqual(argv[0], exe)

    def test_self_check_runs_before_exec_and_includes_the_flag(self):
        seen_argv = []

        def check_runner(argv, **kwargs):
            seen_argv.append(argv)
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

        relaunch(exec_func=lambda exe, argv: None, check_runner=check_runner)

        self.assertEqual(len(seen_argv), 1)
        self.assertIn("--self-check", seen_argv[0])

    def test_does_not_exec_when_self_check_fails(self):
        calls = []

        result = relaunch(
            exec_func=lambda exe, argv: calls.append((exe, argv)),
            check_runner=self._failing_check_runner,
        )

        self.assertEqual(calls, [])
        self.assertFalse(result.succeeded)
        self.assertIn("self-check failed", result.detail)

    def test_check_runner_timeout_is_reported_not_raised(self):
        def timing_out(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="python", timeout=1.0)

        result = relaunch(exec_func=lambda exe, argv: None, check_runner=timing_out, timeout=1.0)

        self.assertFalse(result.succeeded)
        self.assertIn("timed out", result.detail)

    def test_check_runner_os_error_is_reported_not_raised(self):
        def raising(*args, **kwargs):
            raise OSError("no such file")

        result = relaunch(exec_func=lambda exe, argv: None, check_runner=raising)

        self.assertFalse(result.succeeded)
        self.assertIn("self-check failed to run", result.detail)


if __name__ == "__main__":
    unittest.main()
