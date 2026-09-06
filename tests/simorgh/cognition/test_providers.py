"""Provider adapters (docs/blueprint/subsystems/04-cognition.md section
11). `ClaudeCodeProvider`'s `--bare` case is a live-caught lesson, not a
guess: see the module docstring in `simorgh/cognition/providers/
claude_code.py` for exactly what broke and why."""

from __future__ import annotations

import json
import subprocess
import unittest

from simorgh.cognition.api import ProviderUnavailable, Purpose
from simorgh.cognition.providers.base import TEMPLATES, FloorProvider
from simorgh.cognition.providers.claude_code import ClaudeCodeProvider
from simorgh.cognition.providers.gemini import GeminiProvider


def _fake_completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestClaudeCodeProvider(unittest.IsolatedAsyncioTestCase):
    async def test_never_passes_bare_flag(self):
        captured = {}

        def runner(argv, **kwargs):
            captured["argv"] = argv
            return _fake_completed(json.dumps({"result": "hi", "is_error": False, "total_cost_usd": 0.01}))

        provider = ClaudeCodeProvider(binary="claude", runner=runner)
        await provider.complete([{"role": "user", "content": "hello"}], tools=None, max_tokens=100)
        self.assertNotIn("--bare", captured["argv"])

    async def test_never_inherits_the_real_terminal_stdin(self):
        """Live-caught (the creator's own real `sim.sh` use): the full
        prompt is already on argv (-p) and --disallowedTools "*" means
        this subprocess never legitimately needs input -- but without an
        explicit `stdin=`, it inherits the parent's own stdin, the real
        terminal when the Kernel runs interactively. A call that times
        out gets killed; if `claude` had put that shared terminal into
        raw/cbreak mode, the kill skips its chance to restore it, and the
        terminal stays broken (a literal ^M on every Enter, no further
        input works) for the rest of the session."""
        captured = {}

        def runner(argv, **kwargs):
            captured["kwargs"] = kwargs
            return _fake_completed(json.dumps({"result": "hi", "is_error": False}))

        provider = ClaudeCodeProvider(binary="claude", runner=runner)
        await provider.complete([{"role": "user", "content": "hello"}], tools=None, max_tokens=100)
        self.assertEqual(captured["kwargs"].get("stdin"), subprocess.DEVNULL)

    async def test_strips_credential_env_vars_ranked_above_the_subscription(self):
        captured = {}

        def runner(argv, **kwargs):
            captured["env"] = kwargs["env"]
            return _fake_completed(json.dumps({"result": "hi", "is_error": False}))

        base_env = {"ANTHROPIC_API_KEY": "sk-should-be-stripped", "PATH": "/usr/bin"}
        provider = ClaudeCodeProvider(binary="claude", env=base_env, runner=runner)
        await provider.complete([{"role": "user", "content": "hello"}], tools=None, max_tokens=100)
        self.assertNotIn("ANTHROPIC_API_KEY", captured["env"])
        self.assertEqual(captured["env"]["PATH"], "/usr/bin")

    async def test_returns_a_provider_response_on_success(self):
        def runner(argv, **kwargs):
            return _fake_completed(json.dumps({"result": "the answer", "is_error": False, "total_cost_usd": 0.02}))

        provider = ClaudeCodeProvider(runner=runner)
        response = await provider.complete([{"role": "user", "content": "q"}], tools=None, max_tokens=100)
        self.assertEqual(response.text, "the answer")
        self.assertEqual(response.provider, "claude_code_cli")
        self.assertAlmostEqual(response.cost_usd, 0.02)

    async def test_is_error_true_with_exit_zero_is_still_unavailable(self):
        # The live-caught lesson: exit 0 does not mean success -- `is_error`
        # can be true on a lapsed login, and that must not be handed back
        # as a real reply.
        def runner(argv, **kwargs):
            return _fake_completed(json.dumps({"result": "Not logged in", "is_error": True}))

        provider = ClaudeCodeProvider(runner=runner)
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "q"}], tools=None, max_tokens=100)

    async def test_nonzero_exit_raises_provider_unavailable(self):
        def runner(argv, **kwargs):
            return _fake_completed("", returncode=1, stderr="boom")

        provider = ClaudeCodeProvider(runner=runner)
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "q"}], tools=None, max_tokens=100)

    async def test_non_json_stdout_raises_provider_unavailable(self):
        def runner(argv, **kwargs):
            return _fake_completed("not json")

        provider = ClaudeCodeProvider(runner=runner)
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "q"}], tools=None, max_tokens=100)

    async def test_timeout_raises_provider_unavailable_not_a_crash(self):
        def runner(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))

        provider = ClaudeCodeProvider(runner=runner)
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "q"}], tools=None, max_tokens=100)

    def test_available_reflects_whether_the_binary_is_on_path(self):
        self.assertFalse(ClaudeCodeProvider(binary="definitely-not-a-real-binary-xyz").available())

    async def test_system_role_content_becomes_a_real_system_prompt_flag(self):
        """Live-caught: identity/self-model content flattened into the
        same -p prompt as everything else was too weak to override
        Claude Code's own default identity -- asked directly, it said it
        was Claude Code, not Simorgh. A `role: "system"` message must
        reach the CLI with real system-prompt authority instead."""
        captured = {}

        def runner(argv, **kwargs):
            captured["argv"] = argv
            return _fake_completed(json.dumps({"result": "hi", "is_error": False}))

        provider = ClaudeCodeProvider(binary="claude", runner=runner)
        await provider.complete(
            [{"role": "system", "content": "You are Simorgh."}, {"role": "user", "content": "hello"}],
            tools=None, max_tokens=100,
        )
        argv = captured["argv"]
        self.assertIn("--system-prompt", argv)
        self.assertEqual(argv[argv.index("--system-prompt") + 1], "You are Simorgh.")
        self.assertNotIn("--append-system-prompt", argv)
        # The user turn (-p) must not also carry the system content --
        # no double-delivery, no role bleed.
        self.assertEqual(argv[argv.index("-p") + 1], "hello")

    async def test_multiple_system_messages_are_joined_into_one_flag(self):
        captured = {}

        def runner(argv, **kwargs):
            captured["argv"] = argv
            return _fake_completed(json.dumps({"result": "hi", "is_error": False}))

        provider = ClaudeCodeProvider(binary="claude", runner=runner)
        await provider.complete(
            [{"role": "system", "content": "part one"}, {"role": "system", "content": "part two"},
             {"role": "user", "content": "hello"}],
            tools=None, max_tokens=100,
        )
        argv = captured["argv"]
        self.assertEqual(argv[argv.index("--system-prompt") + 1], "part one\n\npart two")

    async def test_no_system_messages_omits_the_flag_entirely(self):
        captured = {}

        def runner(argv, **kwargs):
            captured["argv"] = argv
            return _fake_completed(json.dumps({"result": "hi", "is_error": False}))

        provider = ClaudeCodeProvider(binary="claude", runner=runner)
        await provider.complete([{"role": "user", "content": "hello"}], tools=None, max_tokens=100)
        self.assertNotIn("--system-prompt", captured["argv"])


class TestGeminiProvider(unittest.IsolatedAsyncioTestCase):
    def test_unavailable_without_an_api_key(self):
        provider = GeminiProvider(api_key=None)
        provider._api_key = None  # ensure no ambient env var leaks into the test
        self.assertFalse(provider.available())

    async def test_complete_raises_provider_unavailable_without_a_key(self):
        provider = GeminiProvider(api_key="")
        provider._api_key = None  # ignore any ambient GEMINI_API_KEY/GOOGLE_API_KEY in this environment
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=100)

    async def test_complete_uses_an_injected_client_and_reports_usage(self):
        class _Usage:
            prompt_token_count = 10
            candidates_token_count = 5

        class _Response:
            text = "gemini says hi"
            usage_metadata = _Usage()

        class _Models:
            def generate_content(self, *, model, contents):
                return _Response()

        class _Client:
            models = _Models()

        provider = GeminiProvider(api_key="fake-key", client=_Client())
        response = await provider.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=100)
        self.assertEqual(response.text, "gemini says hi")
        self.assertEqual(response.input_tokens, 10)
        self.assertEqual(response.output_tokens, 5)

    async def test_sdk_failure_degrades_to_provider_unavailable(self):
        class _Models:
            def generate_content(self, *, model, contents):
                raise RuntimeError("network down")

        class _Client:
            models = _Models()

        provider = GeminiProvider(api_key="fake-key", client=_Client())
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "hi"}], tools=None, max_tokens=100)


class TestFloorProvider(unittest.IsolatedAsyncioTestCase):
    def test_available_is_always_true(self):
        self.assertTrue(FloorProvider().available())

    def test_never_raises_and_answers_every_purpose(self):
        floor = FloorProvider()
        for purpose in Purpose:
            response = floor.respond_for_purpose(purpose)
            self.assertEqual(response.provider, "floor")
            self.assertEqual(response.text, TEMPLATES[purpose])
            self.assertTrue(response.text.startswith("[floor]"))

    async def test_complete_never_raises(self):
        response = await FloorProvider().complete([], tools=None, max_tokens=10)
        self.assertEqual(response.provider, "floor")


if __name__ == "__main__":
    unittest.main()
