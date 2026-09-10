"""`level=1` has to mean the easiest level, whatever it is called.

GAIA's levels are literally named "1", "2" and "3", so `level=2` looked
like a solved problem. SWE-bench Verified's are named by how long a
human took -- `<15 min fix`, `15 min - 1 hour`, `1-4 hours`,
`>4 hours` -- and the creator typed `level=1` through `level=4` at it
four times in a row, getting `no_cases` every time (live, 2026-09-10).
Two separate failures behind one message:

  1. the level token was matched by exact string equality only, and
  2. the refusal named the level asked for and never the levels there,
     while `benchmark load` was printing them in ALPHABETICAL order --
     which puts a four-hour task second and makes the printed order
     useless as a thing to count along.

So: levels sort by difficulty, a bare number is an ordinal into that
order, and a token that names no level is `no_such_level` (which lists
them) rather than `no_cases` (which means the level exists and is
empty).
"""

from __future__ import annotations

import unittest

from simorgh.benchmark.api import Case, Suite, _level_key


def _suite(levels) -> Suite:
    return Suite(
        name="s",
        cases=tuple(Case(id=f"c{i}", question="q", answer="a", level=level)
                    for i, level in enumerate(levels)),
    )


SWEBENCH = ("1-4 hours", "15 min - 1 hour", "<15 min fix", ">4 hours")


class LevelOrderTestCase(unittest.TestCase):
    def test_durations_sort_by_duration_not_by_spelling(self):
        self.assertEqual(
            _suite(SWEBENCH).levels(),
            ("<15 min fix", "15 min - 1 hour", "1-4 hours", ">4 hours"),
        )

    def test_the_same_number_is_split_by_its_edge(self):
        # Both of these start at 15. `<` is less than a plain 15,
        # which is less than `>`.
        self.assertLess(_level_key("<15 min fix"), _level_key("15 min - 1 hour"))
        self.assertLess(_level_key("15 min"), _level_key(">15 min"))

    def test_a_number_after_the_first_does_not_win(self):
        # "15 min - 1 hour" contains "hour", and reading the unit by
        # name rather than by position made it an hour -- which sorted
        # it after "1-4 hours".
        self.assertLess(_level_key("15 min - 1 hour"), _level_key("1-4 hours"))

    def test_numeric_levels_are_unchanged(self):
        self.assertEqual(_suite(["3", "1", "2"]).levels(), ("1", "2", "3"))
        self.assertEqual(_suite(["10", "9"]).levels(), ("9", "10"))

    def test_families_do_not_interleave(self):
        # A number, a duration and a word are three different kinds of
        # level. Whatever the order between them, it is stable.
        levels = _suite(["2", "1-4 hours", "hard", ""]).levels()
        self.assertEqual(levels[0], "2")
        self.assertEqual(len(levels), 4)


class LevelMatchTestCase(unittest.TestCase):
    def setUp(self):
        self.suite = _suite(SWEBENCH)

    def test_a_bare_number_is_an_ordinal_into_that_order(self):
        self.assertEqual(self.suite.match_level("1"), "<15 min fix")
        self.assertEqual(self.suite.match_level("2"), "15 min - 1 hour")
        self.assertEqual(self.suite.match_level("3"), "1-4 hours")
        self.assertEqual(self.suite.match_level("4"), ">4 hours")

    def test_an_ordinal_off_the_end_matches_nothing(self):
        self.assertIsNone(self.suite.match_level("5"))
        self.assertIsNone(self.suite.match_level("0"))

    def test_an_exact_name_still_wins_over_the_ordinal(self):
        # GAIA's levels ARE "1".."3". The ordinal must never shadow them.
        gaia = _suite(["1", "2", "3"])
        self.assertEqual(gaia.match_level("1"), "1")
        self.assertEqual(gaia.match_level("3"), "3")

    def test_a_name_matches_whatever_its_case(self):
        self.assertEqual(self.suite.match_level(">4 HOURS"), ">4 hours")
        self.assertEqual(self.suite.match_level("<15 min fix"), "<15 min fix")

    def test_an_ambiguous_fragment_matches_nothing(self):
        # "15 min" is inside two of them. Picking one would be a guess
        # about which run the number belongs to.
        self.assertIsNone(self.suite.match_level("15 min"))
        self.assertIsNone(self.suite.match_level("hours"))

    def test_an_unambiguous_fragment_matches(self):
        self.assertEqual(self.suite.match_level("fix"), "<15 min fix")

    def test_no_token_is_not_a_match(self):
        self.assertIsNone(self.suite.match_level(""))
        self.assertIsNone(self.suite.match_level("   "))

    def test_every_level_resolves_to_cases(self):
        for i, _ in enumerate(self.suite.levels(), 1):
            resolved = self.suite.match_level(str(i))
            self.assertTrue(len(self.suite.sample(0, level=resolved)))


class LevelsLineTestCase(unittest.TestCase):
    def test_named_levels_are_numbered_on_screen(self):
        from simorgh.interface.benchmarkview import _levels_line

        self.assertEqual(
            _levels_line(list(_suite(SWEBENCH).levels())),
            "1=<15 min fix · 2=15 min - 1 hour · 3=1-4 hours · 4=>4 hours",
        )

    def test_numeric_levels_are_not_numbered_twice(self):
        from simorgh.interface.benchmarkview import _levels_line

        self.assertEqual(_levels_line(["1", "2", "3"]), "1, 2, 3")

    def test_no_levels_says_so(self):
        from simorgh.interface.benchmarkview import _levels_line

        self.assertEqual(_levels_line([]), "none")
        self.assertEqual(_levels_line([""]), "none")

    def test_a_started_run_echoes_the_level_it_resolved_to(self):
        from simorgh.interface.benchmarkview import started

        line = started({"suite": "swebench-verified", "cases": 20, "model": "m",
                        "run_id": "r", "level": "<15 min fix"})
        self.assertIn("level <15 min fix", line)

    def test_a_run_with_no_level_says_nothing_about_one(self):
        from simorgh.interface.benchmarkview import started

        line = started({"suite": "gaia", "cases": 5, "model": "m", "run_id": "r"})
        self.assertNotIn("level", line)


if __name__ == "__main__":
    unittest.main()
