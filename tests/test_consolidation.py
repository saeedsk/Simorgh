import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.consolidation import run_consolidation
from src.orchestrator.reflection import Outcome, OutcomeLog


class TestRunConsolidation(unittest.TestCase):
    def test_prunes_kind_down_to_keep_count(self):
        store = InMemoryStore()
        for i in range(10):
            store.remember("note", str(i))

        report = run_consolidation(store, keep_per_kind={"note": 3})

        self.assertEqual(report.pruned_counts["note"], 7)
        self.assertEqual(len(store.query(kind="note")), 3)

    def test_keeps_the_most_recent_records(self):
        store = InMemoryStore()
        for i in range(5):
            store.remember("note", str(i))

        run_consolidation(store, keep_per_kind={"note": 2})

        remaining = [r.content for r in store.query(kind="note")]
        self.assertEqual(remaining, ["4", "3"])

    def test_kinds_not_named_are_untouched(self):
        store = InMemoryStore()
        store.remember("interest", "rocketry")
        for i in range(5):
            store.remember("note", str(i))

        run_consolidation(store, keep_per_kind={"note": 1})

        self.assertEqual(len(store.query(kind="interest")), 1)

    def test_no_op_when_under_the_keep_count(self):
        store = InMemoryStore()
        store.remember("note", "only one")

        report = run_consolidation(store, keep_per_kind={"note": 10})

        self.assertEqual(report.pruned_counts["note"], 0)
        self.assertEqual(len(store.query(kind="note")), 1)

    def test_surfaces_reflection_proposals(self):
        store = InMemoryStore()
        log = OutcomeLog(store)
        for _ in range(10):
            log.record(
                Outcome(agent="skills", request_text="x", output="bad", succeeded=False)
            )

        report = run_consolidation(store)

        self.assertEqual(len(report.proposals), 1)
        self.assertEqual(report.proposals[0].subject, "skills")

    def test_no_pruning_when_keep_per_kind_omitted(self):
        store = InMemoryStore()
        store.remember("note", "keep me")

        report = run_consolidation(store)

        self.assertEqual(report.pruned_counts, {})
        self.assertEqual(len(store.query(kind="note")), 1)


if __name__ == "__main__":
    unittest.main()
