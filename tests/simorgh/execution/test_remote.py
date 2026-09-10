"""`run_remote` (execution/remote.py).

No test here opens an ssh connection: each injects a runner. What is
pinned is the argv that WOULD go out, and the refusals that stop it
being built at all.

The property most worth protecting is that THE MODEL CANNOT CHOOSE THE
DESTINATION. A `host` argument would turn "run my build on my server"
into a general way to send anything on this machine to any machine on
the internet -- so several tests here exist purely to fail if someone
adds one.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.remote import (
    HOST_ENV,
    KEY_ENV,
    USER_ENV,
    RemoteUnavailable,
    RunRemoteTool,
    settings,
    ssh_argv,
)
from simorgh.execution.tools import builtin_tools


class _Completed:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class _Runner:
    def __init__(self, completed=None, raises=None):
        self.completed = completed or _Completed()
        self.raises, self.calls = raises, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if self.raises:
            raise self.raises
        return self.completed


def _ctx():
    return ToolContext(
        action_id="a1", task_id=None, scope={}, constraints={},
        data_dir=Path("."), clock=None, logger=None, ledger=None,
    )


HOST = {HOST_ENV: "build.example.test", USER_ENV: "ci"}


class RegistrationTestCase(unittest.TestCase):
    def test_it_is_off_by_default(self):
        # One step stricter than run_shell's default-on: the blast radius
        # is a machine this code cannot inspect or roll back.
        self.assertNotIn("run_remote", {t.name for t in builtin_tools(Config())})

    def test_it_appears_when_configured(self):
        self.assertIn("run_remote", {t.name for t in builtin_tools(Config(remote=True))})

    def test_it_is_irreversible_and_stays_that_way(self):
        tool = RunRemoteTool(Config())
        self.assertEqual(tool.reversibility, "irreversible")
        self.assertFalse(tool.read_only)


class TheModelCannotChooseTheHostTestCase(unittest.IsolatedAsyncioTestCase):
    """These tests exist to fail if someone adds a `host` argument."""

    def test_the_schema_accepts_nothing_but_a_command(self):
        self.assertEqual(set(RunRemoteTool(Config()).args_schema["properties"]), {"command"})

    async def test_a_host_argument_is_ignored_not_honoured(self):
        runner = _Runner()
        tool = RunRemoteTool(Config(), env=HOST, runner=runner)
        await tool.run({"command": "uptime", "host": "attacker.example.test"}, ctx=_ctx())
        argv = runner.calls[0]
        self.assertIn("ci@build.example.test", argv)
        self.assertNotIn("attacker.example.test", " ".join(argv))


class SettingsTestCase(unittest.TestCase):
    def test_with_nothing_set_it_names_the_variable(self):
        with self.assertRaises(RemoteUnavailable) as caught:
            settings({})
        self.assertIn(HOST_ENV, str(caught.exception))

    def test_there_is_no_default_host(self):
        # Guessing one would run a command on a machine nobody chose.
        with self.assertRaises(RemoteUnavailable):
            settings({USER_ENV: "ci"})

    def test_a_host_that_could_be_read_as_an_ssh_option_is_refused(self):
        for bad in ("-oProxyCommand=curl evil", "host with space", "host;rm -rf /"):
            with self.subTest(host=bad):
                with self.assertRaises(RemoteUnavailable):
                    settings({HOST_ENV: bad})

    def test_a_username_that_could_be_read_as_an_option_is_refused(self):
        with self.assertRaises(RemoteUnavailable):
            settings({HOST_ENV: "h.example.test", USER_ENV: "-oProxyCommand=x"})

    def test_a_plain_host_and_user_are_accepted(self):
        found = settings(HOST)
        self.assertEqual(found["host"], "build.example.test")
        self.assertEqual(found["user"], "ci")


class ArgvTestCase(unittest.TestCase):
    def test_ssh_never_prompts_for_a_password(self):
        # BatchMode means a password-authenticated host fails fast rather
        # than hanging on a prompt nobody can answer -- and no password
        # ever passes through this process.
        argv = ssh_argv("uptime", Config(), settings(HOST))
        self.assertIn("BatchMode=yes", argv)

    def test_host_keys_are_checked_by_default(self):
        self.assertIn("StrictHostKeyChecking=yes", ssh_argv("uptime", Config(), settings(HOST)))

    def test_turning_host_key_checking_off_is_possible_and_explicit(self):
        argv = ssh_argv("uptime", Config(remote_strict_host_key=False), settings(HOST))
        self.assertIn("StrictHostKeyChecking=no", argv)

    def test_the_command_is_one_argument_so_nothing_runs_locally(self):
        # No local shell: `; rm -rf /` is text sent to the remote host,
        # not something this machine interprets on the way.
        argv = ssh_argv("echo hi; whoami", Config(), settings(HOST))
        self.assertEqual(argv[-1], "echo hi; whoami")

    def test_a_working_directory_is_quoted(self):
        argv = ssh_argv("make", Config(remote_working_dir="/srv/my project"), settings(HOST))
        self.assertEqual(argv[-1], "cd '/srv/my project' && make")

    def test_a_key_pins_identities_only(self):
        # Without IdentitiesOnly, ssh may offer every key in the agent.
        argv = ssh_argv("uptime", Config(), settings(dict(HOST, **{KEY_ENV: "/k"})))
        self.assertIn("IdentitiesOnly=yes", argv)
        self.assertIn("/k", argv)


class RunningTestCase(unittest.IsolatedAsyncioTestCase):
    def _tool(self, runner, env=None, **overrides):
        return RunRemoteTool(Config(**overrides), env=HOST if env is None else env, runner=runner)

    async def test_with_no_host_configured_it_refuses_and_says_what_to_set(self):
        runner = _Runner()
        result = await self._tool(runner, env={}).run({"command": "uptime"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn(HOST_ENV, result.error)
        self.assertEqual(runner.calls, [], "a refusal must not have connected to anything")

    async def test_a_catastrophic_command_is_refused_before_connecting(self):
        runner = _Runner()
        result = await self._tool(runner).run({"command": "rm -rf /"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("refused", result.error)
        self.assertEqual(runner.calls, [])

    async def test_an_empty_command_is_refused(self):
        result = await self._tool(_Runner()).run({"command": "  "}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_a_successful_run_returns_the_remote_output(self):
        result = await self._tool(_Runner(_Completed(stdout="linux build ok"))).run(
            {"command": "make"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("linux build ok", result.output)

    async def test_a_missing_key_file_names_the_path_not_its_contents(self):
        env = dict(HOST, **{KEY_ENV: "/nope/id_ed25519"})
        runner = _Runner()
        result = await self._tool(runner, env=env).run({"command": "uptime"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("/nope/id_ed25519", result.error)
        self.assertEqual(runner.calls, [])

    async def test_a_nonzero_exit_is_a_failure_that_names_the_host(self):
        result = await self._tool(_Runner(_Completed(returncode=2, stderr="boom"))).run(
            {"command": "make"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("build.example.test", result.error)
        self.assertIn("boom", result.metadata["stderr"])

    async def test_no_ssh_on_the_machine_is_a_result_not_a_crash(self):
        result = await self._tool(_Runner(raises=FileNotFoundError())).run(
            {"command": "uptime"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("ssh", result.error)

    async def test_a_timeout_is_reported_rather_than_hanging(self):
        result = await self._tool(
            _Runner(raises=subprocess.TimeoutExpired("ssh", 1))).run({"command": "sleep 999"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout")

    async def test_it_claims_no_local_side_effects_it_cannot_see(self):
        # run_shell reports written_paths via writewatch. This tool
        # genuinely cannot know what changed on the far side, and saying
        # otherwise would be exactly the honesty failure the
        # verification checks exist to prevent.
        result = await self._tool(_Runner()).run({"command": "make"}, ctx=_ctx())
        self.assertEqual(len(result.side_effects), 1)
        self.assertTrue(result.side_effects[0].startswith("run_remote:"))
        self.assertNotIn("file_write", " ".join(result.side_effects))
        self.assertIn("another machine", result.metadata["note"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
