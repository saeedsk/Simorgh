"""What ranks first, and the two wires that were never connected.

`Task.priority` has existed on the model, been persisted by the store
and round-tripped through the ledger since the beginning, and was read
by NOTHING. Measured 2026-09-16: of 97 tasks ever created, 96 carried
the default 0, and the single task that set 5 got nothing for it.
There was no way to say "this one matters more" and be heard.

Worse, `priority_weights` listed neither `project` nor `research`, so
`.get(origin, 0)` gave both of them 0 -- below curiosity's 1. Every
child of an approved plan is created with `origin="project"`
(`service.py::_on_plan_approved`), so decomposing a goal into steps was
the very thing that sent those steps to the back of the queue. On the
day this was measured, four self-improvement project tasks sat behind
three Age of Empires clones running at weight 2.

Neither fix is new machinery. Both are wires.
"""

from __future__ import annotations

import unittest

from simorgh.planning.config import Config
from simorgh.planning.scheduler import better_ready, select_ready


class _Task:
    def __init__(self, id_, *, origin="assistant", attempts=0, created_at=0.0,
                 updated_at=None, priority=0):
        self.id = id_
        self.origin = origin
        self.kind = "patch"
        self.attempts = attempts
        self.created_at = created_at
        self.updated_at = created_at if updated_at is None else updated_at
        self.priority = priority


class _Bare:
    """A task with no `priority` attribute at all -- the shape every
    older test builds, and the reason the sort key reads it defensively."""

    def __init__(self, id_, *, origin="assistant", created_at=0.0):
        self.id = id_
        self.origin = origin
        self.kind = "patch"
        self.attempts = 0
        self.created_at = created_at
        self.updated_at = created_at


class _Store:
    def __init__(self, tasks):
        self._tasks = list(tasks)
        self.index = type("I", (), {"tasks": {t.id: t for t in tasks}})()

    def ready(self, limit=1000):
        return list(self._tasks)


class WeightsTestCase(unittest.TestCase):
    weights = Config().priority_weights

    def test_a_decomposed_child_no_longer_ranks_below_a_game(self):
        """The inversion: `project` was absent from the dict entirely."""
        self.assertGreater(self.weights.get("project", 0), self.weights.get("assistant", 0))

    def test_research_is_not_zero_either(self):
        self.assertGreater(self.weights.get("research", 0), 0)

    def test_every_origin_the_model_allows_has_a_weight(self):
        """`.get(origin, 0)` hides a missing entry as "least important",
        which is how this went unnoticed."""
        from simorgh.planning.model import ORIGINS

        missing = [o for o in ORIGINS if o not in self.weights and o != "planner"]
        self.assertEqual(missing, [], f"no weight for {missing}")


class PriorityIsReadTestCase(unittest.TestCase):
    weights = Config().priority_weights

    def _order(self, tasks):
        return [t.id for t in select_ready(_Store(tasks), priority_weights=self.weights,
                                           limit=len(tasks))]

    def test_priority_orders_work_of_the_same_origin(self):
        """The common case: everything waiting, nothing attempted yet."""
        order = self._order([_Task("game", created_at=1.0, priority=0),
                             _Task("loop", created_at=2.0, priority=5)])
        self.assertEqual(order, ["loop", "game"], "priority was ignored")

    def test_a_task_that_says_nothing_keeps_the_old_order(self):
        order = self._order([_Task("older", created_at=1.0), _Task("newer", created_at=2.0)])
        self.assertEqual(order, ["older", "newer"])

    def test_priority_does_not_defeat_the_starvation_rule(self):
        """The rule this key was rewritten for, 2026-09-10: work never
        tried goes before a retry, however much the retry wants it."""
        order = self._order([_Task("retry", attempts=9, priority=9, created_at=1.0),
                             _Task("fresh", attempts=0, priority=0, created_at=2.0)])
        self.assertEqual(order, ["fresh", "retry"])

    def test_origin_still_outranks_priority(self):
        order = self._order([_Task("mine", origin="curiosity", priority=9, created_at=1.0),
                             _Task("theirs", origin="human", priority=0, created_at=2.0)])
        self.assertEqual(order, ["theirs", "mine"])

    def test_a_task_object_without_the_field_is_not_a_crash(self):
        """Every older test builds one of these."""
        order = self._order([_Bare("a", created_at=1.0), _Bare("b", created_at=2.0)])
        self.assertEqual(order, ["a", "b"])


class PreemptionAgreesTestCase(unittest.TestCase):
    weights = Config().priority_weights

    def _better(self, tasks, held):
        return better_ready(_Store(tasks), held, priority_weights=self.weights)

    def test_a_higher_priority_task_of_equal_weight_is_taken_instead(self):
        """`select_ready` and `better_ready` must not disagree about
        what is next, or the claim undoes the ordering."""
        best = self._better([_Task("held", created_at=1.0, priority=0),
                             _Task("urgent", created_at=2.0, priority=5)], "held")
        self.assertIsNotNone(best)
        self.assertEqual(best.id, "urgent")

    def test_equal_weight_and_equal_priority_keeps_the_offer_order(self):
        """The 2026-09-10 rule: among equals the scheduler's order stands."""
        self.assertIsNone(self._better([_Task("held", created_at=1.0),
                                        _Task("other", created_at=2.0)], "held"))

    def test_a_lower_priority_task_does_not_preempt(self):
        self.assertIsNone(self._better([_Task("held", created_at=1.0, priority=5),
                                        _Task("meh", created_at=2.0, priority=0)], "held"))


if __name__ == "__main__":
    unittest.main()
