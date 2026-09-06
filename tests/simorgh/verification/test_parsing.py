"""`parse_verdict` (milestone-92, docs/EVOLUTION.md): a non-answer must
scan as `None`, never silently as "no"."""

import unittest

from simorgh.verification.parsing import parse_verdict


class TestParseVerdict(unittest.TestCase):
    def test_yes_first_word(self):
        self.assertEqual(parse_verdict("YES, this looks right."), "yes")

    def test_no_first_word(self):
        self.assertEqual(parse_verdict("NO -- it's missing the empty-list case."), "no")

    def test_yes_with_punctuation_and_case(self):
        self.assertEqual(parse_verdict("yes!\nlooks correct to me."), "yes")

    def test_verdict_after_narration_is_honored(self):
        text = "I'll check the actual file that was modified first...\nOkay, reviewed it. YES, it addresses the task."
        self.assertEqual(parse_verdict(text), "yes")

    def test_pure_narration_is_none_not_no(self):
        text = "I'll check the actual file that was modified before answering."
        self.assertIsNone(parse_verdict(text))

    def test_empty_text_is_none(self):
        self.assertIsNone(parse_verdict(""))

    def test_first_standalone_token_wins_when_both_appear(self):
        # "NO" inside "KNOB" or similar must not match -- only a standalone word.
        self.assertEqual(parse_verdict("KNOBS aside, YES it handles this."), "yes")


if __name__ == "__main__":
    unittest.main()
