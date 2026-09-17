"""Sim is told the date rather than left to guess it.

Asked "what day is today" on 2026-09-17, Sim answered "It's Tuesday,
September 15, 2026" -- and then said it again, and again, across three
separate turns and two engines.

It was not a hallucination in the ordinary sense. NOTHING in the prompt
ever carried the date: no `strftime`, no `datetime.now`, no "today is"
anywhere in orchestration, cognition or persona. So the model guessed
once from its own training, the guess was stored as an episodic memory,
and every later answer recalled that memory and repeated it. A
fabrication that fed itself, on the question a household asks most
often -- and the consolidation guard added the same evening cannot
catch this one, because it entered memory as an ordinary turn, not as a
distillation.

The tools always knew. That same evening `remind` scheduled something
for "Thu 17 Sep at 01:18" off the same clock the session already holds.
Only the prose had never been told.

It goes in `task_rules` because that block is never compacted (04
section 4.6). A date that a long tool result can push out of the prompt
is a date Sim will invent again.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime

from simorgh.orchestration import profiles, scaffolds


class TheStampTestCase(unittest.TestCase):
    def test_it_says_the_day_the_date_and_the_time(self):
        when = datetime(2026, 9, 17, 1, 18).timestamp()
        line = scaffolds.when_line(when)
        self.assertIn("Thursday", line)
        self.assertIn("September 2026", line)
        self.assertIn("01:18", line)

    def test_no_clock_says_nothing_rather_than_something_wrong(self):
        """Silence beats Tuesday."""
        self.assertEqual(scaffolds.when_line(0.0), "")

    def test_a_clock_that_makes_no_sense_says_nothing_either(self):
        for bad in (float("inf"), float("nan"), -1e30, 1e30):
            with self.subTest(value=bad):
                self.assertEqual(scaffolds.when_line(bad), "")

    def test_it_is_local_time(self):
        """The family lives in one timezone; the date they mean is theirs."""
        when = datetime(2026, 9, 17, 23, 30)
        self.assertIn(f"{when:%H:%M}", scaffolds.when_line(when.timestamp()))


class ItReachesThePromptTestCase(unittest.TestCase):
    def test_a_spoken_turn_carries_the_date(self):
        text = scaffolds.render(profiles.for_percept("voice"), now=time.time())
        self.assertTrue(text.startswith("Right now it is"), text[:60])

    def test_a_typed_turn_carries_it_too(self):
        """Typed chat guessed the date just as badly."""
        text = scaffolds.render(profiles.for_percept("chat"), now=time.time())
        self.assertIn("Right now it is", text)

    def test_it_comes_before_the_task(self):
        """A fact about the world, not an instruction -- and first, so a
        long tool result cannot push it out of what the model sees."""
        text = scaffolds.render(profiles.for_percept("chat"), task="turn the kitchen light off",
                                now=time.time())
        self.assertLess(text.index("Right now it is"), text.index("Your task:"))

    def test_without_a_clock_the_prompt_is_unchanged(self):
        """No date is better than a wrong one, and nothing else moves."""
        text = scaffolds.render(profiles.for_percept("voice"))
        self.assertNotIn("Right now it is", text)


class TheCallerActuallyPassesItTestCase(unittest.TestCase):
    """The wired-but-unused shape is this codebase's commonest bug: a
    parameter that exists, is documented, and nobody fills."""

    def test_the_session_hands_over_its_clock(self):
        import inspect

        from simorgh.orchestration import session

        self.assertIn("now=_epoch(self._clock)", inspect.getsource(session),
                      "render() takes `now` and the session never passes it")

    def test_it_reads_either_shape_of_clock(self):
        """Interface passes `ctx.clock.now` -- the bound method -- while
        other callers pass the clock object. Assuming one shape raised
        `AttributeError: 'function' object has no attribute 'now'` in 52
        tests at once."""
        from simorgh.orchestration.session import _epoch

        class _Obj:
            def now(self):
                return 1_600_000_000.0

        self.assertEqual(_epoch(lambda: 1_600_000_000.0), 1_600_000_000.0)
        self.assertEqual(_epoch(_Obj()), 1_600_000_000.0)

    def test_an_unreadable_clock_costs_the_date_not_the_turn(self):
        from simorgh.orchestration.session import _epoch

        for bad in (None, "tuesday", object(), 0):
            with self.subTest(clock=bad):
                self.assertEqual(_epoch(bad), 0.0)


if __name__ == "__main__":
    unittest.main()
