import unittest

from src.agents.interests import InterestTracker, NewsItem, NullWorldFeed, RssWorldFeed, WorldFeed
from src.memory.long_term import InMemoryStore
from src.tools.web_fetch import FetchRefused, FetchResult


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


class FakeWebFetch:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        if self._raises is not None:
            raise self._raises
        return self._result


_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Example Feed</title>
<item>
  <title>First item</title>
  <description>First summary</description>
  <pubDate>Wed, 02 Oct 2024 15:00:00 GMT</pubDate>
</item>
<item>
  <title>Second item</title>
  <description>Second summary</description>
  <pubDate>Thu, 03 Oct 2024 15:00:00 GMT</pubDate>
</item>
</channel></rss>"""

_ATOM_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Example Atom Feed</title>
<entry>
  <title>Atom item</title>
  <summary>Atom summary</summary>
  <updated>2024-10-02T15:00:00Z</updated>
</entry>
</feed>"""


class TestRssWorldFeed(unittest.TestCase):
    def test_non_url_topic_never_fetches_and_returns_empty(self):
        web_fetch = FakeWebFetch()
        feed = RssWorldFeed(web_fetch)

        result = feed.fetch("rocketry")

        self.assertEqual(result, [])
        self.assertEqual(web_fetch.calls, [])

    def test_parses_rss_items(self):
        web_fetch = FakeWebFetch(
            result=FetchResult(
                url="https://example.com/feed", status_code=200, content=_RSS_XML, truncated=False
            )
        )
        feed = RssWorldFeed(web_fetch)

        items = feed.fetch("https://example.com/feed")

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "First item")
        self.assertEqual(items[0].summary, "First summary")
        self.assertEqual(items[0].source, "example.com")
        self.assertGreater(items[0].published_at, 0)

    def test_parses_atom_items(self):
        web_fetch = FakeWebFetch(
            result=FetchResult(
                url="https://example.com/atom", status_code=200, content=_ATOM_XML, truncated=False
            )
        )
        feed = RssWorldFeed(web_fetch)

        items = feed.fetch("https://example.com/atom")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Atom item")
        self.assertEqual(items[0].summary, "Atom summary")

    def test_respects_limit(self):
        web_fetch = FakeWebFetch(
            result=FetchResult(
                url="https://example.com/feed", status_code=200, content=_RSS_XML, truncated=False
            )
        )
        feed = RssWorldFeed(web_fetch)

        items = feed.fetch("https://example.com/feed", limit=1)

        self.assertEqual(len(items), 1)

    def test_non_200_status_returns_empty(self):
        web_fetch = FakeWebFetch(
            result=FetchResult(url="https://example.com/feed", status_code=404, content="", truncated=False)
        )
        feed = RssWorldFeed(web_fetch)

        self.assertEqual(feed.fetch("https://example.com/feed"), [])

    def test_fetch_refused_returns_empty_not_raise(self):
        web_fetch = FakeWebFetch(raises=FetchRefused("blocked"))
        feed = RssWorldFeed(web_fetch)

        self.assertEqual(feed.fetch("https://example.com/feed"), [])

    def test_malformed_xml_returns_empty(self):
        web_fetch = FakeWebFetch(
            result=FetchResult(
                url="https://example.com/feed", status_code=200, content="not xml{{{", truncated=False
            )
        )
        feed = RssWorldFeed(web_fetch)

        self.assertEqual(feed.fetch("https://example.com/feed"), [])


if __name__ == "__main__":
    unittest.main()
