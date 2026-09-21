"""A retry that reaches the same conclusion is not a new attempt.

Planning already had a no-progress guard, measured on a GAIA run in
2026-09-10: retrying past the first repeated answer never once turned
a wrong answer into a right one, and the retries took 68% of that
run's steps.

It compared the whole summary. On the creator's GAIA run of
2026-09-20 one case answered `FINAL ANSWER: 2` six times, each above
a completely different paragraph of reasoning -- "the stray rerun was
the old montage-level scan...", "Full-resolution scan of f_0083
confirms...", "The evidence across this attempt chain is
consistent..." -- so six identical answers looked like six different
ones, the guard never fired, and the task retried until the
ten-minute case timeout killed it.

The cost was not only time. One of those attempts found a third
species and answered 3; the loop talked it back down to 2.
"""

import unittest

from simorgh.contracts.text.answer import final_answer


class TheAnswerOutOfTheProse(unittest.TestCase):
    def test_the_same_answer_under_different_reasoning(self):
        """The six summaries from that case, shortened. They must all
        reduce to the same thing."""
        attempts = [
            "The stray rerun was the old montage-level scan with the small 3b model.\nFINAL ANSWER: 2",
            "Full-resolution scan of f_0083 confirms the co-occurrence.\nFINAL ANSWER: 2",
            "The evidence across this attempt chain is consistent.\nFINAL ANSWER: 2",
            "The last open gap is now closed.\nFINAL ANSWER: 2",
        ]
        self.assertEqual({final_answer(a) for a in attempts}, {"2"})

    def test_a_different_answer_is_still_different(self):
        """The attempt that found the Adélie and said 3 must not be
        collapsed into the ones that said 2."""
        self.assertNotEqual(final_answer("...adult Adélie Penguin...\nFINAL ANSWER: 3"),
                            final_answer("...only two species...\nFINAL ANSWER: 2"))

    def test_the_last_marker_wins(self):
        """A model that restates the format instruction before
        answering must not have its own example read as the answer."""
        self.assertEqual(final_answer("Reply as FINAL ANSWER: <answer>\nFINAL ANSWER: 17"), "17")

    def test_no_marker_falls_back_to_the_last_line(self):
        self.assertEqual(final_answer("some working\n0.1777"), "0.1777")

    def test_nothing_is_nothing(self):
        self.assertEqual(final_answer(""), "")
        self.assertEqual(final_answer("   \n\n  "), "")


class TheGuardUsesIt(unittest.IsolatedAsyncioTestCase):
    def _service(self):
        from simorgh.planning.service import Service

        service = Service.__new__(Service)
        service._last_blocked_answer = {}
        return service

    @staticmethod
    def _task(task_id="t1"):
        class _T:
            id = task_id
            attempts = 1

        return _T()

    def test_two_attempts_with_the_same_answer_stop(self):
        from simorgh.planning.service import VERIFICATION_REASON

        service, task = self._service(), self._task()
        first = "One paragraph of reasoning.\nFINAL ANSWER: 2"
        second = "A completely different paragraph.\nFINAL ANSWER: 2"
        self.assertFalse(service._made_no_progress(task, first, VERIFICATION_REASON),
                         "the first is not a repeat of anything")
        self.assertTrue(service._made_no_progress(task, second, VERIFICATION_REASON),
                        "the same answer twice is the loop this stops")

    def test_a_changed_answer_keeps_going(self):
        from simorgh.planning.service import VERIFICATION_REASON

        service, task = self._service(), self._task()
        service._made_no_progress(task, "x\nFINAL ANSWER: 2", VERIFICATION_REASON)
        self.assertFalse(service._made_no_progress(task, "y\nFINAL ANSWER: 3", VERIFICATION_REASON),
                         "a different conclusion is progress and deserves its attempt")

    def test_only_a_block_that_judged_the_answer_counts(self):
        """A task blocked for running out of steps carries its answer
        forward unchanged by design; counting that as no progress
        killed a correct patch task on 2026-09-10."""
        service, task = self._service(), self._task()
        service._made_no_progress(task, "x\nFINAL ANSWER: 2", "ran out of steps")
        self.assertFalse(service._made_no_progress(task, "x\nFINAL ANSWER: 2", "ran out of steps"))

    def test_tasks_do_not_bleed_into_each_other(self):
        from simorgh.planning.service import VERIFICATION_REASON

        service = self._service()
        service._made_no_progress(self._task("a"), "x\nFINAL ANSWER: 2", VERIFICATION_REASON)
        self.assertFalse(service._made_no_progress(self._task("b"), "y\nFINAL ANSWER: 2", VERIFICATION_REASON))


if __name__ == "__main__":
    unittest.main()
