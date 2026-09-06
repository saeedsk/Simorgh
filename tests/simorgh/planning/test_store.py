import unittest

from simorgh.ledger.backends.memory import InMemoryBackend as LedgerMemoryBackend
from simorgh.ledger.client import LedgerClient

from simorgh.planning.model import AVAILABLE, BLOCKED, COMPLETED, IN_PROGRESS, PENDING
from simorgh.planning.store import TASK_SNAPSHOT_EVERY, TaskStore

from tests.simorgh.helpers import FakeClock
from tests.simorgh.orchestration.harness import run


async def _store(clock=None):
    clock = clock or FakeClock()
    ledger = LedgerClient(LedgerMemoryBackend(), clock=clock)
    await ledger.start()
    return TaskStore(ledger, clock), ledger, clock


class TestCreateAndTransition(unittest.TestCase):
    @run
    async def test_create_produces_a_pending_task(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        self.assertEqual(task.status, PENDING)
        self.assertEqual((await store.get(task.id)).id, task.id)

    @run
    async def test_transition_updates_status_and_projection(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        updated = await store.transition(task.id, AVAILABLE)
        self.assertEqual(updated.status, AVAILABLE)
        self.assertEqual((await store.get(task.id)).status, AVAILABLE)

    @run
    async def test_transition_same_status_is_a_noop(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        again = await store.transition(task.id, PENDING)
        self.assertEqual(again.status, PENDING)

    @run
    async def test_illegal_transition_raises(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        with self.assertRaises(ValueError):
            await store.transition(task.id, COMPLETED)

    @run
    async def test_transition_unknown_task_raises(self):
        store, _, _ = await _store()
        with self.assertRaises(KeyError):
            await store.transition("ghost", AVAILABLE)


class TestClaim(unittest.TestCase):
    @run
    async def test_claim_grants_when_available(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)
        result = await store.claim(task.id, "worker-1", 60.0)
        self.assertTrue(result.granted)
        self.assertEqual(result.task.status, "claimed")
        self.assertEqual(result.task.lease.worker_id, "worker-1")

    @run
    async def test_claim_denied_when_not_available(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        result = await store.claim(task.id, "worker-1", 60.0)
        self.assertFalse(result.granted)
        self.assertEqual(result.reason, "not_available")

    @run
    async def test_claim_denied_when_unknown(self):
        store, _, _ = await _store()
        result = await store.claim("ghost", "worker-1", 60.0)
        self.assertFalse(result.granted)
        self.assertEqual(result.reason, "unknown_task")

    @run
    async def test_second_claim_after_first_is_denied_not_available(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)
        first = await store.claim(task.id, "worker-1", 60.0)
        second = await store.claim(task.id, "worker-2", 60.0)
        self.assertTrue(first.granted)
        self.assertFalse(second.granted)
        self.assertEqual(second.reason, "not_available")

    @run
    async def test_concurrent_instances_racing_on_a_stale_index_lose_the_cas(self):
        # Two independent `TaskStore`s over the same Ledger, matching the
        # multi-Planning-instance scenario the CAS is actually for: both
        # rebuild from the same (available) state, so both attempt the
        # `claimed` append with the same `expected_seq` -- only one wins.
        store, ledger, clock = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)

        other = TaskStore(ledger, clock)
        await other.rebuild()

        import asyncio

        first, second = await asyncio.gather(
            store.claim(task.id, "worker-1", 60.0), other.claim(task.id, "worker-2", 60.0)
        )
        results = {first.granted, second.granted}
        self.assertEqual(results, {True, False})
        loser = second if first.granted else first
        self.assertEqual(loser.reason, "leased_to_other")

    @run
    async def test_lease_refresh_extends_until(self):
        store, _, clock = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)
        claimed = await store.claim(task.id, "worker-1", 60.0)
        clock.advance(30.0)
        await store.refresh_lease(task.id, 90.0)
        refreshed = await store.get(task.id)
        self.assertGreater(refreshed.lease.until, claimed.lease_until)

    @run
    async def test_expire_lease_returns_task_to_available(self):
        store, _, _ = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)
        await store.claim(task.id, "worker-1", 60.0)
        await store.expire_lease(task.id)
        refreshed = await store.get(task.id)
        self.assertEqual(refreshed.status, AVAILABLE)
        self.assertIsNone(refreshed.lease)


class TestQueries(unittest.TestCase):
    @run
    async def test_children_and_rollup_inputs(self):
        store, _, _ = await _store()
        parent = await store.create(kind="project", description="p", origin="human")
        c1 = await store.create(kind="patch", description="c1", origin="planning", parent_id=parent.id)
        c2 = await store.create(kind="patch", description="c2", origin="planning", parent_id=parent.id)
        kids = store.children(parent.id)
        self.assertEqual({t.id for t in kids}, {c1.id, c2.id})

    @run
    async def test_ready_excludes_blocked_and_unavailable(self):
        store, _, _ = await _store()
        a = await store.create(kind="patch", description="a", origin="human")
        await store.transition(a.id, AVAILABLE)
        b = await store.create(kind="patch", description="b", origin="human", depends_on=[a.id])
        await store.transition(b.id, BLOCKED)
        ready = store.ready()
        self.assertEqual([t.id for t in ready], [a.id])

    @run
    async def test_ready_includes_child_once_dependency_completes(self):
        store, _, _ = await _store()
        a = await store.create(kind="patch", description="a", origin="human")
        await store.transition(a.id, AVAILABLE)
        b = await store.create(kind="patch", description="b", origin="human", depends_on=[a.id])
        await store.transition(b.id, BLOCKED)
        await store.claim(a.id, "w1", 60.0)
        await store.transition(a.id, IN_PROGRESS)
        await store.transition(a.id, COMPLETED)
        await store.transition(b.id, AVAILABLE)
        ready = store.ready()
        self.assertEqual([t.id for t in ready], [b.id])

    @run
    async def test_unfinished_excludes_terminal_tasks(self):
        store, _, _ = await _store()
        a = await store.create(kind="patch", description="a", origin="human")
        await store.transition(a.id, AVAILABLE)
        await store.claim(a.id, "w1", 60.0)
        await store.transition(a.id, IN_PROGRESS)
        await store.transition(a.id, COMPLETED)
        b = await store.create(kind="patch", description="b", origin="human")
        self.assertEqual([t.id for t in store.unfinished()], [b.id])


class TestRebuildAndSnapshot(unittest.TestCase):
    @run
    async def test_rebuild_from_scratch_reconstructs_state(self):
        store, ledger, clock = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        await store.transition(task.id, AVAILABLE)
        await store.claim(task.id, "worker-1", 60.0)

        fresh = TaskStore(ledger, clock)
        await fresh.rebuild()
        rebuilt = await fresh.get(task.id)
        self.assertEqual(rebuilt.status, "claimed")
        self.assertEqual(rebuilt.lease.worker_id, "worker-1")

    @run
    async def test_snapshot_written_after_threshold_events(self):
        store, ledger, _ = await _store()
        loaded = await ledger.load_snapshot(store._index_stream)
        self.assertIsNone(loaded)
        for _ in range(TASK_SNAPSHOT_EVERY - 1):
            await store._maybe_snapshot()
        loaded = await ledger.load_snapshot(store._index_stream)
        self.assertIsNone(loaded)
        await store._maybe_snapshot()
        loaded = await ledger.load_snapshot(store._index_stream)
        self.assertIsNotNone(loaded)

    @run
    async def test_rebuild_after_snapshot_still_reflects_later_events(self):
        store, ledger, clock = await _store()
        task = await store.create(kind="patch", description="d", origin="human")
        await ledger.snapshot(store._index_stream, store.index.snapshot_state(), at_seq=0)
        await store.transition(task.id, AVAILABLE)

        fresh = TaskStore(ledger, clock)
        await fresh.rebuild()
        self.assertEqual((await fresh.get(task.id)).status, AVAILABLE)


if __name__ == "__main__":
    unittest.main()
