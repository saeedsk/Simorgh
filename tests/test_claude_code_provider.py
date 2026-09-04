import json
import subprocess
import unittest

from src.cognition.claude_code_provider import ClaudeCodeProvider
from src.cognition.provider import ProviderUnavailable


class FakeRunner:
    """Stands in for subprocess.run -- never spawns a real process."""

    def __init__(self, completed=None, exception=None):
        self.completed = completed
        self.exception = exception
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.exception is not None:
            raise self.exception
        return self.completed


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestAvailability(unittest.TestCase):
    def test_available_when_binary_is_on_path(self):
        # python3 is guaranteed present in this test environment -- no
        # need for the real `claude` binary to exercise this path
        provider = ClaudeCodeProvider(binary="python3")
        self.assertTrue(provider.available())

    def test_unavailable_when_binary_is_missing(self):
        provider = ClaudeCodeProvider(binary="definitely-not-a-real-cli-xyz")
        self.assertFalse(provider.available())


class TestComplete(unittest.TestCase):
    def _provider(self, runner, binary="python3", env=None):
        return ClaudeCodeProvider(binary=binary, env=env, runner=runner)

    def test_returns_text_and_reported_cost(self):
        payload = json.dumps(
            {"result": "def run(): return 1", "total_cost_usd": 0.021, "session_id": "s1"}
        )
        runner = FakeRunner(completed=_completed(stdout=payload))
        provider = self._provider(runner)

        response = provider.complete("draft a skill")

        self.assertEqual(response.text, "def run(): return 1")
        self.assertEqual(response.provider_name, "claude_code_cli")
        self.assertAlmostEqual(response.metadata["cost_usd"], 0.021)
        self.assertEqual(response.metadata["session_id"], "s1")

    def test_prompt_and_expected_flags_are_passed(self):
        runner = FakeRunner(completed=_completed(stdout=json.dumps({"result": "ok"})))
        provider = self._provider(runner)

        provider.complete("hello")

        args = runner.calls[0]["args"]
        self.assertIn("hello", args)
        self.assertIn("-p", args)
        self.assertIn("--disallowedTools", args)
        self.assertIn("*", args)

    def test_never_passes_dangerously_skip_permissions(self):
        runner = FakeRunner(completed=_completed(stdout=json.dumps({"result": "ok"})))
        provider = self._provider(runner)

        provider.complete("hello")

        args = runner.calls[0]["args"]
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertNotIn("--permission-mode", args)

    def test_credential_env_vars_are_stripped(self):
        runner = FakeRunner(completed=_completed(stdout=json.dumps({"result": "ok"})))
        base_env = {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "sk-should-not-be-passed",
            "ANTHROPIC_AUTH_TOKEN": "tok-should-not-be-passed",
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth-should-not-be-passed",
        }
        provider = self._provider(runner, env=base_env)

        provider.complete("hello")

        passed_env = runner.calls[0]["kwargs"]["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", passed_env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", passed_env)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", passed_env)
        self.assertEqual(passed_env["PATH"], "/usr/bin")

    def test_missing_binary_raises_provider_unavailable(self):
        provider = self._provider(FakeRunner(), binary="definitely-not-a-real-cli-xyz")

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hello")

    def test_nonzero_exit_raises_provider_unavailable(self):
        runner = FakeRunner(completed=_completed(returncode=1, stderr="quota exceeded"))
        provider = self._provider(runner)

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hello")

    def test_is_error_true_with_exit_zero_raises_provider_unavailable(self):
        # Live-observed: `claude -p ... --bare` exits 0 with
        # {"is_error": true, "result": "Not logged in · Please run
        # /login", ...} when no subscription session is active --
        # returncode alone doesn't catch this.
        payload = json.dumps(
            {"is_error": True, "result": "Not logged in · Please run /login"}
        )
        runner = FakeRunner(completed=_completed(returncode=0, stdout=payload))
        provider = self._provider(runner)

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hello")

    def test_invalid_json_raises_provider_unavailable(self):
        runner = FakeRunner(completed=_completed(stdout="not json"))
        provider = self._provider(runner)

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hello")

    def test_timeout_raises_provider_unavailable(self):
        runner = FakeRunner(exception=subprocess.TimeoutExpired(cmd="claude", timeout=1.0))
        provider = self._provider(runner)

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hello")

    def test_spawn_failure_raises_provider_unavailable(self):
        runner = FakeRunner(exception=OSError("no such file"))
        provider = self._provider(runner)

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hello")

    def test_unexpected_runner_exception_raises_provider_unavailable(self):
        # Regression coverage: any failure from the runner call, not just
        # the two documented subprocess exception types, must degrade to
        # ProviderUnavailable -- see the identical fix in gemini_provider.py
        runner = FakeRunner(exception=ValueError("unexpected"))
        provider = self._provider(runner)

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hello")

    def test_missing_cost_field_defaults_to_zero(self):
        runner = FakeRunner(completed=_completed(stdout=json.dumps({"result": "ok"})))
        provider = self._provider(runner)

        response = provider.complete("hello")

        self.assertEqual(response.metadata["cost_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
