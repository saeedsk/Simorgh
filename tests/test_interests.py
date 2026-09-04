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

    def test_follow_up_persists_items_into_the_knowledge_base(self):
        items = [
            NewsItem(title="t1", summary="s1", source="src", published_at=0.0),
            NewsItem(title="t2", summary="s2", source="src", published_at=0.0),
        ]
        tracker = InterestTracker(InMemoryStore(), feed=StubFeed(items))
        tracker.note_interest("rocketry", "r1")

        tracker.follow_up("rocketry")

        unshared = tracker.unshared_news_items()
        self.assertEqual({r.content for r in unshared}, {"t1", "t2"})

    def test_follow_up_dedups_items_already_known_for_the_same_topic(self):
        items = [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        tracker = InterestTracker(InMemoryStore(), feed=StubFeed(items))
        tracker.note_interest("rocketry", "r1")

        tracker.follow_up("rocketry")
        tracker.follow_up("rocketry")  # same item comes back again

        self.assertEqual(len(tracker.unshared_news_items()), 1)

    def test_same_title_from_a_different_topic_is_not_deduped(self):
        items = [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        tracker = InterestTracker(InMemoryStore(), feed=StubFeed(items))
        tracker.note_interest("rocketry", "r1")
        tracker.note_interest("astronomy", "r2")

        tracker.follow_up("rocketry")
        tracker.follow_up("astronomy")

        self.assertEqual(len(tracker.unshared_news_items()), 2)

    def test_mark_news_item_shared_removes_it_from_unshared(self):
        items = [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        tracker = InterestTracker(InMemoryStore(), feed=StubFeed(items))
        tracker.note_interest("rocketry", "r1")
        tracker.follow_up("rocketry")
        record = tracker.unshared_news_items()[0]

        tracker.mark_news_item_shared(record.id)

        self.assertEqual(tracker.unshared_news_items(), [])

    def test_marking_shared_does_not_delete_or_mutate_the_record(self):
        store = InMemoryStore()
        items = [NewsItem(title="t1", summary="s1", source="src", published_at=0.0)]
        tracker = InterestTracker(store, feed=StubFeed(items))
        tracker.note_interest("rocketry", "r1")
        tracker.follow_up("rocketry")
        record = tracker.unshared_news_items()[0]

        tracker.mark_news_item_shared(record.id)

        # The original record still exists and is unchanged -- sharing is
        # additive (a separate marker record), not a mutation/delete.
        self.assertIsNotNone(store.get(record.id))
        self.assertEqual(store.get(record.id).content, "t1")

    def test_unshared_news_items_respects_limit(self):
        items = [
            NewsItem(title=f"t{i}", summary="s", source="src", published_at=0.0)
            for i in range(5)
        ]
        tracker = InterestTracker(InMemoryStore(), feed=StubFeed(items))
        tracker.note_interest("rocketry", "r1")
        tracker.follow_up("rocketry")

        self.assertEqual(len(tracker.unshared_news_items(limit=2)), 2)


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

# Matches the real shape hnrss.org-style feeds ship, caught live: XML
# entities that unescape (during normal XML parsing) into literal HTML
# markup embedded in the description text -- this is what a second,
# separate HTML-stripping pass is for.
_RSS_XML_WITH_HTML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Some &amp; item</title>
  <description>&lt;p&gt;Article URL: &lt;a href="https://example.com"&gt;https://example.com&lt;/a&gt;&lt;/p&gt;
&lt;p&gt;Points: 10&lt;/p&gt;</description>
  <pubDate>Wed, 02 Oct 2024 15:00:00 GMT</pubDate>
</item>
</channel></rss>"""


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

    def test_html_embedded_in_feed_text_is_stripped(self):
        web_fetch = FakeWebFetch(
            result=FetchResult(
                url="https://example.com/feed",
                status_code=200,
                content=_RSS_XML_WITH_HTML,
                truncated=False,
            )
        )
        feed = RssWorldFeed(web_fetch)

        items = feed.fetch("https://example.com/feed")

        self.assertEqual(len(items), 1)
        self.assertNotIn("<", items[0].summary)
        self.assertNotIn("&lt;", items[0].summary)
        self.assertIn("Article URL: https://example.com", items[0].summary)
        self.assertIn("Points: 10", items[0].summary)
        self.assertEqual(items[0].title, "Some & item")


class TestStripHtml(unittest.TestCase):
    def test_plain_text_is_returned_unchanged(self):
        from src.agents.interests import _strip_html

        self.assertEqual(_strip_html("just plain text"), "just plain text")

    def test_tags_are_removed(self):
        from src.agents.interests import _strip_html

        self.assertEqual(_strip_html("<p>hello <b>world</b></p>"), "hello world")

    def test_entities_are_unescaped(self):
        from src.agents.interests import _strip_html

        self.assertEqual(_strip_html("Q &amp; A"), "Q & A")

    def test_whitespace_collapses_to_single_spaces(self):
        from src.agents.interests import _strip_html

        self.assertEqual(_strip_html("<p>a</p>\n\n<p>b</p>"), "a b")

    def test_malformed_markup_never_raises(self):
        from src.agents.interests import _strip_html

        result = _strip_html("<p>unclosed <b>tags")

        self.assertIsInstance(result, str)

    def test_empty_string(self):
        from src.agents.interests import _strip_html

        self.assertEqual(_strip_html(""), "")


if __name__ == "__main__":
    unittest.main()
