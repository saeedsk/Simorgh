"""A dataset name stored cut in half still finds its test.

SWE-bench's own FAIL_TO_PASS / PASS_TO_PASS lists were built by
splitting log lines on whitespace, so a parametrised id containing a
space is stored up to that space:

    expected: ...::test_totxtfile[home_is_data,
    the log:  ...::test_totxtfile[home_is_data, pathlib]

Live, 2026-09-22: astropy-14598 ran for 11 minutes, produced a patch,
and was thrown away as "2 named test(s) never appeared in the log" --
a case neither scored nor retried, because of a comma in someone else's
name list.
"""

import unittest

from simorgh.benchmark.swebench import judge

CASE = "astropy/io/fits/tests/test_header.py::TestHeaderFunctions"
LOG = f"""
PASSED {CASE}::test_totxtfile[]
PASSED {CASE}::test_totxtfile[home_is_data]
PASSED {CASE}::test_totxtfile[home_is_data, pathlib]
PASSED {CASE}::test_fixed
======================== 4 passed in 2.81s =========================
"""


def _instance(fail_to_pass, pass_to_pass=()):
    return {"log_parser": "parse_log_astropy",
            "FAIL_TO_PASS": list(fail_to_pass), "PASS_TO_PASS": list(pass_to_pass)}


class ATruncatedNameIsStillMeasured(unittest.TestCase):
    def test_the_cut_name_matches_the_one_test_that_extends_it(self):
        verdict = judge(LOG, _instance([f"{CASE}::test_fixed"],
                                       [f"{CASE}::test_totxtfile[home_is_data,"]))
        self.assertTrue(verdict.resolved, verdict.detail)
        self.assertFalse(verdict.skipped)

    def test_an_ambiguous_cut_stays_unmeasurable(self):
        """`test_totxtfile[` extends to three different tests. A name
        that cannot tell them apart must not pick one: unmeasurable is
        the honest answer."""
        verdict = judge(LOG, _instance([f"{CASE}::test_fixed"],
                                       [f"{CASE}::test_totxtfile["]))
        self.assertFalse(verdict.resolved)
        self.assertTrue(verdict.skipped)
        self.assertIn("never appeared", verdict.detail)

    def test_a_name_that_is_simply_absent_is_still_absent(self):
        """Only an UNBALANCED bracket is the truncation signature. A
        whole name the log never mentions means the run did not do what
        we think it did, and that must keep saying so."""
        verdict = judge(LOG, _instance([f"{CASE}::test_never_ran"]))
        self.assertTrue(verdict.skipped)
        self.assertIn("never appeared", verdict.detail)

    def test_a_cut_name_that_failed_is_reported_as_failing(self):
        failing = LOG.replace(f"PASSED {CASE}::test_totxtfile[home_is_data, pathlib]",
                              f"FAILED {CASE}::test_totxtfile[home_is_data, pathlib]")
        verdict = judge(failing, _instance([f"{CASE}::test_fixed"],
                                           [f"{CASE}::test_totxtfile[home_is_data,"]))
        self.assertFalse(verdict.resolved)
        self.assertFalse(verdict.skipped, "measured, and it failed")
        self.assertIn("still failing", verdict.detail)


if __name__ == "__main__":
    unittest.main()
