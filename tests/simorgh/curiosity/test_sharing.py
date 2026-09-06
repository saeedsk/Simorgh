import unittest

from simorgh.curiosity.sharing import ShareScheduler


class ShareSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.s = ShareScheduler(growth_cooldown_seconds=100.0, news_cooldown_seconds=200.0)

    def test_nothing_offered_yields_no_decision(self):
        self.assertIsNone(self.s.maybe_share(0.0))

    def test_growth_checked_before_news(self):
        """Spec section 5.7: a direct v1 creator complaint -- 'I don't
        see evidence of self-improving' -- was more pointed than 'share
        more news', so growth always wins when both are ready."""
        self.s.offer_news("news-ref", "news summary", at=0.0)
        self.s.offer_growth("growth-ref", "growth summary", at=0.0)
        decision = self.s.maybe_share(0.0)
        self.assertEqual(decision.kind, "growth")

    def test_news_shared_once_growth_cooldown_active(self):
        self.s.offer_growth("g1", "g summary", at=0.0)
        first = self.s.maybe_share(0.0)
        self.assertEqual(first.kind, "growth")
        self.s.offer_news("n1", "n summary", at=1.0)
        second = self.s.maybe_share(1.0)
        self.assertEqual(second.kind, "news")

    def test_growth_cooldown_blocks_immediate_reshare(self):
        self.s.offer_growth("g1", "s1", at=0.0)
        self.s.maybe_share(0.0)
        self.s.offer_growth("g2", "s2", at=10.0)
        self.assertIsNone(self.s.maybe_share(10.0))
        self.assertIsNotNone(self.s.maybe_share(100.0))

    def test_newer_offer_replaces_buffered_one(self):
        self.s.offer_growth("g1", "s1", at=0.0)
        self.s.offer_growth("g2", "s2", at=5.0)
        decision = self.s.maybe_share(5.0)
        self.assertEqual(decision.content_ref, "g2")

    def test_older_offer_does_not_replace_newer_buffered_one(self):
        self.s.offer_growth("g2", "s2", at=5.0)
        self.s.offer_growth("g1", "s1", at=0.0)
        decision = self.s.maybe_share(5.0)
        self.assertEqual(decision.content_ref, "g2")

    def test_share_consumes_the_buffer(self):
        self.s.offer_growth("g1", "s1", at=0.0)
        self.s.maybe_share(0.0)
        self.s.offer_growth("g1", "s1", at=0.0)  # nothing new offered afterward
        self.assertIsNone(self.s.maybe_share(1.0))


if __name__ == "__main__":
    unittest.main()
