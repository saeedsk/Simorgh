"""The boot progress reporter: what it prints, and where it stays silent.

The creator asked for this after a 38-second boot that printed nothing
until it was over, so the two properties that matter are that a stage
names itself *before* it runs (not after) and that a slow stage is
visibly marked.
"""

import io
import unittest

from simorgh.kernel.bootprogress import (
    SLOW_STAGE_S,
    BootProgress,
    NullBootProgress,
    make_boot_progress,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _plain(chunks: list[str]) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", "".join(chunks))


class TestWhatItPrints(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks: list[str] = []
        self.clock = _Clock()
        self.p = BootProgress(out=self.chunks.append, color=False, total=4, now=self.clock)

    def test_a_stage_names_itself_before_it_runs(self):
        """The whole point: the label is on screen while the slow thing
        is happening, not once it has finished."""
        self.p.stage("ledger", "opening ~/.simorgh")
        out = _plain(self.chunks)
        self.assertIn("ledger", out)
        self.assertIn("opening ~/.simorgh", out)
        self.assertNotIn("\n", out)  # still in place, not committed

    def test_finishing_a_stage_commits_a_line_with_its_elapsed_time(self):
        self.p.stage("ledger")
        self.clock.t = 0.4
        self.p.done()
        out = _plain(self.chunks)
        self.assertIn("0.4s", out)
        self.assertTrue(out.endswith("\n"))

    def test_a_slow_stage_is_marked(self):
        self.p.stage("ledger")
        self.clock.t = SLOW_STAGE_S + 0.5
        self.p.done()
        self.assertIn("slow", _plain(self.chunks))

    def test_a_fast_stage_is_not_marked(self):
        self.p.stage("bus")
        self.clock.t = 0.01
        self.p.done()
        self.assertNotIn("slow", _plain(self.chunks))

    def test_detail_can_be_replaced_once_the_stage_knows_more(self):
        self.p.stage("ledger", "opening")
        self.p.detail("192,456 streams, 3 re-read")
        self.p.done()
        self.assertIn("192,456 streams, 3 re-read", _plain(self.chunks))

    def test_starting_a_stage_closes_the_previous_one(self):
        self.p.stage("ledger")
        self.p.stage("bus")
        self.assertEqual(_plain(self.chunks).count("\n"), 1)

    def test_the_bar_fills_as_stages_complete(self):
        first = []
        self.p._out = first.append  # noqa: SLF001
        self.p.stage("one")
        last = []
        self.p._out = last.append  # noqa: SLF001
        for name in ("two", "three", "four"):
            self.p.stage(name)
        self.assertGreater(_plain(last).count("█"), _plain(first).count("█"))

    def test_finish_reports_the_total_and_closes_an_open_stage(self):
        self.p.stage("ledger")
        self.clock.t = 1.25
        self.p.finish("15 subsystems")
        out = _plain(self.chunks)
        self.assertIn("ready in", out)
        self.assertIn("1.2s", out)
        self.assertIn("15 subsystems", out)

    def test_detail_before_any_stage_is_a_no_op(self):
        self.p.detail("nothing open")
        self.assertEqual(self.chunks, [])


class TestWhenItStaysSilent(unittest.TestCase):
    def test_a_non_interactive_run_gets_the_null_reporter(self):
        self.assertIsInstance(make_boot_progress(False), NullBootProgress)

    def test_a_pipe_gets_the_null_reporter_even_when_interactive(self):
        """In-place rewriting is noise in a log file or a pipe."""
        self.assertIsInstance(make_boot_progress(True, stream=io.StringIO()), NullBootProgress)

    def test_a_tty_gets_a_real_reporter(self):
        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        self.assertIsInstance(make_boot_progress(True, stream=_Tty()), BootProgress)

    def test_the_null_reporter_accepts_every_call(self):
        p = NullBootProgress()
        p.stage("x", "y")
        p.detail("z")
        p.done("w")
        p.finish("v")  # no exception is the assertion


if __name__ == "__main__":
    unittest.main()
