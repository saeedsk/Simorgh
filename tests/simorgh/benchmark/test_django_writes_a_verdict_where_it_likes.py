"""Django's runner does not put a test's verdict on the test's own line.

It writes `label ... ` when a test STARTS and the verdict when it ENDS,
so everything printed in between -- "Testing against Django installed in
/testbed/django", the migrations, the test's own output -- sits between
the two. And when a test defers its result (subtests report at the end),
the next test's label simply continues the same line.

Live, 2026-09-22: of a 30-case run, NINE cases were thrown away as
"named test(s) never appeared in the log". django-10914's label was at
line 36,671 and its `ok` at 36,695; django-10999's line named two tests
and so named neither. Both logs said plainly what had happened.
"""

import unittest

from simorgh.benchmark.swebench import parse_django

CLASS = "test_utils.tests.XMLEqualTests"


class DjangoWritesAVerdictWhereItLikes(unittest.TestCase):
    def test_a_verdict_arriving_pages_later_still_belongs_to_its_test(self):
        log = "\n".join([
            f"test_a ({CLASS}) ... Testing against Django installed in '/testbed'",
            "Importing application test_utils",
            "Creating table auth_permission",
            "System check identified no issues (0 silenced).",
            "ok",
        ])
        self.assertEqual(parse_django(log), {f"test_a ({CLASS})": "PASSED"})

    def test_two_labels_on_one_line_credit_only_the_second(self):
        """The `ok` is the last label's; the first test's result is
        genuinely unknown from that line, and guessing is how a passing
        test certifies a failing one."""
        log = f"test_a ({CLASS}) ... test_b ({CLASS}) ... ok"
        self.assertEqual(parse_django(log), {f"test_b ({CLASS})": "PASSED"})

    def test_a_deferred_failure_is_still_read_from_the_summary(self):
        log = "\n".join([
            f"test_a ({CLASS}) ... test_b ({CLASS}) ... ok",
            f"FAIL: test_a ({CLASS}) (source='-15:30')",
        ])
        self.assertEqual(parse_django(log), {f"test_b ({CLASS})": "PASSED", f"test_a ({CLASS})": "FAIL"})

    def test_a_docstring_label_is_not_cut_at_its_own_dots(self):
        """A documented test is named by its docstring -- free text that
        may contain "..." -- and cutting that would invent a name."""
        log = "Something with ... dots in it ... ok"
        self.assertEqual(parse_django(log), {"Something with ... dots in it": "PASSED"})

    def test_a_stray_verdict_belongs_to_nobody(self):
        self.assertEqual(parse_django("ok\nOK\nFAIL"), {})

    def test_a_second_label_before_any_verdict_leaves_the_first_unknown(self):
        log = "\n".join([f"test_a ({CLASS}) ... ", f"test_b ({CLASS}) ... ", "ok"])
        self.assertEqual(parse_django(log), {f"test_b ({CLASS})": "PASSED"},
                         "which test the ok belongs to is unknowable; only the nearest label may claim it")

    def test_the_ordinary_shape_still_works(self):
        log = "\n".join([f"test_a ({CLASS}) ... ok", f"test_b ({CLASS}) ... FAIL",
                         f"test_c ({CLASS}) ... skipped 'no db'"])
        self.assertEqual(parse_django(log), {f"test_a ({CLASS})": "PASSED", f"test_b ({CLASS})": "FAIL",
                                             f"test_c ({CLASS})": "SKIPPED"})


if __name__ == "__main__":
    unittest.main()
