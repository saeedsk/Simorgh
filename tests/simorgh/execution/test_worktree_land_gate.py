"""The landing gate is as strict as the boot gate (2026-09-18 evaluation, S5).

`RunTestsTool.gate` runs the whole suite on the tree about to become
main. It used to accept pytest exit 5 ("no tests collected") and never
read the summary or compare the count, so a branch that deleted the
tests it was gated by landed. It now re-judges a green run with the
bootloader's own `unit_verdict`, loaded from the main checkout.
"""

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from simorgh.contracts.protocols import ToolResult
from simorgh.execution.config import Config
from simorgh.execution.tools import RunTestsTool

pytestmark = pytest.mark.contract

REPO = Path(__file__).resolve().parents[3]


class TheLandingGateUsesTheLoadersVerdict(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        shutil.copy(REPO / "simloader.py", self.root / "simloader.py")
        notes = self.root / ".simorgh_loader"
        notes.mkdir()
        (notes / "unit_baseline-all.json").write_text('{"tests": 1000, "seconds": 60}')
        self.tool = RunTestsTool(replace(Config(), repo_root=self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def _gate_with(self, result: ToolResult) -> ToolResult:
        with mock.patch.object(RunTestsTool, "_run_isolated", return_value=result):
            return self.tool.gate(self.root)

    def test_a_full_green_run_lands(self):
        out = self._gate_with(ToolResult(ok=True, output="1000 passed in 60.0s"))
        self.assertTrue(out.ok)

    def test_nothing_collected_is_refused(self):
        out = self._gate_with(ToolResult(ok=True, output="\n\n[no tests cover this target yet -- nothing was run]"))
        self.assertFalse(out.ok)
        self.assertIn("no tests actually ran", out.error)

    def test_a_gutted_suite_is_refused(self):
        out = self._gate_with(ToolResult(ok=True, output="40 passed in 1.0s"))
        self.assertFalse(out.ok)
        self.assertIn("shrank", out.error)

    def test_a_forged_exit_code_is_refused_by_the_summary(self):
        # A conftest can set exitstatus = 0; the summary still says "failed".
        out = self._gate_with(ToolResult(ok=True, output="2 failed, 998 passed in 60.0s"))
        self.assertFalse(out.ok)
        self.assertIn("failed", out.error)

    def test_a_red_run_is_passed_through_untouched(self):
        red = ToolResult(ok=False, error="failed", output="1 failed, 999 passed")
        self.assertIs(self._gate_with(red), red)

    def test_no_loader_means_no_second_opinion(self):
        (self.root / "simloader.py").unlink()
        out = self._gate_with(ToolResult(ok=True, output="40 passed in 1.0s"))
        self.assertTrue(out.ok)
