"""Three ways the reviewer said the wrong thing, all found by an
observer attacking it on 2026-09-10.

Two of them are FALSE PASSES, which is the dangerous direction: a real
defect accepted because a sentence about it happened to contain a word
this code was matching on.
"""

from __future__ import annotations

import unittest

from simorgh.verification.checks.didanything import _DECLINED
from simorgh.verification.parsing import parse_verdict
from simorgh.verification.verdict import _refused_rather_than_failed


class ARealDefectIsNotARefusalTestCase(unittest.TestCase):
    """`combine()` passes a task whose required item answered "no" when
    the evidence says the system correctly refused. The phrases were
    loose enough to match a plain description of the defect.
    """

    def test_a_lock_is_not_a_guardian_denial(self):
        self.assertFalse(_refused_rather_than_failed(
            "The docstring was not added; the attribute is protected by a lock "
            "so the model skipped it."))

    def test_a_remark_about_the_evidence_is_not_a_refusal(self):
        self.assertFalse(_refused_rather_than_failed(
            "there is no workaround visible in the steps"))

    def test_the_word_refused_inside_a_denial_of_refusing_is_not_one(self):
        self.assertFalse(_refused_rather_than_failed(
            "It refused to add a docstring? No, it simply never edited the file."))

    def test_a_real_guardian_denial_still_passes(self):
        for evidence in ("Guardian denied the write to simorgh/guardian/rules.py (protected path)",
                         "the write to docs/SOUL.md was denied by policy",
                         "refused: 'docs/SOUL.md' is a protected path",
                         "only the creator may edit the charter"):
            self.assertTrue(_refused_rather_than_failed(evidence), evidence)


class AnHonestNoOpMustSayNothingWasWrittenTestCase(unittest.TestCase):
    """`did_anything`'s escape hatch matched the bare word "already", so
    an answer describing work it HAD done -- "which were already
    sorted" -- read as "I deliberately wrote nothing", over a step log
    containing only reads.
    """

    def _declined(self, answer: str) -> bool:
        return any(phrase in answer.lower() for phrase in _DECLINED)

    def test_an_answer_claiming_work_is_not_a_no_op(self):
        for answer in ("I added __all__ right after the imports, which were already sorted.",
                       "Added the docstring; the tests already pass."):
            self.assertFalse(self._declined(answer), answer)

    def test_a_genuine_no_op_still_says_so(self):
        for answer in ("No change was needed: the function already has a docstring.",
                       "The file already contains that constant, so I made no edit.",
                       "Guardian denied the write to a protected path.",
                       "I cannot change simorgh/guardian/rules.py: it is protected."):
            self.assertTrue(self._declined(answer), answer)


class AnEnglishNoIsNotAVerdictTestCase(unittest.TestCase):
    """`parse_verdict` read the determiner "no" as a hard NO, so an
    admission of uncertainty became a failure -- and in one case
    overruled a stated YES on the next line.
    """

    def test_an_admission_of_uncertainty_is_not_a_failure(self):
        self.assertIsNone(parse_verdict("I cannot tell from the evidence; no test output is shown."))
        self.assertIsNone(parse_verdict("there is no way to determine this"))

    def test_a_stated_yes_is_not_overruled_by_throat_clearing(self):
        self.assertEqual(parse_verdict("Hmm, no clear signal.\nYES it does address the task."), "yes")

    def test_a_real_no_is_still_a_no(self):
        for text in ("NO", "no", "no.", "no, the docstring was never added",
                     "NO -- the docstring was never added", "The answer is: no"):
            self.assertEqual(parse_verdict(text), "no", text)

    def test_unknown_is_still_neither(self):
        self.assertIsNone(parse_verdict("UNKNOWN\nno test shows it"))


if __name__ == "__main__":
    unittest.main()
