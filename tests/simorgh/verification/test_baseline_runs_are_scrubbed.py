"""Verification's own pytest runs inherit no credential and run under
resource limits (found writing verification's CONTRACT.md, 2026-09-19:
`still_failing_here` ran the model's tests with Sim's full environment)."""

import os
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
