import unittest

from simorgh.planning import dag
from simorgh.planning.model import (
    AVAILABLE,
    BLOCKED,
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    PENDING,
    Task,
    is_legal_transition,
)
from simorgh.planning.rollup import is_stalled, project_status


def _task(tid, status, **kw):
    return Task(id=tid, kind="patch", description="d", status=status, **kw)


class TestTransitions(unittest.TestCase):
    def test_pending_to_available_is_legal(self):
        self.assertTrue(is_legal_transition(PENDING, AVAILABLE))

    def test_completed_is_terminal(self):
        self.assertFalse(is_legal_transition(COMPLETED, AVAILABLE))
        self.assertFalse(is_legal_transition(COMPLETED, FAILED))

    def test_same_status_is_a_legal_noop(self):
        self.assertTrue(is_legal_transition(IN_PROGRESS, IN_PROGRESS))

    def test_available_cannot_jump_to_completed(self):
        self.assertFalse(is_legal_transition(AVAILABLE, COMPLETED))


class TestDagValidate(unittest.TestCase):
    def test_unknown_dependency_raises(self):
        with self.assertRaises(dag.UnknownDependencyError):
            dag.validate("a", ["ghost"], {})

    def test_self_dependency_is_a_cycle(self):
        with self.assertRaises(dag.CycleError):
            dag.validate("a", ["a"], {"a": _task("a", PENDING)})

    def test_three_cycle_is_rejected(self):
        known = {"a": _task("a", PENDING, depends_on=("b",)), "b": _task("b", PENDING, depends_on=("c",))}
        with self.assertRaises(dag.CycleError):
            dag.validate("c", ["a"], known)

    def test_diamond_is_valid(self):
        known = {
            "a": _task("a", COMPLETED),
            "b": _task("b", PENDING, depends_on=("a",)),
            "c": _task("c", PENDING, depends_on=("a",)),
        }
        dag.validate("d", ["b", "c"], known)  # no raise

    def test_valid_chain_does_not_raise(self):
        known = {"a": _task("a", PENDING)}
        dag.validate("b", ["a"], known)  # no raise


class TestDagReadiness(unittest.TestCase):
    def test_ready_when_all_deps_completed(self):
        known = {"a": _task("a", COMPLETED), "b": _task("b", COMPLETED)}
        t = _task("c", PENDING, depends_on=("a", "b"))
        self.assertTrue(dag.is_ready(t, known))

    def test_not_ready_when_one_dep_incomplete(self):
        known = {"a": _task("a", COMPLETED), "b": _task("b", IN_PROGRESS)}
        t = _task("c", PENDING, depends_on=("a", "b"))
        self.assertFalse(dag.is_ready(t, known))

    def test_no_deps_is_ready(self):
        self.assertTrue(dag.is_ready(_task("a", PENDING), {}))

    def test_unknown_dep_is_not_ready_not_a_crash(self):
        t = _task("c", PENDING, depends_on=("ghost",))
        self.assertFalse(dag.is_ready(t, {}))

    def test_dependents_of(self):
        known = {
            "a": _task("a", COMPLETED),
            "b": _task("b", PENDING, depends_on=("a",)),
            "c": _task("c", PENDING, depends_on=("a",)),
            "d": _task("d", PENDING),
        }
        self.assertEqual(sorted(dag.dependents_of("a", known)), ["b", "c"])


class TestProjectStatus(unittest.TestCase):
    def test_no_children_is_pending(self):
        self.assertEqual(project_status([]), PENDING)

    def test_all_done_children_is_done(self):
        self.assertEqual(project_status([_task("a", COMPLETED), _task("b", COMPLETED)]), COMPLETED)

    def test_all_terminal_but_one_failed_is_failed(self):
        self.assertEqual(project_status([_task("a", COMPLETED), _task("b", FAILED)]), FAILED)

    def test_any_in_progress_is_in_progress(self):
        self.assertEqual(project_status([_task("a", COMPLETED), _task("b", IN_PROGRESS)]), IN_PROGRESS)

    def test_some_done_some_pending_is_in_progress(self):
        self.assertEqual(project_status([_task("a", COMPLETED), _task("b", PENDING)]), IN_PROGRESS)

    def test_blocked_with_no_progress_is_blocked(self):
        self.assertEqual(project_status([_task("a", BLOCKED), _task("b", PENDING)]), BLOCKED)

    def test_all_pending_is_pending(self):
        self.assertEqual(project_status([_task("a", PENDING), _task("b", PENDING)]), PENDING)


class TestStalled(unittest.TestCase):
    def test_blocked_past_threshold_is_stalled(self):
        t = _task("a", BLOCKED, updated_at=0.0)
        self.assertTrue(is_stalled([t], now=2000.0, stalled_after_seconds=1800.0))

    def test_blocked_within_threshold_is_not_stalled(self):
        t = _task("a", BLOCKED, updated_at=1000.0)
        self.assertFalse(is_stalled([t], now=1500.0, stalled_after_seconds=1800.0))

    def test_in_progress_with_no_lease_is_not_stalled(self):
        t = _task("a", IN_PROGRESS, updated_at=0.0)
        self.assertFalse(is_stalled([t], now=100000.0, stalled_after_seconds=1800.0))


if __name__ == "__main__":
    unittest.main()
