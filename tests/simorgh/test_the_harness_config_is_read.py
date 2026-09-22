"""The trial harness's own config is read by the Sim it boots.

`tools/trial.py`, `trial_suite.py`, `bench_instance.py` and
`kill_resume_trial.py` all set `[curiosity] autonomy_on_boot = false` --
"the point of a trial: nothing self-directed competes with it". The
section moved to `[growth.explore]` on 2026-09-20 and nothing read the
old one, so every trial since ran with autonomy ON (found 2026-09-22,
from the `config.section_moved` warning in a trial's own output).
"""

import re
import unittest
from pathlib import Path

from simorgh.growth.explore.config import Config as ExploreConfig
from simorgh.kernel.configcheck import RENAMED_SECTIONS

TOOLS = Path(__file__).resolve().parents[2] / "tools"
HARNESS = ("trial.py", "trial_suite.py", "bench_instance.py", "kill_resume_trial.py")


class TheHarness(unittest.TestCase):
    def test_no_tool_writes_a_section_that_moved(self):
        for name in HARNESS:
            text = (TOOLS / name).read_text()
            for old in RENAMED_SECTIONS:
                self.assertIsNone(re.search(rf'"{re.escape(old)}"\s*:\s*\{{', text),
                                  f"{name} still configures [{old}], which nothing reads")

    def test_no_test_configures_a_section_that_moved(self):
        """A test that sets `[curiosity]` boots with autonomy ON -- the
        opposite of what it asked for -- and passes anyway (eleven did,
        found 2026-09-22)."""
        tests = Path(__file__).resolve().parent
        for path in tests.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for old in RENAMED_SECTIONS:
                self.assertIsNone(re.search(rf'LoadedConfig\(\{{[^)]*"{re.escape(old)}"\s*:\s*\{{', text, re.S)
                                  or re.search(rf'^\s*"{re.escape(old)}"\s*:\s*\{{"autonomy_on_boot"', text, re.M),
                                  f"{path.relative_to(tests)} configures [{old}], which nothing reads")

    def test_each_turns_autonomy_off_where_it_is_read(self):
        for name in HARNESS:
            self.assertRegex((TOOLS / name).read_text(),
                             r'"growth":\s*\{+"explore":\s*\{+"autonomy_on_boot":\s*False', name)

    def test_the_key_is_one_the_explore_part_reads(self):
        self.assertIn("autonomy_on_boot", ExploreConfig.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
