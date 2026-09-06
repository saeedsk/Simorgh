import unittest

from simorgh.curiosity.api import NewsItem
from simorgh.curiosity.interests import InterestService, is_feed_url, parse_feed_items

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Feed</title>
<item><title>Item &amp; One</title><description>&lt;p&gt;Summary one&lt;/p&gt;</description><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
<item><title>Item Two</title><description>Summary two</description><pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate></item>
</channel></rss>"""

_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom Item</title><summary>Atom summary</summary><updated>2024-01-03T00:00:00Z</updated></entry>
</feed>"""


class IsFeedUrlTest(unittest.TestCase):
    def test_http_url_is_a_feed_url(self):
        self.assertTrue(is_feed_url("https://hnrss.org/frontpage"))

    def test_plain_topic_is_not_a_feed_url(self):
        self.assertFalse(is_feed_url("distributed systems"))

    def test_malformed_scheme_is_not_a_feed_url(self):
        self.assertFalse(is_feed_url("ftp://example.com/feed"))


class ParseFeedItemsTest(unittest.TestCase):
    def test_parses_rss_items_and_strips_html(self):
        items = parse_feed_items(_RSS, source="hn", limit=10)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "Item & One")
        self.assertEqual(items[0].summary, "Summary one")

    def test_respects_limit(self):
        items = parse_feed_items(_RSS, source="hn", limit=1)
        self.assertEqual(len(items), 1)

    def test_falls_back_to_atom_when_no_rss_items(self):
        items = parse_feed_items(_ATOM, source="atom-source", limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Atom Item")

    def test_malformed_xml_returns_empty_list(self):
        self.assertEqual(parse_feed_items("not xml at all <<<", source="x", limit=10), [])

    def test_empty_feed_returns_empty_list(self):
        empty = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        self.assertEqual(parse_feed_items(empty, source="x", limit=10), [])


class InterestServiceTest(unittest.TestCase):
    def setUp(self):
        self.svc = InterestService(follow_up_cooldown_seconds=100.0)

    def test_note_creates_interest_with_default_score(self):
        interest = self.svc.note("https://example.com/feed")
        self.assertEqual(interest.score, 1.0)
        self.assertIsNone(interest.last_followed_up)

    def test_note_is_idempotent_on_topic(self):
        self.svc.note("t1", why="a")
        self.svc.note("t1", why="b")
        self.assertEqual(len(self.svc.list_interests()), 1)

    def test_never_followed_up_wins_over_stale_ones(self):
        self.svc.note("old")
        self.svc.record_follow_up("old", [], now=0.0)
        self.svc.note("new")
        least = self.svc.least_recently_followed(now=1.0)
        self.assertEqual(least.topic, "new")

    def test_respects_cooldown(self):
        self.svc.note("t1")
        self.svc.record_follow_up("t1", [], now=0.0)
        self.assertIsNone(self.svc.least_recently_followed(now=50.0))
        self.assertIsNotNone(self.svc.least_recently_followed(now=150.0))

    def test_score_decays_on_denial(self):
        self.svc.note("t1")
        interest = self.svc.record_follow_up("t1", [], now=0.0, denied=True)
        self.assertAlmostEqual(interest.score, 0.8)

    def test_score_decays_on_empty_items_even_without_denial(self):
        interest = self.svc.record_follow_up("t1", [], now=0.0, denied=False)
        self.assertAlmostEqual(interest.score, 0.8)

    def test_score_unaffected_by_successful_follow_up(self):
        self.svc.note("t1")
        interest = self.svc.record_follow_up(
            "t1", [NewsItem(title="t", summary="s", source="src", published_at=0.0)],
            now=0.0, denied=False,
        )
        self.assertEqual(interest.score, 1.0)

    def test_decay_reduces_score_proportionally_to_elapsed_days(self):
        self.svc.note("t1")
        self.svc.decay(0.0, elapsed_days=10.0)
        interest = self.svc.list_interests()[0]
        self.assertLess(interest.score, 1.0)

    def test_topics_lower_matches_case_insensitively(self):
        self.svc.note("Distributed Systems")
        self.assertIn("distributed systems", self.svc.topics_lower())


if __name__ == "__main__":
    unittest.main()
