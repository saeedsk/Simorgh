"""One block per case: what was asked, what Sim said, what it cost.

The creator, 2026-09-20, after three gaia-l1 runs in an evening:
`benchmark show` tells you which cases failed and nothing about what
they said. A pass rate alone cannot tell a system that is working
from one that is brute-forcing, and it cannot tell you that the
answer was right and the units were wrong.
"""

import unittest

from simorgh.interface import benchmarkview

RUN = {"runs": [{
    "run_id": "dcdcc4d35f5d", "suite": "gaia-l1", "model": "zai-org/GLM-5.3-Flash",
    "attempted": 2, "correct": 1, "accuracy": 0.5, "seconds": 222.0, "cost_usd": 0.0147,
    "by_level": {"1": [1, 2]},
    "cases": [
        {"case_id": "kipchoge", "level": "1", "correct": True, "tokens": 10926,
         "cost_usd": 0.004, "seconds": 66, "steps": 7,
         "question": "how many thousand hours would it take him to run to the Moon?",
         "answer": "17", "expected": "17"},
        {"case_id": "riddle", "level": "1", "correct": False, "tokens": 84605,
         "cost_usd": 0.009, "seconds": 67, "steps": 12,
         "question": "Here's a fun riddle that I think you'll enjoy.",
         "answer": "100", "expected": "3",
         "blocked_by": "verification failed after max revisions"},
    ],
}]}


class WhatEachCaseShows(unittest.TestCase):
    def setUp(self):
        self.text = benchmarkview.cases(RUN)

    def test_the_question_as_asked(self):
        self.assertIn("thousand hours", self.text)

    def test_what_sim_answered(self):
        self.assertIn("17", self.text)
        self.assertIn("100", self.text)

    @staticmethod
    def _block(text: str, case_id: str) -> str:
        """The lines of one case's block, found by its mark line --
        the case id also appears inside a question, which is how the
        first version of this test fooled itself."""
        blocks, current = {}, None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped[:1] in ("✓", "✗", "·") and len(stripped.split()) > 1:
                current = stripped.split()[1]
                blocks[current] = []
            elif current:
                blocks[current].append(line)
        return "\n".join(blocks.get(case_id, []))

    def test_the_true_answer_only_when_it_differs(self):
        """Printing "expected 17" under "answered 17" is noise on
        every passing case."""
        failed = self._block(self.text, "riddle")
        self.assertIn("wanted  3", failed, "the failing case names what was true")
        passing = self._block(self.text, "kipchoge")
        self.assertNotIn("wanted", passing, "the passing case needs no expected line")

    def test_the_cost_of_a_right_answer(self):
        """A right answer at 5,000 tokens and one at 80,000 are
        different results."""
        self.assertIn("10,926 tokens", self.text)
        self.assertIn("84,605 tokens", self.text)

    def test_why_it_was_stopped(self):
        self.assertIn("verification failed", self.text)

    def test_the_labels_do_not_collide_with_the_pass_mark(self):
        """A tick for "passed" and a tick for "this was true" in one
        block is unreadable down the left edge, and the first version
        of this view did exactly that."""
        for line in self.text.splitlines():
            if line.strip().startswith(("ask", "got", "wanted", "stopped")):
                self.assertNotIn("✓", line, line)

    def test_the_headline_is_still_there(self):
        self.assertIn("gaia-l1", self.text)
        self.assertIn("50.0%", self.text)


class WhatItDoesWithNothing(unittest.TestCase):
    def test_an_unknown_run(self):
        self.assertEqual(benchmarkview.cases({"runs": []}), "no such run")

    def test_a_run_with_no_case_detail_still_renders(self):
        """History rebuilt from a summary carries no cases; the
        headline must survive that."""
        thin = {"runs": [{**RUN["runs"][0], "cases": []}]}
        self.assertIn("gaia-l1", benchmarkview.cases(thin))

    def test_a_case_missing_its_question(self):
        thin = {"runs": [{**RUN["runs"][0],
                          "cases": [{"case_id": "x", "level": "1", "correct": True}]}]}
        self.assertIn("x", benchmarkview.cases(thin))


if __name__ == "__main__":
    unittest.main()
