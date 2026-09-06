import unittest
from dataclasses import replace

from .helpers import make_event
from simorgh.ledger.idempotency import IdempotencyIndex


class TestIdempotencyIndex(unittest.TestCase):
    def test_record_and_get(self):
        idx = IdempotencyIndex()
        idx.record("s", "k1", 1)
        self.assertEqual(idx.get("s", "k1"), 1)
        self.assertIsNone(idx.get("s", "missing"))
        self.assertIsNone(idx.get("other-stream", "k1"))

    def test_record_without_key_is_a_noop(self):
        idx = IdempotencyIndex()
        idx.record("s", None, 1)
        self.assertEqual(idx.items("s"), [])

    def test_rebuild_from_events(self):
        idx = IdempotencyIndex()
        events = [
            replace(make_event("s", idempotency_key="a"), seq=1),
            replace(make_event("s", idempotency_key="b"), seq=2),
            replace(make_event("s"), seq=3),  # no key: not indexed
        ]
        idx.rebuild("s", events)
        self.assertEqual(idx.get("s", "a"), 1)
        self.assertEqual(idx.get("s", "b"), 2)
        self.assertEqual(len(idx.items("s")), 2)

    def test_forget_below_keeps_only_recent_keys(self):
        idx = IdempotencyIndex()
        idx.record("s", "a", 1)
        idx.record("s", "b", 5)
        idx.forget_below("s", 5)
        self.assertIsNone(idx.get("s", "a"))
        self.assertEqual(idx.get("s", "b"), 5)

    def test_forget_stream_clears_everything_for_it_only(self):
        idx = IdempotencyIndex()
        idx.record("s1", "a", 1)
        idx.record("s2", "b", 1)
        idx.forget_stream("s1")
        self.assertIsNone(idx.get("s1", "a"))
        self.assertEqual(idx.get("s2", "b"), 1)


if __name__ == "__main__":
    unittest.main()
