"""The unicode benchmark charts (`interface/benchmarkchart.py`).

Pure functions over the payload dicts `benchmark.history.reply` carries,
so every one of these runs without a terminal or a subsystem.
"""

from __future__ import annotations

import unittest

from simorgh.interface.benchmarkchart import bar, braille_chart, compare, history, sparkline, summary


def _run(model="glm", suite="gaia", correct=2, attempted=4, started=0.0, **extra) -> dict:
    run = {
        "run_id": "r1", "suite": suite, "suite_version": "abc123", "model": model,
        "started_at": started, "correct": correct, "attempted": attempted, "skipped": 0,
        "accuracy": correct / attempted if attempted else 0.0, "seconds": 12.0, "cost_usd": 0.0,
        "partial": False, "note": "", "by_level": {"1": [1, 2], "2": [1, 2]},
    }
    run.update(extra)
    return run


class BarTestCase(unittest.TestCase):
    def test_a_bar_is_exactly_the_width_asked_for(self):
        for fraction in (0.0, 0.01, 0.5, 0.999, 1.0):
            self.assertEqual(len(bar(fraction, 20)), 20, fraction)

    def test_a_tiny_fraction_still_shows_something(self):
        self.assertNotEqual(bar(0.02, 24).strip(), "")
        self.assertEqual(bar(0.0, 24).strip(), "")

    def test_it_is_clamped_at_both_ends(self):
        self.assertEqual(bar(5.0, 8), "█" * 8)
        self.assertEqual(bar(-5.0, 8).strip(), "")


class SparklineTestCase(unittest.TestCase):
    def test_one_cell_per_value(self):
        self.assertEqual(len(sparkline([0.0, 0.5, 1.0])), 3)

    def test_empty_is_empty(self):
        self.assertEqual(sparkline([]), "")

    def test_a_rising_series_rises(self):
        cells = sparkline([0.0, 0.5, 1.0])
        self.assertLess(ord(cells[0]), ord(cells[1]))
        self.assertLess(ord(cells[1]), ord(cells[2]))


class BrailleChartTestCase(unittest.TestCase):
    def test_the_grid_is_the_size_asked_for_and_is_braille(self):
        rows = braille_chart([("m", [0.0, 0.5, 1.0])], width=20, height=3)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(len(row) == 20 for row in rows))
        self.assertTrue(all(0x2800 <= ord(ch) <= 0x28FF for row in rows for ch in row))

    def test_a_high_series_draws_at_the_top_and_a_low_one_at_the_bottom(self):
        top = braille_chart([("m", [1.0, 1.0])], width=8, height=3)
        bottom = braille_chart([("m", [0.0, 0.0])], width=8, height=3)
        self.assertNotEqual(top[0], "⠀" * 8)
        self.assertEqual(top[2], "⠀" * 8)
        self.assertNotEqual(bottom[2], "⠀" * 8)
        self.assertEqual(bottom[0], "⠀" * 8)

    def test_a_single_point_still_draws(self):
        rows = braille_chart([("m", [1.0])], width=6, height=2)
        self.assertNotEqual("".join(rows), "⠀" * 12)

    def test_empty_input_does_not_crash(self):
        self.assertEqual(len(braille_chart([("m", [])], width=6, height=2)), 2)
        self.assertEqual(len(braille_chart([], width=6, height=2)), 2)


class SummaryTestCase(unittest.TestCase):
    def test_it_names_the_suite_the_model_and_each_level(self):
        text = summary(_run())
        self.assertIn("gaia", text)
        self.assertIn("glm", text)
        self.assertIn("Level 1", text)
        self.assertIn("2/4 correct", text)
        self.assertIn("abc123", text)

    def test_a_partial_run_says_so(self):
        self.assertIn("[partial]", summary(_run(partial=True)))

    def test_skipped_cases_are_reported(self):
        self.assertIn("3 skipped", summary(_run(skipped=3)))

    def test_a_run_with_nothing_attempted_does_not_divide_by_zero(self):
        self.assertIn("0/0", summary(_run(correct=0, attempted=0, by_level={})))


class HistoryTestCase(unittest.TestCase):
    def test_nothing_recorded_says_how_to_start(self):
        self.assertIn("benchmark run", history([]))

    def test_each_model_gets_a_row_with_its_trend(self):
        text = history([
            _run(model="glm", correct=1, started=1.0),
            _run(model="glm", correct=3, started=2.0),
            _run(model="other", correct=2, started=3.0),
        ])
        self.assertIn("glm", text)
        self.assertIn("other", text)
        self.assertIn("2 runs", text)
        self.assertIn("▲", text)

    def test_a_decline_is_marked_down(self):
        text = history([_run(correct=4, started=1.0), _run(correct=1, started=2.0)])
        self.assertIn("▼", text)

    def test_the_axis_is_labelled_at_both_ends(self):
        text = history([_run()])
        self.assertIn("100%", text)
        self.assertIn("0%", text)


class CompareTestCase(unittest.TestCase):
    def _with_cases(self, marks, **extra):
        cases = [{"case_id": f"c{i}", "correct": ok, "skipped": False,
                  "expected": "Paris", "answer": "Paris" if ok else "Berlin"}
                 for i, ok in enumerate(marks)]
        return _run(correct=sum(marks), attempted=len(marks), cases=cases, **extra)

    def test_it_names_what_broke_and_what_was_fixed(self):
        before = self._with_cases([True, True, False])
        after = self._with_cases([True, False, True])
        text = compare(before, after)
        self.assertIn("fixed   1", text)
        self.assertIn("broke   1", text)
        self.assertIn("c1", text)
        self.assertIn("Berlin", text)

    def test_no_shared_cases_is_not_a_crash(self):
        self.assertIn("0 shared cases", compare(_run(cases=[]), _run(cases=[])))

    def test_skipped_cases_are_left_out_of_the_comparison(self):
        before = _run(cases=[{"case_id": "c0", "correct": False, "skipped": True}])
        after = _run(cases=[{"case_id": "c0", "correct": True, "skipped": False}])
        self.assertIn("0 shared cases", compare(before, after))


if __name__ == "__main__":
    unittest.main()


class LongLevelNamesTestCase(unittest.TestCase):
    """BFCL's levels are words, not digits. The bars must still line up
    (watched, 2026-09-08: "Level live_parallel ███ ... Llive_parallel")."""

    def test_the_level_column_widens_to_the_longest_name(self):
        run = _run(by_level={"live_parallel": [1, 1], "parallel": [2, 2]})
        lines = [line for line in summary(run).splitlines() if "Level" in line]
        self.assertEqual(len(lines), 2)
        starts = {line.index("█") for line in lines}
        self.assertEqual(len(starts), 1, "the bars do not line up")

    def test_a_digit_level_still_renders_compactly(self):
        text = summary(_run(by_level={"1": [1, 2], "2": [1, 2]}))
        self.assertIn("Level 1 ", text)


class BlockedAnswersTestCase(unittest.TestCase):
    """A run must say when our own pipeline stopped answers, and how
    many of those were right -- otherwise "the model is wrong" and "our
    verifier is too strict" look identical (2026-09-08)."""

    def test_blocked_answers_are_counted_in_the_summary(self):
        text = summary(_run(blocked=3, blocked_but_correct=2))
        self.assertIn("3 answers our own pipeline stopped", text)
        self.assertIn("2 of them right", text)

    def test_none_blocked_says_nothing_about_it(self):
        self.assertNotIn("pipeline stopped", summary(_run()))

    def test_blocked_but_all_wrong_does_not_claim_any_were_right(self):
        text = summary(_run(blocked=2, blocked_but_correct=0))
        self.assertIn("2 answers our own pipeline stopped", text)
        self.assertNotIn("of them right", text)

    def test_one_blocked_reads_as_singular(self):
        self.assertIn("1 answer our own pipeline stopped", summary(_run(blocked=1)))
