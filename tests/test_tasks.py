import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.tasks import (
    BLOCKED,
    DONE,
    IN_PROGRESS,
    PATCH_TASK,
    PENDING,
    SKILL_TASK,
    TaskStore,
)


class TestTaskStore(unittest.TestCase):
    def test_add_creates_a_pending_task(self):
        store = TaskStore(InMemoryStore())

        task = store.add("build a rocketry skill", SKILL_TASK)

        self.assertEqual(task.status, PENDING)
        self.assertEqual(task.description, "build a rocketry skill")
        self.assertEqual(task.kind, SKILL_TASK)
        self.assertEqual(task.attempts, 0)

    def test_get_returns_none_for_unknown_id(self):
        store = TaskStore(InMemoryStore())
        self.assertIsNone(store.get("nonexistent"))

    def test_get_returns_the_created_task(self):
        store = TaskStore(InMemoryStore())
        created = store.add("fix something", PATCH_TASK, subject="src/x.py")

        fetched = store.get(created.id)

        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.subject, "src/x.py")

    def test_update_status_changes_current_state(self):
        store = TaskStore(InMemoryStore())
        task = store.add("do a thing", SKILL_TASK)

        store.update_status(task.id, IN_PROGRESS)

        self.assertEqual(store.get(task.id).status, IN_PROGRESS)

    def test_update_status_with_attempt_increments_attempts(self):
        store = TaskStore(InMemoryStore())
        task = store.add("do a thing", SKILL_TASK)

        store.update_status(task.id, IN_PROGRESS, attempt=True)
        store.update_status(task.id, BLOCKED, note="denied: eval", attempt=True)

        fetched = store.get(task.id)
        self.assertEqual(fetched.attempts, 2)
        self.assertEqual(fetched.note, "denied: eval")

    def test_status_change_without_attempt_does_not_increment(self):
        store = TaskStore(InMemoryStore())
        task = store.add("do a thing", SKILL_TASK)

        store.update_status(task.id, IN_PROGRESS, attempt=False)

        self.assertEqual(store.get(task.id).attempts, 0)

    def test_pending_only_returns_pending_tasks(self):
        store = TaskStore(InMemoryStore())
        t1 = store.add("task one", SKILL_TASK)
        t2 = store.add("task two", SKILL_TASK)
        store.update_status(t2.id, DONE)

        pending = store.pending()

        self.assertEqual([t.id for t in pending], [t1.id])

    def test_unfinished_includes_pending_in_progress_and_blocked(self):
        store = TaskStore(InMemoryStore())
        t1 = store.add("pending", SKILL_TASK)
        t2 = store.add("in progress", SKILL_TASK)
        store.update_status(t2.id, IN_PROGRESS)
        t3 = store.add("blocked", SKILL_TASK)
        store.update_status(t3.id, BLOCKED)
        t4 = store.add("done", SKILL_TASK)
        store.update_status(t4.id, DONE)

        unfinished_ids = {t.id for t in store.unfinished()}

        self.assertEqual(unfinished_ids, {t1.id, t2.id, t3.id})

    def test_all_returns_tasks_oldest_first(self):
        store = TaskStore(InMemoryStore())
        t1 = store.add("first", SKILL_TASK)
        t2 = store.add("second", SKILL_TASK)

        self.assertEqual([t.id for t in store.all()], [t1.id, t2.id])

    def test_parent_id_is_preserved(self):
        store = TaskStore(InMemoryStore())
        parent = store.add("big goal", SKILL_TASK)
        child = store.add("sub-step", SKILL_TASK, parent_id=parent.id)

        self.assertEqual(store.get(child.id).parent_id, parent.id)

    def test_discovered_via_is_preserved(self):
        store = TaskStore(InMemoryStore())
        task = store.add("found this on my own", SKILL_TASK, discovered_via="scan")

        self.assertEqual(store.get(task.id).discovered_via, "scan")


if __name__ == "__main__":
    unittest.main()
