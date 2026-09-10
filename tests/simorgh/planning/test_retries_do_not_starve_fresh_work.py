"""A retried task must not eat the queue, and a retry that changes
nothing must stop.

Measured on a real GAIA run, 2026-09-10 (42 questions, 103 minutes):

- Two tasks were re-claimed nine and ten times. Retries took **68% of
  the run's steps and 71% of its wall clock** -- re-answering questions
  the system had already answered.
- Four questions were never started at all. They sat on the queue for
  their full 600s timeout and scored zero without ever being read,
  because `select_ready` ordered by age and a blocked task is always
  older than the work still waiting behind it.
- Of the 18 tasks that were retried, 8 came back with an identical
  answer, which the same reviewer then rejected for the same reason.
- Retrying past three attempts turned a wrong answer into a right one
  exactly once, in six tasks. The four starved questions cost more.

Both fixes are ordering and stopping rules, not new machinery.
"""

from __future__ import annotations

import unittest

from simorgh.planning.config import Config
from simorgh.planning.scheduler import STARVATION_GRACE_SECONDS, select_ready


class _Task:
    def __init__(self, id_, *, origin="benchmark", attempts=0, created_at=0.0, updated_at=None):
        self.id = id_
        self.origin = origin
        self.kind = "research"
        self.attempts = attempts
        self.created_at = created_at
        self.updated_at = created_at if updated_at is None else updated_at


class _Store:
    def __init__(self, tasks):
        self._tasks = tasks

    def ready(self, limit=1000):
        return list(self._tasks)


class FairDispatchTestCase(unittest.TestCase):
    weights = Config().priority_weights

    def _order(self, tasks):
        return [t.id for t in select_ready(_Store(tasks), priority_weights=self.weights,
                                           limit=len(tasks))]

    def test_a_question_never_asked_goes_before_a_ninth_retry(self):
        """The live shape: one old task on its ninth attempt, four fresh
        questions created after it, one worker."""
        retried = _Task("retried", attempts=9, created_at=1.0)
        fresh = [_Task(f"fresh{i}", created_at=10.0 + i) for i in range(4)]
        order = self._order([retried, *fresh])
        self.assertEqual(order[0], "fresh0")
        self.assertEqual(order[-1], "retried")

    def test_the_retry_still_runs_once_the_new_work_has_had_a_turn(self):
        """Fairness, not starvation in the other direction."""
        order = self._order([_Task("retried", attempts=2, created_at=1.0),
                             _Task("fresh", created_at=9.0)])
        self.assertEqual(order, ["fresh", "retried"])

    def test_among_equals_the_oldest_still_goes_first(self):
        order = self._order([_Task("newer", created_at=20.0), _Task("older", created_at=5.0)])
        self.assertEqual(order, ["older", "newer"])

    def test_a_humans_task_still_outranks_everything(self):
        """Priority is still the first key: attempts only break ties
        inside one origin, or a retry could jump a person's request."""
        order = self._order([_Task("bench", origin="benchmark", attempts=0, created_at=1.0),
                             _Task("human", origin="human", attempts=5, created_at=99.0)])
        self.assertEqual(order[0], "human")


class AndFreshWorkDoesNotStarveTheRetryForeverTestCase(unittest.TestCase):
    """The open question the fix above left behind, measured 2026-09-10
    with `select_ready` itself: one worker, a retry on the queue at t=0,
    twenty tasks already queued, fresh work arriving at a given rate per
    service slot.

        arrival probability   slots the retry waited
        0.50                  34-50
        0.80                  68-102
        0.95                  333-449
        1.00 (saturated)      NEVER, in 5,000 slots, every seed
        2.00                  NEVER

    A slot is one real task, so the 0.95 row is already hours and the
    saturated rows are exactly as bad as they sound: the retry is never
    dispatched again, at all, for as long as the load lasts.

    A retry that has waited longer than `STARVATION_GRACE_SECONDS` stops
    being sorted as a retry. It does not jump the queue -- it competes
    on age like everything else. Re-running the same simulation with
    that rule: 30 slots (the grace itself) at every arrival rate,
    including 2x saturation.

    The grace is deliberately far longer than the window the
    fewest-attempts rule protects: the GAIA run's retries were
    re-claimed within seconds of being requeued, so nothing that fix
    prevents happens inside half an hour.
    """

    weights = Config().priority_weights

    def _order(self, tasks, *, now):
        return [t.id for t in select_ready(_Store(tasks), priority_weights=self.weights,
                                           limit=len(tasks), now=now)]

    def test_a_retry_held_past_the_grace_stops_being_sent_to_the_back(self):
        stale = _Task("retried", attempts=9, created_at=0.0, updated_at=0.0)
        fresh = [_Task(f"fresh{i}", created_at=100.0 + i) for i in range(4)]
        order = self._order([stale, *fresh], now=STARVATION_GRACE_SECONDS + 1.0)
        self.assertEqual(order[0], "retried")

    def test_inside_the_grace_the_retry_still_waits_its_turn(self):
        """The GAIA fix is untouched for the window it was written for."""
        stale = _Task("retried", attempts=9, created_at=0.0, updated_at=0.0)
        fresh = [_Task(f"fresh{i}", created_at=100.0 + i) for i in range(4)]
        order = self._order([stale, *fresh], now=STARVATION_GRACE_SECONDS - 1.0)
        self.assertEqual(order[0], "fresh0")
        self.assertEqual(order[-1], "retried")

    def test_an_aged_retry_still_does_not_outrank_a_human(self):
        """Priority is still the first key; aging only touches the
        attempts tiebreak inside one origin."""
        stale = _Task("retried", attempts=9, created_at=0.0, updated_at=0.0)
        human = _Task("human", origin="human", attempts=0, created_at=999.0)
        order = self._order([stale, human], now=STARVATION_GRACE_SECONDS + 1.0)
        self.assertEqual(order[0], "human")

    def test_a_caller_with_no_clock_gets_exactly_the_old_ordering(self):
        stale = _Task("retried", attempts=9, created_at=0.0, updated_at=0.0)
        fresh = _Task("fresh", created_at=10_000.0)
        self.assertEqual(
            [t.id for t in select_ready(_Store([stale, fresh]), priority_weights=self.weights, limit=2)],
            ["fresh", "retried"])


if __name__ == "__main__":
    unittest.main()
