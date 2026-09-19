"""The household recall scenario runs against the real booted system and
keeps what already works (2026-09-19 baseline: 2 of 3 probes).

Pinned: a correction reaches the model after what it corrects (the
conversation window, stage 0 item 8), and a fact asked about in its own
words is recalled. Not pinned, on purpose: a fact asked about in
DIFFERENT words 13 turns later (`machines@14`) -- that is stage 5's job
(real embeddings, a fact store); when it passes, turn it into an
assertion here.
"""

import asyncio
import contextlib
import io
import unittest

import pytest

from tools.recall_scenario import run

pytestmark = pytest.mark.integration


class TheRecallScenario(unittest.TestCase):
    def test_the_baseline_holds(self):
        with contextlib.redirect_stdout(io.StringIO()):
            report = asyncio.run(run())
        probes = {p["probe"]: p for p in report["probes"]}
        self.assertTrue(probes["birthday@15"]["seen"])
        self.assertTrue(probes["birthday@15"]["order_ok"], "the correction must come after what it corrects")
        self.assertTrue(probes["machines@18"]["seen"])
        self.assertGreaterEqual(report["score"], 2)
