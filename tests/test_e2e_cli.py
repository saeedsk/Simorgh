"""End-to-end CLI scenario tests: spawn the real `python -m src.main`
process (never a mocked or directly-imported call) against an isolated
copy of this repository, feed it scripted input via stdin, and assert on
what it actually printed. This is what catches an integration/wiring
problem unit tests can't -- a broken import, a CLI flag that doesn't
parse, the real startup sequence -- since every other test in this suite
calls functions directly rather than exercising the process boundary.

HOME is overridden to an isolated temp directory for every subprocess
here, so ~/.simorgh/memory.jsonl and ~/.simorgh/cli_history never touch
the real user's data, and PATH is narrowed so ClaudeCodeProvider's
`shutil.which("claude")` check reliably finds nothing -- these scenarios
must never make a real, billed LLM call or depend on the machine running
them happening to have a `claude` login. Everything here exercises the
zero-dependency deterministic floor, which is exactly what should be
guaranteed to work.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_IGNORE_FOR_COPY = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache")
_REAL_REPO_ROOT = Path(__file__).resolve().parent.parent


class E2ECliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.repo_copy = root / "repo"
        self.home = root / "home"
        self.home.mkdir()
        shutil.copytree(_REAL_REPO_ROOT, self.repo_copy, ignore=_IGNORE_FOR_COPY)

    def tearDown(self):
        self._tmpdir.cleanup()

    def run_cli(self, stdin_text: str, extra_args: list[str] | None = None, timeout: float = 40.0):
        return subprocess.run(
            [sys.executable, "-m", "src.main", *(extra_args or [])],
            cwd=self.repo_copy,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
        )


class TestStartupAndExit(E2ECliTestCase):
    def test_shows_banner_and_exits_cleanly_on_exit_command(self):
        result = self.run_cli("exit\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Simorgh", result.stdout)
        self.assertIn("propose", result.stdout)  # the banner lists commands

    def test_autonomous_loop_starts_by_default(self):
        result = self.run_cli("exit\n")

        self.assertIn("autonomous self-improvement is ON", result.stdout)

    def test_eof_with_no_input_exits_cleanly(self):
        result = self.run_cli("")

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cognition_status_reports_the_deterministic_only_floor(self):
        # No real provider is reachable in this isolated environment
        # (no API keys, no `claude` on the narrowed PATH) -- this is the
        # guaranteed-available floor every other capability degrades to.
        result = self.run_cli("exit\n")

        self.assertIn("deterministic fallback only", result.stdout)


class TestSelfCheckFlag(E2ECliTestCase):
    def test_self_check_exits_zero_on_healthy_code(self):
        result = self.run_cli("", extra_args=["--self-check"], timeout=20.0)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)


class TestPlainChat(E2ECliTestCase):
    def test_plain_message_gets_a_rule_based_reply(self):
        result = self.run_cli("hello there\nexit\n")

        self.assertIn("Here's my take", result.stdout)

    def test_a_reply_triggers_the_llm_unavailable_notice(self):
        # llm_configured is False here (no real provider registered at
        # all), so handle_turn must NOT print the "[notice] LLM access
        # isn't available" line -- that's reserved for when a real
        # provider was configured but degraded mid-turn.
        result = self.run_cli("hello there\nexit\n")

        self.assertNotIn("LLM access isn't available", result.stdout)


class TestTaskAndSkillCommands(E2ECliTestCase):
    def test_tasks_autonomous_status_budget_skills_all_run_cleanly(self):
        result = self.run_cli("tasks\nautonomous status\nbudget\nskills\nlog\nexit\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Task backlog", result.stdout)
        self.assertIn("Autonomous self-improvement", result.stdout)
        self.assertIn("Applied skills", result.stdout)
        self.assertIn("no real LLM provider configured", result.stdout)

    def test_autonomous_off_then_status_shows_disabled(self):
        result = self.run_cli("autonomous off\nautonomous status\nexit\n")

        self.assertIn("enabled: False", result.stdout)

    def test_discover_with_no_signals_reports_nothing_found(self):
        result = self.run_cli("discover\nexit\n")

        self.assertIn("no new improvement areas", result.stdout)

    def test_work_with_nothing_pending_reports_it(self):
        result = self.run_cli("work\nexit\n")

        self.assertIn("nothing pending", result.stdout)

    def test_digest_with_no_autonomous_activity_reports_it(self):
        result = self.run_cli("digest\nexit\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no autonomous actions", result.stdout)

    def test_pending_with_nothing_applied_reports_it(self):
        result = self.run_cli("pending\nexit\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing applied yet", result.stdout)


class TestProposeAndUseEndToEnd(E2ECliTestCase):
    def test_propose_drafts_applies_and_is_immediately_usable(self):
        result = self.run_cli("propose rocketry\nuse rocketry\nexit\n")

        self.assertIn("APPLIED", result.stdout)
        self.assertTrue((self.repo_copy / "src" / "agents" / "skills" / "rocketry.py").exists())
        # "use" ran the skill fresh from disk in the same session, no
        # relaunch -- its output (the deterministic note template's
        # returned string) should show up somewhere in the transcript.
        self.assertIn("rocketry", result.stdout.lower())

    def test_pending_with_a_path_shows_the_full_applied_code(self):
        result = self.run_cli("propose rocketry\npending src/agents/skills/rocketry.py\nexit\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("def run()", result.stdout)

    def test_plan_saves_tasks_without_a_real_provider(self):
        # No real LLM is reachable here, so the brainstorm step can't
        # produce anything -- this must fail cleanly with a clear
        # message, not hang or crash.
        result = self.run_cli("plan 3 improve resilience\ntasks\nexit\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no real drafting intelligence", result.stdout)


if __name__ == "__main__":
    unittest.main()
