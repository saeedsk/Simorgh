"""voice/health.py: the machine's excuse for a slow hearing, read from
the power state (2026-09-13: a 2% battery throttled the GPU fifteenfold
and nothing said so)."""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from simorgh.voice import health

_PMSET_LOW = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=21954659)\t2%; charging; (no estimate) present: true
"""
_PMSET_FULL = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=21954659)\t100%; charged; 0:00 remaining present: true
"""


class HealthTestCase(unittest.TestCase):
    def setUp(self):
        health._cache = (0.0, {})  # noqa: SLF001

    def _with(self, text):
        return mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=text, stderr=""))

    def test_a_low_battery_is_named_as_the_reason(self):
        with self._with(_PMSET_LOW), mock.patch.object(health.shutil, "which", return_value="/usr/bin/pmset"):
            state = health.power_state()
            self.assertEqual((state["battery_pct"], state["charging"], state["source"]), (2, True, "AC Power"))
            notes = health.machine_notes()
            self.assertEqual(len(notes), 1); self.assertIn("battery at 2%", notes[0]); self.assertIn("charging", notes[0])
            self.assertIn("battery at 2%", health.slow_hearing_note(45.0))
            self.assertEqual(health.slow_hearing_note(2.0), "", "a normal hearing needs no excuse")

    def test_a_full_battery_gives_no_note_and_a_slow_hearing_still_gets_a_line(self):
        with self._with(_PMSET_FULL), mock.patch.object(health.shutil, "which", return_value="/usr/bin/pmset"):
            self.assertEqual(health.machine_notes(), [])
            note = health.slow_hearing_note(12.0)
            self.assertIn("hearing took 12 s", note); self.assertIn("voice status", note)

    def test_no_pmset_is_no_state(self):
        with mock.patch.object(health.shutil, "which", return_value=None):
            self.assertEqual(health.power_state(), {})
            self.assertEqual(health.machine_notes(), [])
