"""The household scenario runs against the real booted system and keeps
what works (2026-09-19: 3 of 3 probes, up from 2 of 3 that morning).

Pinned: a correction reaches the model after what it corrects (the
conversation window, stage 0 item 8); a fact asked about in its own
words is recalled; and -- since stage 5's dense recall and fact store --
a fact asked about in DIFFERENT words 13 turns later (`machines@14`),
which was the open one this file used to describe as stage 5's job.
"""

import asyncio
import contextlib
import io
import unittest

import pytest

from simorgh.evals.scenario import run

pytestmark = pytest.mark.integration


class TheRecallScenario(unittest.TestCase):
    def test_the_baseline_holds(self):
        with contextlib.redirect_stdout(io.StringIO()):
            report = asyncio.run(run())
        probes = {p["probe"]: p for p in report["probes"]}
        self.assertTrue(probes["birthday@15"]["seen"])
        self.assertTrue(probes["birthday@15"]["order_ok"], "the correction must come after what it corrects")
        self.assertTrue(probes["machines@18"]["seen"])
        self.assertTrue(probes["machines@14"]["seen"],
                        "asked in different words 13 turns later -- stage 5's dense recall")
        self.assertEqual(report["score"], report["of"])
