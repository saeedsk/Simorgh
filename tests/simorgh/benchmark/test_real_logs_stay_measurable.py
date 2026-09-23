"""Every SWE-bench log this machine has kept must still be judgeable.

Each parser shape was found the hard way, one live run at a time:
coloured output (2026-09-10), a dataset name truncated mid-bracket, a
Django verdict printed pages below its label, two labels sharing a line
(all 2026-09-22). Nine of thirty cases in one run were thrown away as
"named test(s) never appeared in the log" -- a harness failure that
looks exactly like the model failing, and cost about 17 points.

The logs under `results/swebench/` are the corpus that found them, so
they are the corpus that keeps them found. A new parser shape may be
added to `UNMEASURABLE` with a reason; silently losing a case that used
to score may not.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pytest

from simorgh.benchmark import swebench

REPO = Path(__file__).resolve().parents[3]
LOGS = REPO / "results" / "swebench"
DATASET = Path.home() / ".simorgh" / "benchmarks" / "swebench-verified.json"

#: Cases whose log genuinely cannot be judged, and why. Each is a real
#: gap someone chose to leave open, not a mystery.
UNMEASURABLE = {
    "django__django-10554": "the runner printed no verdict for one PASS_TO_PASS test",
    "astropy__astropy-14369": "the dataset names parametrised ids this run never collected",
}

pytestmark = pytest.mark.skipif(not DATASET.exists() or not LOGS.is_dir(),
                                reason="no local SWE-bench dataset or kept logs")


def _rows() -> dict:
    return {r["instance_id"]: r for r in json.loads(DATASET.read_text())["rows"]}


class RealLogsStayMeasurable(unittest.TestCase):
    def test_every_kept_log_reaches_a_verdict(self):
        rows = _rows()
        unmeasurable: list[str] = []
        judged = 0
        for log in sorted(LOGS.glob("*.log")):
            row = rows.get(log.stem)
            if row is None:
                continue                      # a case from an older dataset version
            verdict = swebench.judge(log.read_text(errors="replace"), row)
            judged += 1
            if verdict.skipped and log.stem not in UNMEASURABLE:
                unmeasurable.append(f"{log.stem}: {verdict.detail[:90]}")
        self.assertGreater(judged, 10, "the corpus went missing")
        self.assertEqual(unmeasurable, [], "these used to be judgeable")

    def test_the_parsers_find_tests_in_every_log(self):
        """A log that parses to NOTHING means the runner printed a shape
        neither reader understands -- the 2026-09-10 ANSI bug, which
        scored a whole passing run as 'the suite most likely never ran'.
        """
        rows = _rows()
        empty = []
        for log in sorted(LOGS.glob("*.log")):
            row = rows.get(log.stem)
            if row is None:
                continue
            results, problem = swebench.parse_log(log.read_text(errors="replace"), row["log_parser"])
            if problem or not results:
                empty.append(f"{log.stem}: {problem or 'no results parsed'}")
        self.assertEqual(empty, [])


if __name__ == "__main__":
    unittest.main()
