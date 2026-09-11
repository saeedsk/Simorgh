"""A passing run that printed in colour parsed to nothing.

pytest emits SGR escapes whenever the repo's own config forces colour,
and several SWE-bench images do. Every pattern in `swebench.py` expects

    PASSED astropy/io/fits/tests/test_connect.py::test_is_fits_gh_14305

and a coloured run prints

    \x1b[32mPASSED\x1b[0m astropy/...::\x1b[1mtest_is_fits_gh_14305\x1b[0m

so the whole log parsed to zero entries and `judge` reported "the test
log had no recognisable results -- the suite most likely never ran (an
install or import failure earlier in the log)".

Live, 2026-09-10, first real SWE-bench Verified attempt:
`astropy__astropy-14309` ended `142 passed, 8 skipped, 5 xfailed in
2.14s` with the case's one fail-to-pass test among the passes. Sim had
really fixed it. The run recorded `skipped=True` -- honest about not
knowing, and wrong about not knowing. 0 entries parsed with the escapes
in, 142 with them out.

This is the expensive direction of the honesty rule: refusing to score
is right when the measurement failed, so a measurement that fails for a
cosmetic reason turns real work into no evidence at all.
"""

from __future__ import annotations

import unittest

from simorgh.benchmark.swebench import judge, parse_log, strip_ansi

GREEN, BOLD, OFF = "\x1b[32m", "\x1b[1m", "\x1b[0m"


def _coloured(status: str, nodeid: str) -> str:
    path, _, name = nodeid.partition("::")
    return f"{GREEN}{status}{OFF} {path}::{BOLD}{name}{OFF}"


class StripTestCase(unittest.TestCase):
    def test_colour_is_removed(self):
        self.assertEqual(strip_ansi(_coloured("PASSED", "a.py::test_x")), "PASSED a.py::test_x")

    def test_a_plain_log_is_untouched(self):
        plain = "PASSED a.py::test_x\nFAILED b.py::test_y\n"
        self.assertEqual(strip_ansi(plain), plain)

    def test_empty_and_none_are_safe(self):
        self.assertEqual(strip_ansi(""), "")
        self.assertEqual(strip_ansi(None), "")

    def test_other_escape_sequences_go_too(self):
        # Not only colour: a progress-bar rewrite (`\x1b[2K`) or a cursor
        # move sits in the middle of the same lines.
        self.assertEqual(strip_ansi("\x1b[2K\x1b[1GPASSED a.py::test_x"), "PASSED a.py::test_x")


class ColouredLogTestCase(unittest.TestCase):
    def test_a_coloured_log_parses(self):
        log = "\n".join([
            _coloured("PASSED", "astropy/io/fits/tests/test_connect.py::test_is_fits_gh_14305"),
            _coloured("PASSED", "astropy/io/fits/tests/test_connect.py::test_other"),
            f"{GREEN}=== {BOLD}142 passed{OFF} in 2.14s ==={OFF}",
        ])
        results, problem = parse_log(log, "parse_log_astropy")
        self.assertEqual(problem, "")
        self.assertEqual(results.get("astropy/io/fits/tests/test_connect.py::test_is_fits_gh_14305"),
                         "PASSED")

    def test_a_coloured_pass_is_judged_resolved(self):
        instance = {
            "FAIL_TO_PASS": ["t/test_x.py::test_new"],
            "PASS_TO_PASS": ["t/test_x.py::test_old"],
            "log_parser": "parse_log_astropy",
        }
        log = "\n".join([
            _coloured("PASSED", "t/test_x.py::test_new"),
            _coloured("PASSED", "t/test_x.py::test_old"),
        ])
        verdict = judge(log, instance)
        self.assertTrue(verdict.resolved, verdict.detail)
        self.assertFalse(verdict.skipped)

    def test_a_coloured_failure_is_still_a_failure(self):
        # The strip must not turn a red run green: the point is to read
        # the log, not to be generous with it.
        instance = {
            "FAIL_TO_PASS": ["t/test_x.py::test_new"],
            "PASS_TO_PASS": [],
            "log_parser": "parse_log_astropy",
        }
        verdict = judge(_coloured("FAILED", "t/test_x.py::test_new"), instance)
        self.assertFalse(verdict.resolved)
        self.assertFalse(verdict.skipped, "a measured failure is not an unmeasurable one")


if __name__ == "__main__":
    unittest.main()
