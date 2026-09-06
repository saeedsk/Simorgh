import unittest

from .helpers import make_event
from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.compaction import DEFAULT_RETENTION, RetentionPolicy, parse_duration, run_compaction


class TestParseDuration(unittest.TestCase):
    def test_parses_each_unit(self):
        self.assertEqual(parse_duration("30s"), 30.0)
        self.assertEqual(parse_duration("5m"), 300.0)
        self.assertEqual(parse_duration("2h"), 7200.0)
        self.assertEqual(parse_duration("7d"), 7 * 86400.0)

    def test_forever_and_none_mean_no_window(self):
        self.assertIsNone(parse_duration("forever"))
        self.assertIsNone(parse_duration(None))

    def test_a_bare_number_is_seconds(self):
        self.assertEqual(parse_duration(90), 90.0)

    def test_a_bad_string_raises(self):
        with self.assertRaises(ValueError):
            parse_duration("nonsense")
        with self.assertRaises(ValueError):
            parse_duration("7 weeks")


class TestRetentionPolicy(unittest.TestCase):
    def test_defaults_match_the_documented_windows(self):
        policy = RetentionPolicy.parse(None)
        self.assertEqual(policy.window_for("trace:xyz"), parse_duration(DEFAULT_RETENTION["trace:"]))
        self.assertEqual(policy.window_for("dead:foo"), parse_duration(DEFAULT_RETENTION["dead:"]))
        self.assertEqual(policy.window_for("activity"), parse_duration(DEFAULT_RETENTION["activity"]))
        self.assertIsNone(policy.window_for("task:abc"))  # forever by default

    def test_longest_matching_prefix_wins(self):
        policy = RetentionPolicy.parse({"task:": "forever", "task:temp:": "1d"})
        self.assertIsNone(policy.window_for("task:abc"))
        self.assertEqual(policy.window_for("task:temp:x"), 86400.0)

    def test_keep_tail_is_configurable(self):
        policy = RetentionPolicy.parse({"keep_tail": 5})
        self.assertEqual(policy.keep_tail, 5)


class TestRunCompaction(unittest.IsolatedAsyncioTestCase):
    async def test_a_per_id_stream_past_its_window_is_deleted_whole(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        await backend.append(make_event("trace:old", ts=0.0), expected_seq=None)
        await backend.append(make_event("trace:new", ts=1000.0), expected_seq=None)
        policy = RetentionPolicy.parse({"trace:": "100s"})

        report = await run_compaction(backend, policy, now=1000.0)

        self.assertEqual(report.streams_deleted, 1)
        self.assertEqual(await backend.streams(""), ["trace:new"])

    async def test_a_per_id_stream_inside_its_window_survives(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        await backend.append(make_event("trace:recent", ts=950.0), expected_seq=None)
        policy = RetentionPolicy.parse({"trace:": "100s"})

        await run_compaction(backend, policy, now=1000.0)

        self.assertEqual(await backend.streams(""), ["trace:recent"])

    async def test_a_singleton_stream_is_truncated_to_its_window(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        for i, ts in enumerate([0.0, 500.0, 1000.0]):
            await backend.append(make_event("activity", ts=ts), expected_seq=i)
        policy = RetentionPolicy.parse({"activity": "600s"})

        await run_compaction(backend, policy, now=1000.0)

        remaining = await backend.read("activity", from_seq=0, limit=None)
        self.assertEqual([e.ts for e in remaining], [500.0, 1000.0])

    async def test_a_forever_stream_is_truncated_to_snapshot_minus_keep_tail(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        for i in range(10):
            await backend.append(make_event("task:k", ts=float(i)), expected_seq=i)
        await backend.write_snapshot("task:k", {"n": 8}, 8)
        policy = RetentionPolicy.parse({}, keep_tail=2)

        report = await run_compaction(backend, policy, now=100.0)

        remaining = await backend.read("task:k", from_seq=0, limit=None)
        self.assertEqual([e.seq for e in remaining], [7, 8, 9, 10])
        self.assertGreater(report.events_truncated, 0)

    async def test_a_forever_stream_with_no_snapshot_is_left_alone(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        for i in range(3):
            await backend.append(make_event("task:m"), expected_seq=i)
        policy = RetentionPolicy.parse({})

        report = await run_compaction(backend, policy, now=100.0)

        self.assertEqual(report.events_truncated, 0)
        self.assertEqual(len(await backend.read("task:m", from_seq=0, limit=None)), 3)

    async def test_a_protected_prefix_is_never_compacted(self) -> None:
        backend = InMemoryBackend()
        await backend.start()
        await backend.append(make_event("ledger:compaction", ts=0.0), expected_seq=None)
        policy = RetentionPolicy.parse({"ledger:": "1s"})

        report = await run_compaction(backend, policy, now=1000.0, protect=("ledger:",))

        self.assertEqual(report.streams_seen, 0)
        self.assertEqual(await backend.streams(""), ["ledger:compaction"])


if __name__ == "__main__":
    unittest.main()
