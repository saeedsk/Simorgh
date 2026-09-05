import unittest

from src.agents.interests import InterestTracker, NewsItem, WorldFeed
from src.cognition.provider import CognitionRouter, LLMResponse, ProviderUnavailable
from src.memory.long_term import InMemoryStore
from src.orchestrator.apply import APPLIED_KIND, APPLIED_PATCH_KIND
from src.orchestrator.socializing import GrowthHighlight, GrowthSocializer, NewsHighlight, NewsSocializer


class StubFeed(WorldFeed):
    def __init__(self, items):
        self._items = items

    def fetch(self, topic, limit=5):
        return self._items[:limit]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, text):
        self._text = text

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        return LLMResponse(text=self._text, provider_name=self.name)


class RaisingProvider:
    name = "raising"

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        raise ProviderUnavailable("boom")


def _tracker_with_one_item(title="t1", summary="s1", source="src.example.com"):
    store = InMemoryStore()
    items = [NewsItem(title=title, summary=summary, source=source, published_at=0.0)]
    tracker = InterestTracker(store, feed=StubFeed(items))
    tracker.note_interest("https://example.com/feed", "seeded for test")
    return tracker


class TestNewsSocializerReady(unittest.TestCase):
    def test_ready_immediately_after_construction(self):
        self.assertTrue(NewsSocializer().ready())

    def test_not_ready_right_after_a_share(self):
        tracker = _tracker_with_one_item()
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer(cooldown_seconds=3600.0)

        socializer.share_next(tracker, None)

        self.assertFalse(socializer.ready())


class TestShareNext(unittest.TestCase):
    def test_shares_an_already_fetched_unshared_item(self):
        tracker = _tracker_with_one_item()
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, None)

        self.assertIsInstance(highlight, NewsHighlight)
        self.assertEqual(highlight.title, "t1")
        self.assertEqual(tracker.unshared_news_items(), [])

    def test_refreshes_the_most_overdue_interest_when_nothing_unshared(self):
        tracker = _tracker_with_one_item()
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, None)  # nothing fetched yet

        self.assertIsNotNone(highlight)
        self.assertEqual(highlight.title, "t1")

    def test_returns_none_when_nothing_is_tracked_at_all(self):
        tracker = InterestTracker(InMemoryStore())
        socializer = NewsSocializer()

        self.assertIsNone(socializer.share_next(tracker, None))

    def test_returns_none_when_refreshing_turns_up_nothing_new(self):
        store = InMemoryStore()
        tracker = InterestTracker(store, feed=StubFeed([]))  # feed always empty
        tracker.note_interest("https://example.com/feed", "seeded")
        socializer = NewsSocializer()

        self.assertIsNone(socializer.share_next(tracker, None))

    def test_two_calls_share_two_different_items(self):
        store = InMemoryStore()
        items = [
            NewsItem(title="t1", summary="s1", source="src", published_at=0.0),
            NewsItem(title="t2", summary="s2", source="src", published_at=0.0),
        ]
        tracker = InterestTracker(store, feed=StubFeed(items))
        tracker.note_interest("https://example.com/feed", "seeded")
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer()

        first = socializer.share_next(tracker, None)
        second = socializer.share_next(tracker, None)

        self.assertNotEqual(first.title, second.title)


class TestMaybeShare(unittest.TestCase):
    def test_does_nothing_when_not_yet_ready(self):
        tracker = _tracker_with_one_item()
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer(cooldown_seconds=3600.0)
        socializer.share_next(tracker, None)  # starts the cooldown

        result = socializer.maybe_share(tracker, None)

        self.assertIsNone(result)

    def test_shares_when_ready(self):
        tracker = _tracker_with_one_item()
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer(cooldown_seconds=0.0)

        result = socializer.maybe_share(tracker, None)

        self.assertIsNotNone(result)


class TestBlurbDrafting(unittest.TestCase):
    def test_uses_a_real_llm_response_when_available(self):
        tracker = _tracker_with_one_item()
        tracker.follow_up("https://example.com/feed")
        cognition = CognitionRouter([ScriptedProvider("here's something neat!")])
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, cognition)

        self.assertEqual(highlight.blurb, "here's something neat!")

    def test_falls_back_to_raw_content_with_no_cognition(self):
        tracker = _tracker_with_one_item(title="t1", summary="s1")
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, None)

        self.assertIn("t1", highlight.blurb)
        self.assertIn("s1", highlight.blurb)

    def test_falls_back_when_only_the_deterministic_provider_answers(self):
        tracker = _tracker_with_one_item(title="t1", summary="s1")
        tracker.follow_up("https://example.com/feed")
        cognition = CognitionRouter()  # deterministic fallback only
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, cognition)

        self.assertIn("t1", highlight.blurb)

    def test_falls_back_when_the_provider_raises(self):
        tracker = _tracker_with_one_item(title="t1", summary="s1")
        tracker.follow_up("https://example.com/feed")
        cognition = CognitionRouter([RaisingProvider()])
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, cognition)

        self.assertIn("t1", highlight.blurb)

    def test_title_alone_when_there_is_no_summary(self):
        tracker = _tracker_with_one_item(title="t1", summary="")
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, None)

        self.assertEqual(highlight.blurb, "t1")

    def test_highlight_carries_source_and_topic(self):
        tracker = _tracker_with_one_item(source="news.example.com")
        tracker.follow_up("https://example.com/feed")
        socializer = NewsSocializer()

        highlight = socializer.share_next(tracker, None)

        self.assertEqual(highlight.source, "news.example.com")
        self.assertEqual(highlight.topic, "https://example.com/feed")


class TestGrowthSocializerReady(unittest.TestCase):
    def test_ready_immediately_after_construction(self):
        self.assertTrue(GrowthSocializer(InMemoryStore()).ready())

    def test_not_ready_right_after_a_share(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", rationale="fun")
        socializer = GrowthSocializer(store, cooldown_seconds=3600.0)

        socializer.share_next(None)

        self.assertFalse(socializer.ready())


class TestGrowthShareNext(unittest.TestCase):
    def test_shares_the_most_recent_applied_skill(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "src/agents/skills/rocketry.py", rationale="fun capability")
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(None)

        self.assertIsInstance(highlight, GrowthHighlight)
        self.assertEqual(highlight.subject, "src/agents/skills/rocketry.py")
        self.assertEqual(highlight.kind, "skill")
        self.assertEqual(highlight.rationale, "fun capability")

    def test_shares_an_applied_patch_too(self):
        store = InMemoryStore()
        store.remember(APPLIED_PATCH_KIND, "src/main.py", rationale="fixed a bug")
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(None)

        self.assertEqual(highlight.kind, "patch")

    def test_most_recent_change_wins_across_skills_and_patches(self):
        import time

        store = InMemoryStore()
        store.remember(APPLIED_KIND, "old.py", rationale="older")
        time.sleep(0.01)
        store.remember(APPLIED_PATCH_KIND, "new.py", rationale="newer")
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(None)

        self.assertEqual(highlight.subject, "new.py")

    def test_returns_none_when_nothing_has_ever_been_applied(self):
        socializer = GrowthSocializer(InMemoryStore())

        self.assertIsNone(socializer.share_next(None))

    def test_does_not_repeat_an_already_shared_highlight(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "only.py", rationale="the only one")
        socializer = GrowthSocializer(store)

        first = socializer.share_next(None)
        second = socializer.share_next(None)

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_two_calls_share_two_different_changes(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py", rationale="a")
        store.remember(APPLIED_KIND, "b.py", rationale="b")
        socializer = GrowthSocializer(store)

        first = socializer.share_next(None)
        second = socializer.share_next(None)

        self.assertNotEqual(first.subject, second.subject)


class TestGrowthMaybeShare(unittest.TestCase):
    def test_does_nothing_when_not_yet_ready(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py", rationale="a")
        socializer = GrowthSocializer(store, cooldown_seconds=3600.0)
        socializer.share_next(None)  # starts the cooldown

        self.assertIsNone(socializer.maybe_share(None))

    def test_shares_when_ready(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py", rationale="a")
        socializer = GrowthSocializer(store, cooldown_seconds=0.0)

        self.assertIsNotNone(socializer.maybe_share(None))


class TestGrowthBlurbDrafting(unittest.TestCase):
    def test_uses_a_real_llm_response_when_available(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py", rationale="a reason")
        cognition = CognitionRouter([ScriptedProvider("look what I did!")])
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(cognition)

        self.assertEqual(highlight.blurb, "look what I did!")

    def test_falls_back_to_a_plain_rendering_with_no_cognition(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py", rationale="a good reason")
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(None)

        self.assertIn("a.py", highlight.blurb)
        self.assertIn("a good reason", highlight.blurb)

    def test_falls_back_when_only_the_deterministic_provider_answers(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py", rationale="a reason")
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(CognitionRouter())

        self.assertIn("a.py", highlight.blurb)

    def test_falls_back_when_the_provider_raises(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py", rationale="a reason")
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(CognitionRouter([RaisingProvider()]))

        self.assertIn("a.py", highlight.blurb)

    def test_handles_a_missing_rationale_gracefully(self):
        store = InMemoryStore()
        store.remember(APPLIED_KIND, "a.py")
        socializer = GrowthSocializer(store)

        highlight = socializer.share_next(None)

        self.assertIn("a.py", highlight.blurb)


if __name__ == "__main__":
    unittest.main()
