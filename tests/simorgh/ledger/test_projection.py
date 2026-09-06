import unittest
from dataclasses import replace

from .helpers import Counter, make_event
from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.projection import materialize, rebuild


class TestProjectionFold(unittest.TestCase):
    def test_fold_applies_increasing_seqs(self) -> None:
        proj = Counter()

        proj.fold(replace(make_event("s"), seq=1))
        proj.fold(replace(make_event("s"), seq=2))

        self.assertEqual((proj.count, proj.applied_seq), (2, 2))

    def test_fold_ignores_a_duplicate_or_stale_seq(self) -> None:
        proj = Counter()

        proj.fold(replace(make_event("s"), seq=1))
        proj.fold(replace(make_event("s"), seq=1))  # redelivered (a tail racing a rebuild)

        self.assertEqual((proj.count, proj.applied_seq), (1, 1))


class TestRebuildAndMaterializeAgainstABareBackend(unittest.IsolatedAsyncioTestCase):
    """These call `projection.rebuild`/`materialize` directly against a
    backend, bypassing `LedgerClient`, so the module works on its own
    (the client's own tests in test_backends.py cover the wired path)."""

    async def test_rebuild_from_empty_stream(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        proj = Counter()

        head = await rebuild(backend, proj, "task:empty")

        self.assertEqual((head, proj.count, proj.applied_seq), (0, 0, 0))

    async def test_rebuild_with_no_snapshot_replays_everything(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        for i in range(4):
            await backend.append(make_event("task:a"), expected_seq=i)
        proj = Counter()

        head = await rebuild(backend, proj, "task:a")

        self.assertEqual((head, proj.count), (4, 4))

    async def test_materialize_snapshots_and_a_later_rebuild_uses_it(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        proj = Counter()
        proj.snapshot_every = 3
        for i in range(3):
            await backend.append(make_event("task:b"), expected_seq=i)
        await materialize(backend, proj, "task:b")
        self.assertIsNotNone(await backend.read_snapshot("task:b"))

        for i in range(3, 5):
            await backend.append(make_event("task:b"), expected_seq=i)
        proj2 = Counter()
        head = await rebuild(backend, proj2, "task:b")

        self.assertEqual((head, proj2.count), (5, 5))

    async def test_a_corrupt_snapshot_state_falls_back_to_full_replay(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        for i in range(3):
            await backend.append(make_event("task:c"), expected_seq=i)
        await backend.write_snapshot("task:c", {"wrong_key": 99}, 2)  # Counter.load needs "count"
        proj = Counter()

        head = await rebuild(backend, proj, "task:c")

        self.assertEqual((head, proj.count), (3, 3))


if __name__ == "__main__":
    unittest.main()
