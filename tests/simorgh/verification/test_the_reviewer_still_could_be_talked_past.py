"""The second pass at "a reviewer cannot be talked past" (9fbdab1,
39efa1f) left four ways through, all found by re-attacking those two
commits on 2026-09-10 and all reproduced here before anything changed.

Each one is the SAME failure the commit it follows says it closed, in
the spelling a model actually writes.
"""

from __future__ import annotations

import asyncio
import unittest


class AVerdictInSentenceCaseTestCase(unittest.TestCase):
    """`parse_verdict` compared the MATCHED TEXT to the lowercase
    literal `"no"`, so the determiner guard only ever ran on an
    all-lowercase `no`.

    An ordinary sentence capitalises its first word, and a reviewer's
    prose is ordinary sentences: `"The diff shows No changes to the
    file."` took the guard's `word == "no"` branch never, and was read
    as a hard NO -- overruling a shouted `YES` on the next line, which
    is precisely the case 9fbdab1's own docstring cites as the reason
    the guard exists.
    """

    def test_a_capitalised_determiner_does_not_overrule_a_stated_yes(self):
        from simorgh.verification.parsing import parse_verdict

        self.assertEqual(
            parse_verdict("The diff shows No changes to the file.\nYES the docstring exists"),
            "yes")

    def test_a_capitalised_determiner_mid_line_is_not_a_verdict(self):
        from simorgh.verification.parsing import parse_verdict

        self.assertIsNone(parse_verdict("There is No way to tell from these steps."))

    def test_a_shouted_no_is_still_a_verdict(self):
        from simorgh.verification.parsing import parse_verdict

        self.assertEqual(parse_verdict("NO the file was never written"), "no")
        self.assertEqual(parse_verdict("The answer is NO"), "no")

    def test_an_ordinary_no_answer_is_still_a_verdict(self):
        """`No, ...` and a bare `No` are answers, not determiners -- the
        determiner needs a bare word after it."""
        from simorgh.verification.parsing import parse_verdict

        self.assertEqual(parse_verdict("No, it does not address the task"), "no")
        self.assertEqual(parse_verdict("No."), "no")
        self.assertEqual(parse_verdict("no"), "no")


class ATagSpellingStillMisreadTestCase(unittest.TestCase):
    """39efa1f widened the `[optional]` tag to "every spelling" and
    stopped one character short of the one a model writes most: the em
    dash. `optional - x` and `optional -- x` were recognised, `optional
    — x` was not, so the item silently became REQUIRED again. A tag
    followed by a full stop went the same way, and the tag's own
    punctuation was left inside the question.
    """

    def test_an_em_dash_is_a_delimiter(self):
        from simorgh.verification.checklist import split_tag

        self.assertEqual(split_tag("optional — is there a test?"), ("is there a test?", False))
        self.assertEqual(split_tag("Optional — is there a test?"), ("is there a test?", False))

    def test_a_trailing_tag_followed_by_a_full_stop(self):
        from simorgh.verification.checklist import split_tag

        self.assertEqual(split_tag("is there a test? [optional]."), ("is there a test?", False))
        self.assertEqual(split_tag("is there a test? (optional)."), ("is there a test?", False))

    def test_the_tags_own_punctuation_leaves_with_it(self):
        from simorgh.verification.checklist import split_tag

        self.assertEqual(split_tag("optional -- is there a test?"), ("is there a test?", False))
        self.assertEqual(split_tag("[optional]: is there a test?"), ("is there a test?", False))

    def test_a_bare_leading_word_is_still_part_of_the_question(self):
        from simorgh.verification.checklist import split_tag

        self.assertEqual(split_tag("Optional arguments documented?"),
                         ("Optional arguments documented?", True))


class AnOrdinaryToolRefusalIsNotAProtectionTestCase(unittest.TestCase):
    """9fbdab1 replaced the loose `refused to` with `refused:` and made
    the hole bigger, not smaller.

    `refused:` is `pathsafety.py`'s prefix for EVERY argument it
    dislikes -- `refused: 'foo(' is not a valid regex`, `refused: 'x' is
    not a file`, `refused: path is 5000 chars`. None of those is the
    system protecting anything; they are a tool saying the arguments
    were wrong. Guardian's own denial reaches a step as `denied: ...`
    (`orchestration/session.py:887`), which is the marker that names a
    refuser.
    """

    def test_a_bad_argument_is_not_evidence_of_a_refusal(self):
        from simorgh.verification.verdict import _refused_rather_than_failed

        self.assertFalse(_refused_rather_than_failed(
            "search_code answered refused: 'foo(' is not a valid regex, so it gave up"))
        self.assertFalse(_refused_rather_than_failed(
            "read_file said refused: 'notes.md' is not a file"))

    def test_a_real_denial_and_a_real_protection_still_pass(self):
        from simorgh.verification.verdict import _refused_rather_than_failed

        self.assertTrue(_refused_rather_than_failed(
            "denied: sim.sh is protected -- only the creator may change it"))
        self.assertTrue(_refused_rather_than_failed("Guardian denied the write"))
        self.assertTrue(_refused_rather_than_failed(
            "refused: 'workspace/notes.txt' looks like a credentials path"))
        self.assertTrue(_refused_rather_than_failed(
            "refused: '../secrets' is outside the readable areas"))

    def test_a_required_no_on_a_bad_argument_still_fails_the_task(self):
        from simorgh.verification.checklist import AnsweredItem
        from simorgh.verification.config import VerificationConfig
        from simorgh.verification.trajectory import TrajectoryMetrics
        from simorgh.verification.verdict import combine

        answered = [AnsweredItem(
            question="was the docstring added?", answer="no",
            evidence="the model called search_code and got refused: 'def (' is not a valid regex",
            required=True)]
        result = combine([], answered, TrajectoryMetrics(available=True), VerificationConfig())
        self.assertEqual(result.verdict, "fail")


class ABareWordIsNotAnAssertionThatNothingWasWrittenTestCase(unittest.TestCase):
    """`did_anything`'s escape hatch had `already` and `cannot` tightened
    into forms that are about the change -- and left `denied`,
    `protected`, `refused` and `declined` as bare substrings.

    `protected` is ordinary code-review prose. An answer describing work
    it did not do -- over a step log holding nothing but `read_file` --
    passed on the word alone, which is the exact bug 9fbdab1 says it
    closed for `already`.
    """

    def _run(self, answer: str):
        from simorgh.verification.api import CheckContext, VerifyRequest
        from simorgh.verification.checks.didanything import DidAnythingCheck
        from simorgh.verification.config import VerificationConfig

        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={
                "kind": "patch", "description": "add a docstring", "result": answer,
                "steps": [{"tool": t, "ok": True, "phase": "act", "summary": ""}
                          for t in ("read_file", "search_code")],
            },
        )
        check = DidAnythingCheck()
        self.assertTrue(check.applies(req))
        ctx = CheckContext(act=None, think=None, review=None, clock=None,
                           config=VerificationConfig())
        return asyncio.run(check.run(req, ctx))

    def test_prose_containing_protected_does_not_excuse_a_no_op(self):
        self.assertEqual(
            self._run("I added a guard clause so the field is protected from mutation.").status,
            "failed")

    def test_prose_containing_refused_does_not_excuse_a_no_op(self):
        self.assertEqual(
            self._run("The parser refused the malformed input, so I added a test for it.").status,
            "failed")

    def test_a_real_denial_still_excuses_it(self):
        for answer in ("Guardian denied the write, so no change was made.",
                       "denied: sim.sh is protected -- only the creator may change it",
                       "the file is a protected path; I declined to edit it"):
            self.assertEqual(self._run(answer).status, "passed", answer)

    def test_an_honest_no_op_still_passes(self):
        for answer in ("no changes were needed -- the imports were already sorted",
                       "the module already has __all__",
                       "nothing to change"):
            self.assertEqual(self._run(answer).status, "passed", answer)


if __name__ == "__main__":
    unittest.main()
