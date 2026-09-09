"""`run_container` (execution/container.py).

The one tool whose isolation runs the other way round: the container
cannot see the repository at all. Most of what follows checks that
promise and the bounds around it -- the image allowlist, the absence of
a repo bind mount, and that a timeout actually kills the container
rather than orphaning it.

A fake `docker` (a shell script that records its argv) stands in for
the daemon, so the argv assertions are exact and run anywhere. One real
smoke test uses the actual daemon when it happens to be up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.container import RunContainerTool, find_docker


def _ctx(config, action_id="a1"):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(action_id=action_id, task_id=None, scope={}, constraints={},
                       data_dir=config.repo_root, clock=None, logger=None, ledger=None)


class _FakeDocker:
    """Records every argv, and answers `docker info` as a live daemon."""

    def __init__(self, returncode=0, stdout="hello from the container"):
        self.calls: list[list[str]] = []
        self.returncode, self.stdout = returncode, stdout
        self.timeout_on_run = False

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if len(argv) > 1 and argv[1] == "info":
            return _Completed(0, "29.7.2", "")
        if self.timeout_on_run and len(argv) > 1 and argv[1] == "run":
            raise subprocess.TimeoutExpired(argv, 1)
        return _Completed(self.returncode, self.stdout, "")

    def argv_for(self, verb):
        return next((c for c in self.calls if len(c) > 1 and c[1] == verb), None)


class _Completed:
    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class RunContainerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        self.addCleanup(self._tmp.cleanup)
        self.docker = _FakeDocker()

    def _tool(self, **config):
        settings = {"repo_root": self.root}
        settings.update(config)
        return RunContainerTool(Config(**settings), docker_path="/fake/docker", runner=self.docker)

    async def test_it_runs_and_returns_stdout(self):
        result = await self._tool().run(
            {"image": "python:3.12-slim", "command": ["python", "-c", "print(1)"]},
            ctx=_ctx(Config(repo_root=self.root)))
        self.assertTrue(result.ok, result.error)
        self.assertIn("hello from the container", result.output)

    async def test_the_repo_is_never_mounted_into_the_container(self):
        """The load-bearing isolation claim. A bind mount of the repo
        would make every write-scope rule advisory."""
        await self._tool().run({"image": "python:3.12-slim", "command": ["true"]},
                               ctx=_ctx(Config(repo_root=self.root)))
        argv = self.docker.argv_for("run")
        mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
        self.assertEqual(len(mounts), 1)
        self.assertTrue(mounts[0].endswith(":/work"))
        self.assertNotIn(f"{self.root}:", mounts[0].replace(f"{self.root}/results", ""))

    async def test_the_default_run_is_locked_down(self):
        await self._tool().run({"image": "python:3.12-slim", "command": ["true"]},
                               ctx=_ctx(Config(repo_root=self.root)))
        argv = self.docker.argv_for("run")
        for flag in ("--rm", "--read-only", "--pids-limit", "--memory", "--cpus"):
            self.assertIn(flag, argv, f"{flag} missing")
        self.assertIn("none", argv)  # --network none by default

    async def test_network_is_opt_in(self):
        await self._tool().run(
            {"image": "python:3.12-slim", "command": ["true"], "network": True},
            ctx=_ctx(Config(repo_root=self.root)))
        self.assertIn("bridge", self.docker.argv_for("run"))

    async def test_an_image_outside_the_allowlist_is_refused(self):
        for image in ("evil/backdoor:latest", "", "python", "ubuntu"):
            with self.subTest(image=image):
                result = await self._tool().run(
                    {"image": image, "command": ["true"]}, ctx=_ctx(Config(repo_root=self.root)))
                self.assertFalse(result.ok)
                self.assertIn("not an allowed image", result.error)

    async def test_a_registry_host_disguised_as_an_allowed_prefix_is_refused(self):
        # `python:5000/evil/image:latest` starts with the allowed prefix
        # `python:` as a bare string, but Docker's reference grammar
        # parses `python:5000` as a REGISTRY HOST (port 5000) and pulls
        # `evil/image:latest` from it -- not the official python image.
        # Confirmed live: `docker pull python:5000/malicious/image:latest`
        # dials `https://python:5000/v2/`, never touching Docker Hub.
        # Whoever controls what `python` resolves to (hosts file, DNS,
        # a shared docker network) controls the real image that runs,
        # making the allowlist a no-op.
        for image in (
            "python:5000/evil/image:latest",
            "node:1234/anything",
            "alpine:sneaky.host/repo:tag",
            "python:localhost/evil:latest",
        ):
            with self.subTest(image=image):
                docker = _FakeDocker()
                tool = RunContainerTool(Config(repo_root=self.root), docker_path="/fake/docker", runner=docker)
                result = await tool.run(
                    {"image": image, "command": ["true"]}, ctx=_ctx(Config(repo_root=self.root)))
                self.assertFalse(result.ok, f"{image!r} should have been refused")
                self.assertIsNone(docker.argv_for("run"))

    async def test_a_command_must_be_real(self):
        for command in ([], "", None, [1, 2]):
            with self.subTest(command=command):
                result = await self._tool().run(
                    {"image": "python:3.12-slim", "command": command},
                    ctx=_ctx(Config(repo_root=self.root)))
                self.assertFalse(result.ok)

    async def test_a_string_command_is_split_without_a_shell(self):
        await self._tool().run({"image": "alpine:3", "command": "echo hi there"},
                               ctx=_ctx(Config(repo_root=self.root)))
        argv = self.docker.argv_for("run")
        self.assertEqual(argv[-3:], ["echo", "hi", "there"])

    async def test_input_files_are_copied_not_mounted(self):
        (self.root / "docs" / "data.csv").write_text("a,b\n1,2\n")
        config = Config(repo_root=self.root)
        result = await self._tool().run(
            {"image": "python:3.12-slim", "command": ["true"], "input_files": ["docs/data.csv"]},
            ctx=_ctx(config, action_id="copy1"))
        self.assertTrue(result.ok, result.error)
        staged = self.root / config.container_scratch_dir / "copy1" / "data.csv"
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_text(), "a,b\n1,2\n")

    async def test_an_input_file_outside_the_readable_roots_is_refused(self):
        result = await self._tool().run(
            {"image": "python:3.12-slim", "command": ["true"], "input_files": ["../../etc/passwd"]},
            ctx=_ctx(Config(repo_root=self.root)))
        self.assertFalse(result.ok)

    async def test_a_timeout_kills_the_container_rather_than_orphaning_it(self):
        # Killing the docker CLI leaves the container running with
        # nobody watching -- the same lesson as the hung MCP server.
        self.docker.timeout_on_run = True
        result = await self._tool().run(
            {"image": "python:3.12-slim", "command": ["sleep", "999"]},
            ctx=_ctx(Config(repo_root=self.root)))
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout")
        self.assertIsNotNone(self.docker.argv_for("kill"))
        self.assertIsNotNone(self.docker.argv_for("rm"))

    async def test_a_dead_daemon_is_a_clean_refusal(self):
        class _Dead(_FakeDocker):
            def __call__(self, argv, **kwargs):
                self.calls.append(list(argv))
                return _Completed(1, "", "Cannot connect to the Docker daemon")

        tool = RunContainerTool(Config(repo_root=self.root), docker_path="/fake/docker", runner=_Dead())
        result = await tool.run({"image": "alpine:3", "command": ["true"]},
                                ctx=_ctx(Config(repo_root=self.root)))
        self.assertFalse(result.ok)
        self.assertIn("daemon is not running", result.error)

    async def test_no_docker_at_all_is_a_clean_refusal(self):
        tool = RunContainerTool(Config(repo_root=self.root), docker_path="", runner=self.docker)
        tool._docker = ""
        result = await tool.run({"image": "alpine:3", "command": ["true"]},
                                ctx=_ctx(Config(repo_root=self.root)))
        self.assertFalse(result.ok)
        self.assertIn("no `docker`", result.error)


class FindDockerTestCase(unittest.TestCase):
    def test_a_configured_path_wins(self):
        self.assertEqual(find_docker("/custom/docker"), "/custom/docker")

    def test_it_finds_docker_on_this_machine_or_says_nothing(self):
        found = find_docker()
        self.assertTrue(found == "" or Path(found).exists() or shutil.which("docker"))


class RealDockerSmokeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_real_container_runs_and_leaves_nothing_behind(self):
        docker = find_docker()
        if not docker:
            self.skipTest("docker not installed")
        probe = subprocess.run([docker, "info"], capture_output=True, text=True, timeout=20)
        if probe.returncode != 0:
            self.skipTest("docker daemon not running")
        if os.environ.get("SIMORGH_SKIP_DOCKER_PULL"):
            self.skipTest("image pulls disabled")
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(repo_root=Path(tmp), container_timeout_s=120.0)
            tool = RunContainerTool(config)
            result = await tool.run(
                {"image": "alpine:3", "command": ["sh", "-c", "echo simorgh-live"]},
                ctx=_ctx(config, action_id="live1"))
        if not result.ok and "pull" in (result.metadata.get("stderr", "") or "").lower():
            self.skipTest("image not present and could not be pulled here")
        self.assertTrue(result.ok, result.metadata.get("stderr"))
        self.assertIn("simorgh-live", result.output)
        listing = subprocess.run([docker, "ps", "-a", "--format", "{{.Names}}"],
                                 capture_output=True, text=True, timeout=20)
        self.assertNotIn("simorgh-live1", listing.stdout)
