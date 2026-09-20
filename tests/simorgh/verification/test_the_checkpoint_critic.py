"""Stage 7 item 6: a long task does not fail by answering wrongly -- it
wanders, and nothing notices until the budget is gone. The critic scores
the trajectory against the acceptance criteria at every progress note."""

from __future__ import annotations

import unittest

from simorgh.verification.checkpoint import parse, prompt_for


class TheVerdict(unittest.TestCase):
    def test_it_reads_the_four_verdicts(self):
        for verdict in ("on_track", "drifting", "blocked", "insufficient_evidence"):
            self.assertEqual(parse('{"verdict": "%s"}' % verdict)["verdict"], verdict)

    def test_it_keeps_what_is_unmet_and_what_to_do_next(self):
        answer = parse('{"verdict": "drifting", "unmet": ["the tests still fail", "nothing committed"],'
                       ' "next": "run the failing test alone", "why": "it keeps re-reading the same file"}')
        self.assertEqual(answer["unmet"], ["the tests still fail", "nothing committed"])
        self.assertEqual(answer["next"], "run the failing test alone")
        self.assertIn("re-reading", answer["why"])

    def test_prose_is_not_a_verdict(self):
        """A critic whose reply cannot be read has judged nothing, and
        reading prose as approval is how a checker becomes a stamp."""
        for text in ("Looks good to me!", "", "{oh dear", '{"verdict": "fine"}'):
            with self.subTest(text=text):
                self.assertEqual(parse(text)["verdict"], "insufficient_evidence")

    def test_the_prompt_carries_the_criteria_and_forbids_inventing_progress(self):
        text = prompt_for(goal="add a docstring", acceptance=["the file has one", "the suite passes"],
                          trajectory="read the file twice")
        self.assertIn("- the file has one", text)
        self.assertIn("read the file twice", text)
        self.assertIn("do not invent progress", text)

    def test_no_criteria_still_judges_against_the_goal(self):
        self.assertIn("judge against the goal", prompt_for(goal="g", acceptance=[], trajectory="t"))


if __name__ == "__main__":
    unittest.main()
