"""Recording what Sim printed (contracts/console.py).

The creator, live 2026-09-16: "what was the red message? what was
happening?" -- a question about Sim's own screen. Sim's process had
stdout, stderr and stdin all on one tty and nothing capturing any of
them, so there was no artifact to consult. It tried `read_file` on a
log that does not exist, got a refusal, searched and got no matches,
and then answered with three 429 rate-limit errors, a garden camera
timing out and a front-camera baseline that had updated fine. None of
that had happened; `workspace/cameras/baselines.json` did not exist at
all.

These tests are about the artifact existing. `test_console_tail.py`
covers the tool that reads it.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import console


class ConsoleRecordTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        # settings_home() reads $SIMORGH_CONFIG's PARENT, so point it at a
        # file inside the temp dir. Without this the tests would append to
        # the creator's real ~/.simorgh/interface/console.log.
        patch = mock.patch.dict(os.environ, {"SIMORGH_CONFIG": str(self.home / "simorgh.toml")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_printed_line_can_be_read_back(self):
        console.record("[error] the NVR refused the snapshot")
        self.assertIn("the NVR refused the snapshot", "\n".join(console.tail()))

    def test_the_colour_is_stripped_before_it_is_written(self):
        """A recorded line is read by a model and by a person, and an
        escape sequence helps neither -- `\\x1b[2J` cleared a real
        terminal in the 2026-09-10 incident."""
        console.record("\x1b[31m[error] red on screen\x1b[0m")
        line = console.tail()[-1]
        self.assertIn("[error] red on screen", line)
        self.assertNotIn("\x1b", line)

    def test_nothing_recorded_reads_as_nothing_not_as_an_error(self):
        self.assertEqual(console.tail(), [])

    def test_the_filter_finds_the_last_matching_lines_not_the_matches_in_the_last_lines(self):
        """The distinction that makes the filter worth having: an error
        200 lines ago is exactly the one being asked about."""
        console.record("[error] the first thing that went wrong")
        for n in range(50):
            console.record(f"[info] ordinary line {n}")
        found = console.tail(5, contains="error")
        self.assertEqual(len(found), 1)
        self.assertIn("the first thing that went wrong", found[0])

    def test_the_filter_ignores_case(self):
        console.record("[error] Ring WebRTC KeyError")
        self.assertTrue(console.tail(10, contains="keyerror"))

    def test_the_file_is_bounded(self):
        """Unbounded append is how this project got a 192k-file trace
        directory on 2026-09-07."""
        with mock.patch.object(console, "MAX_BYTES", 2000), \
             mock.patch.object(console, "KEEP_LINES", 20), \
             mock.patch.object(console, "_CHECK_EVERY", 10):
            for n in range(400):
                console.record(f"[info] line {n} " + "x" * 40)
        self.assertLessEqual(console.console_log_path().stat().st_size, 4000)
        self.assertIn("line 399", console.tail(50)[-1])

    def test_recording_never_raises_even_when_it_cannot_write(self):
        """`_out` is the one gate every scrolling line passes through.
        A console that could not print because its recorder threw would
        be strictly worse than one that forgets."""
        with mock.patch.object(Path, "open", side_effect=OSError("read-only fs")):
            console.record("[error] this must not blow up the REPL")

    def test_a_blank_line_is_not_recorded(self):
        console.record("   ")
        console.record("")
        self.assertEqual(console.tail(), [])


if __name__ == "__main__":
    unittest.main()
