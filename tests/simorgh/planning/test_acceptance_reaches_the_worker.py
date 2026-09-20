"""Stage 7 items 3, 4 and 6 meeting: what "done" means is written by the
planner, survives as ordinary text through a store that knows nothing
about plan nodes, and reaches the session the critic scores."""

from __future__ import annotations

import unittest

from simorgh.planning.model import AVAILABLE, COMPLETED, IN_PROGRESS, PENDING, WAITING, Task
from simorgh.planning.rollup import project_status
from simorgh.planning.service import _acceptance_of, _task_payload


def _child(status: str, **kw) -> Task:
    return Task(id=kw.pop("id", "c"), kind="patch", description="d", status=status, **kw)


class Acceptance(unittest.TestCase):
    def test_it_round_trips_through_the_note(self):
        why = "done when: the file has a docstring; the suite passes"
        self.assertEqual(_acceptance_of(why), ["the file has a docstring", "the suite passes"])
        self.assertEqual(_acceptance_of("from project decomposition"), [])
        self.assertEqual(_acceptance_of(""), [])

    def test_the_claim_reply_carries_it(self):
        task = _child(AVAILABLE, note="done when: the bins go out on the right day")
        self.assertEqual(_task_payload(task)["acceptance"], ["the bins go out on the right day"])


class AWaitingChild(unittest.TestCase):
    """Stage 7 item 5 met item 4: a waiting child is going fine and is
    simply not due yet, so its project is in progress -- not pending, and
    certainly not failed."""

    def test_a_project_with_a_waiting_child_is_in_progress(self):
        self.assertEqual(project_status([_child(COMPLETED, id="a"), _child(WAITING, id="b")]), IN_PROGRESS)
        self.assertEqual(project_status([_child(WAITING, id="a")]), IN_PROGRESS)

    def test_a_project_completes_only_when_every_child_did(self):
        self.assertEqual(project_status([_child(COMPLETED, id="a"), _child(COMPLETED, id="b")]), COMPLETED)
        self.assertEqual(project_status([]), PENDING)


if __name__ == "__main__":
    unittest.main()
