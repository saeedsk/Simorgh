"""Verification's own pytest runs inherit no credential and run under
resource limits (found writing verification's CONTRACT.md, 2026-09-19:
`still_failing_here` ran the model's tests with Sim's full environment)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.verification.checks import _baseline


class TheRunsAreScrubbed(unittest.TestCase):
    def test_the_environment_keeps_path_and_drops_keys(self):
        with mock.patch.dict(os.environ, {"TOGETHER_API_KEY": "secret", "SIM_API_TOKEN": "t", "PATH": "/usr/bin"}):
            env = _baseline._scrubbed_env()  # noqa: SLF001
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertNotIn("TOGETHER_API_KEY", env)
        self.assertNotIn("SIM_API_TOKEN", env)

    def test_a_rerun_on_the_task_tree_gets_the_scrubbed_env_and_limits(self):
        seen = {}

        def fake_run(argv, **kw):
            seen.update(kw)
            raise OSError("stop here")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(_baseline.subprocess, "run", side_effect=fake_run), \
                mock.patch.dict(os.environ, {"TOGETHER_API_KEY": "secret"}):
            (Path(tmp) / "tests").mkdir()
            _baseline.still_failing_here(Path(tmp), ("tests/test_x.py::test_y",))
        self.assertNotIn("TOGETHER_API_KEY", seen.get("env", {"TOGETHER_API_KEY": "leaked"}))
        self.assertIsNotNone(seen.get("preexec_fn"))


@unittest.skipUnless(sys.platform == "darwin" and os.path.exists(_baseline._SANDBOX_EXEC), "macOS sandbox only")  # noqa: SLF001
class ATestTheModelWroteIsConfined(unittest.TestCase):
    """Stage 0 item 32: the scrub took the keys; a model-written test
    could still reach the network and write anywhere the user can."""

    def _run(self, body: str) -> subprocess.CompletedProcess:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        (work / "repo").mkdir()
        (work / "repo" / "test_probe.py").write_text(body)
        argv, env = _baseline._confined([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",  # noqa: SLF001
                                         "test_probe.py"], work)
        return subprocess.run(argv, cwd=work / "repo", capture_output=True, text=True, env=env, timeout=60)

    def test_no_network(self):
        done = self._run("import socket\ndef test_x():\n    socket.create_connection(('1.1.1.1', 80), timeout=3)\n")
        self.assertIn("Operation not permitted", done.stdout)

    def test_no_writes_outside_the_copy(self):
        target = Path.home() / f".simorgh-sandbox-probe-{os.getpid()}"
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        done = self._run(f"from pathlib import Path\ndef test_x():\n    Path({str(target)!r}).write_text('x')\n")
        self.assertFalse(target.exists())
        self.assertIn("Operation not permitted", done.stdout)

    def test_an_ordinary_test_still_passes(self):
        done = self._run("def test_x(tmp_path):\n    (tmp_path / 'a').write_text('x')\n")
        self.assertEqual(done.returncode, 0, done.stdout[-500:])
