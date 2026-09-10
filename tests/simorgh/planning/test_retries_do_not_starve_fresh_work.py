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
from simorgh.planning.scheduler import select_ready


class _Task:
    def __init__(self, id_, *, origin="benchmark", attempts=0, created_at=0.0):
        self.id = id_
        self.origin = origin
        self.kind = "research"
        self.attempts = attempts
        self.created_at = created_at
        self.updated_at = created_at


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


if __name__ == "__main__":
    unittest.main()
