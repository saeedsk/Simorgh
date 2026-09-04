import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.discovery import discover_improvements
from src.orchestrator.reflection import Outcome, OutcomeLog, ReflectionAgent
from src.orchestrator.tasks import PATCH_TASK, TaskStore


class TestDiscoverImprovements(unittest.TestCase):
    def test_no_signals_means_no_tasks(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store))

        created = discover_improvements(task_store, reflection_agent, store)

        self.assertEqual(created, [])

    def test_a_reflect_proposal_becomes_a_patch_task(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        outcome_log = OutcomeLog(store)
        for _ in range(5):
            outcome_log.record(Outcome(agent="logic", request_text="x", output="", succeeded=False))
        reflection_agent = ReflectionAgent(outcome_log, concern_threshold=0.3, min_samples=5)

        created = discover_improvements(task_store, reflection_agent, store)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].kind, PATCH_TASK)
        self.assertEqual(created[0].subject, "src/agents/logic/base.py")
        self.assertEqual(created[0].discovered_via, "reflection")

    def test_an_unrecognized_agent_is_skipped_not_crashed_on(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        outcome_log = OutcomeLog(store)
        for _ in range(5):
            outcome_log.record(
                Outcome(agent="some_future_agent", request_text="x", output="", succeeded=False)
            )
        reflection_agent = ReflectionAgent(outcome_log, concern_threshold=0.3, min_samples=5)

        created = discover_improvements(task_store, reflection_agent, store)

        self.assertEqual(created, [])

    def test_a_takeaway_becomes_a_patch_task(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        reflection_agent.reflect_on_outcome(
            Outcome(agent="logic", request_text="x", output="", succeeded=False, note="ValueError")
        )

        created = discover_improvements(task_store, reflection_agent, store)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].subject, "src/agents/logic/base.py")
        self.assertEqual(created[0].discovered_via, "scan")

    def test_does_not_create_a_duplicate_task_for_an_already_tracked_takeaway(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        reflection_agent.reflect_on_outcome(
            Outcome(agent="logic", request_text="x", output="", succeeded=False, note="ValueError")
        )

        first_pass = discover_improvements(task_store, reflection_agent, store)
        second_pass = discover_improvements(task_store, reflection_agent, store)

        self.assertEqual(len(first_pass), 1)
        self.assertEqual(second_pass, [])

    def test_does_not_recreate_a_task_that_was_already_completed(self):
        # A takeaway that was already fixed and marked DONE shouldn't
        # come back as a fresh task just because the record is still
        # sitting in the log.
        store = InMemoryStore()
        task_store = TaskStore(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        reflection_agent.reflect_on_outcome(
            Outcome(agent="logic", request_text="x", output="", succeeded=False, note="ValueError")
        )
        first_pass = discover_improvements(task_store, reflection_agent, store)
        task_store.update_status(first_pass[0].id, "done")

        second_pass = discover_improvements(task_store, reflection_agent, store)

        self.assertEqual(second_pass, [])

    def test_respects_the_limit(self):
        store = InMemoryStore()
        task_store = TaskStore(store)
        reflection_agent = ReflectionAgent(OutcomeLog(store), store=store)
        for i in range(5):
            reflection_agent.reflect_on_outcome(
                Outcome(agent="logic", request_text=f"x{i}", output="", succeeded=False, note=f"error {i}")
            )

        created = discover_improvements(task_store, reflection_agent, store, limit=2)

        self.assertEqual(len(created), 2)


if __name__ == "__main__":
    unittest.main()
