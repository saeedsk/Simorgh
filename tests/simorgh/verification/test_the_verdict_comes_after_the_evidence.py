"""A checklist answer's verdict is read from its last line.

Bench wave, 2026-09-29: asked for the verdict word first, a reviewer
wrote "NO -- 16847.7 is less than 16850 ... actually 16847.7 rounds to
17000, so the pipeline's answer stands", and the NO failed a required
check. The prompt now asks for the evidence first and the word last."""

from __future__ import annotations

import unittest

from simorgh.verification import checklist
from simorgh.verification.parsing import parse_final_verdict


class TheVerdictComesAfterTheEvidence(unittest.TestCase):
    def test_the_prompt_asks_for_the_word_last(self):
        self.assertIn("on a line of its own at the end", checklist._ANSWER_PROMPT)  # noqa: SLF001

    def test_the_last_line_decides(self):
        self.assertEqual(parse_final_verdict("16847.7 rounds to 17000; the answer stands.\nYES"), "yes")
        self.assertEqual(parse_final_verdict("356,500 never appears in the fetched page.\n**NO**"), "no")

    def test_unknown_is_not_a_failure(self):
        self.assertIsNone(parse_final_verdict("Neither the result nor the steps show it.\nUNKNOWN"))

    def test_a_reply_in_the_old_shape_still_reads(self):
        self.assertEqual(parse_final_verdict("NO\nthe file was never written"), "no")
        self.assertEqual(parse_final_verdict("YES it does address the task."), "yes")


if __name__ == "__main__":
    unittest.main()
