"""`tools/soak.py --status`: one line that says whether a soak is alive.

The soak died four times in the morning of 2026-09-23, and the fourth
time the supervisor died with it. Nothing about that was hard to see --
but seeing it took a `ps`, a `tail` and a clock, and asked twice whether
the soak was running I answered from the last check I remembered rather
than looking. So the question got one command, and these are the
answers it must not get wrong: a log that stopped an hour ago is not
alive just because a process is there, and a process that is gone is not
alive just because the log is full of good runs.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import soak


def _run(dir_path: Path, *events: dict) -> Path:
    """A run directory whose log holds `events`, newest last."""
    dir_path.mkdir(parents=True, exist_ok=True)
    with (dir_path / "soak.jsonl").open("w", encoding="utf-8") as out:
        for event in events:
            out.write(json.dumps(event) + "\n")
    return dir_path


class TheStatusLine(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _status(self, run: Path, *, pids: list[int]) -> str:
        with patch.object(soak, "_soak_pids", return_value=pids):
            return soak.status(run)

    def test_a_process_and_a_moving_log_is_alive(self):
        run = _run(self.root / "day",
                   {"at": time.time() - 300, "kind": "ok", "job": "boot"},
                   {"at": time.time() - 30, "kind": "ok", "job": "suite"})
        line = self._status(run, pids=[101, 102])
        self.assertIn("ALIVE", line)
        self.assertIn("2 run(s)", line)
        self.assertIn("0 failure(s)", line)

    def test_no_process_is_dead_however_good_the_log(self):
        """The failure that actually hid: a hundred clean runs, and the
        thing that made them gone."""
        run = _run(self.root / "day", *[{"at": time.time() - 60, "kind": "ok", "job": "house"}] * 100)
        line = self._status(run, pids=[])
        self.assertIn("DEAD", line)
        self.assertIn("100 run(s)", line)

    def test_a_process_with_a_stale_log_is_stuck(self):
        """Alive-looking and saying nothing is its own failure, and was
        never distinguishable before."""
        run = _run(self.root / "day", {"at": time.time() - 3 * 3600, "kind": "ok", "job": "arcs"})
        self.assertIn("STUCK", self._status(run, pids=[101]))

    def test_a_run_that_ended_is_finished_not_dead(self):
        """A soak whose hours ran out has no process and should not be
        reported as a corpse."""
        run = _run(self.root / "day",
                   {"at": time.time() - 4000, "kind": "ok", "job": "house"},
                   {"at": time.time() - 3600, "kind": "end", "runs": 1, "failures": 0})
        self.assertIn("FINISHED", self._status(run, pids=[]))

    def test_findings_are_counted_as_failures(self):
        run = _run(self.root / "day",
                   {"at": time.time() - 60, "kind": "ok", "job": "boot"},
                   {"at": time.time() - 30, "kind": "finding", "job": "suite", "why": "x"})
        line = self._status(run, pids=[101])
        self.assertIn("2 run(s)", line)
        self.assertIn("1 failure(s)", line)

    def test_restarts_are_visible(self):
        """A soak that is alive because it was restarted twice is not
        the same as one that never fell over, and the sitrep should say
        so without being asked."""
        run = _run(self.root / "day",
                   {"at": time.time() - 600, "kind": "restarted", "restarts": 1},
                   {"at": time.time() - 30, "kind": "ok", "job": "boot"})
        self.assertIn("1 restart(s)", self._status(run, pids=[101]))

    def test_an_empty_log_is_not_alive(self):
        run = self.root / "day"
        run.mkdir(parents=True)
        self.assertIn("DEAD", self._status(run, pids=[]))


class TheRunIsNamedBeforeForking(unittest.TestCase):
    """A restart re-runs this file. With an empty `--run`, each restart
    started a fresh dated run while the supervisor logged into the soak
    root -- so a soak that had been restarted looked like one that had
    never started."""

    def test_supervise_is_given_a_run_id(self):
        import argparse

        seen = {}

        def fake_detach(path):
            seen["log"] = path

        def fake_supervise(args):
            seen["run"] = args.run
            return 0

        argv = ["soak.py", "--detach", "--hours", "1", "--instances", "1"]
        with patch.object(soak.sys, "argv", argv), \
             patch.object(soak, "detach", fake_detach), \
             patch.object(soak, "supervise", fake_supervise):
            soak.main()
        self.assertTrue(seen["run"], "the run must be named before the fork, not by the child")
        self.assertIn(seen["run"], str(seen["log"]))


if __name__ == "__main__":
    unittest.main()
