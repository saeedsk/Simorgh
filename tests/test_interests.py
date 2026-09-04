import unittest

from src.agents.interests import InterestTracker, NewsItem, NullWorldFeed, WorldFeed
from src.memory.long_term import InMemoryStore


class StubFeed(WorldFeed):
    def __init__(self, items):
        self._items = items

    def fetch(self, topic, limit=5):
        return self._items[:limit]


class TestNullWorldFeed(unittest.TestCase):
    def test_always_returns_empty_and_never_raises(self):
        feed = NullWorldFeed()
        self.assertEqual(feed.fetch("anything"), [])


class TestInterestTracker(unittest.TestCase):
    def test_note_interest_then_list(self):
        tracker = InterestTracker(InMemoryStore())
        tracker.note_interest("rocketry", "creator mentioned it twice")

        interests = tracker.list_interests()

        self.assertEqual(len(interests), 1)
        self.assertEqual(interests[0].topic, "rocketry")
        self.assertIsNone(interests[0].last_followed_up)

    def test_list_interests_collapses_to_one_entry_per_topic(self):
        tracker = InterestTracker(InMemoryStore())
        tracker.note_interest("rocketry", "first reason")
        tracker.note_interest("rocketry", "second reason")

        interests = tracker.list_interests()

        self.assertEqual(len(interests), 1)
        self.assertEqual(interests[0].why, "second reason")

    def test_least_recently_followed_up_prefers_never_followed_up(self):
        tracker = InterestTracker(InMemoryStore())
        tracker.note_interest("astronomy", "r1")
        tracker.follow_up("astronomy")
        tracker.note_interest("rocketry", "r2")

        overdue = tracker.least_recently_followed_up()

        self.assertEqual(overdue.topic, "rocketry")

    def test_least_recently_followed_up_returns_none_when_empty(self):
        tracker = InterestTracker(InMemoryStore())
        self.assertIsNone(tracker.least_recently_followed_up())

    def test_follow_up_uses_configured_feed_and_records_timestamp(self):
        items = [NewsItem(title="t", summary="s", source="src", published_at=0.0)]
        tracker = InterestTracker(InMemoryStore(), feed=StubFeed(items))
        tracker.note_interest("rocketry", "r1")

        result = tracker.follow_up("rocketry")

        self.assertEqual(result, items)
        updated = tracker.list_interests()[0]
        self.assertIsNotNone(updated.last_followed_up)

    def test_follow_up_with_default_null_feed_returns_empty(self):
        tracker = InterestTracker(InMemoryStore())
        tracker.note_interest("rocketry", "r1")

        self.assertEqual(tracker.follow_up("rocketry"), [])


if __name__ == "__main__":
    unittest.main()
