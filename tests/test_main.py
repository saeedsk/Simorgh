import unittest

from src.agents.interests import InterestTracker
from src.agents.skills.research import SkillResearchAgent
from src.main import (
    PENDING_KIND,
    build_router,
    handle_turn,
    note_interest,
    propose_skill,
)
from src.memory.long_term import InMemoryStore
from src.orchestrator.audit import AuditGate
from src.orchestrator.health import HealthMonitor
from src.orchestrator.reflection import OutcomeLog


class TestMainCli(unittest.TestCase):
    def test_handle_turn_returns_combined_reaction_and_response(self):
        router = build_router()

        output = handle_turn(router, "This is great news, thanks!")

        self.assertIn("Here's my take", output)
        self.assertTrue(output[0].isupper())

    def test_handle_turn_updates_shared_mood_across_calls(self):
        router = build_router()

        handle_turn(router, "This is terrible and awful")

        self.assertLess(router.bus.read().valence, 0)

    def test_handle_turn_flags_heavy_cognitive_load(self):
        router = build_router()

        for _ in range(15):
            handle_turn(router, "another task")

        output = handle_turn(router, "one more task")

        self.assertIn("taking a moment to think this through", output)

    def test_handle_turn_records_outcomes_when_given_a_log(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        handle_turn(router, "hello there", log)

        outcomes = log.recent()
        agents = {o.agent for o in outcomes}
        self.assertEqual(agents, {"emotion", "logic"})
        self.assertTrue(all(o.succeeded for o in outcomes))

    def test_handle_turn_without_a_log_does_not_error(self):
        router = build_router()
        # outcome_log defaults to None -- should behave exactly as before
        output = handle_turn(router, "hello there")
        self.assertTrue(output)

    def test_handle_turn_self_corrects_when_mood_is_pinned_at_an_extreme(self):
        router = build_router()
        for _ in range(6):
            router.bus.publish_state("test", valence=1.0, arousal=1.0)
        monitor = HealthMonitor()

        output = handle_turn(router, "just checking in", health_monitor=monitor)

        self.assertIn("self-correction", output)
        self.assertEqual(router.bus.read().valence, 0.0)
        self.assertEqual(router.bus.read().arousal, 0.0)

    def test_handle_turn_without_health_monitor_does_not_self_correct(self):
        router = build_router()
        for _ in range(6):
            router.bus.publish_state("test", valence=1.0, arousal=1.0)

        output = handle_turn(router, "just checking in")

        self.assertNotIn("self-correction", output)
        self.assertEqual(router.bus.read().valence, 1.0)

    def test_handle_turn_with_health_monitor_and_stable_mood_is_unaffected(self):
        router = build_router()
        monitor = HealthMonitor()

        output = handle_turn(router, "hello there", health_monitor=monitor)

        self.assertNotIn("self-correction", output)


class TestProposeSkill(unittest.TestCase):
    def test_clean_proposal_is_logged_as_pending_not_merged(self):
        store = InMemoryStore()
        message = propose_skill(SkillResearchAgent(), AuditGate(), store, "rocketry")

        self.assertIn("PENDING YOUR APPROVAL", message)
        pending = store.query(kind=PENDING_KIND)
        self.assertEqual(len(pending), 1)
        self.assertIn("rocketry", pending[0].content)

    def test_empty_topic_is_rejected_with_usage_message(self):
        store = InMemoryStore()
        message = propose_skill(SkillResearchAgent(), AuditGate(), store, "")

        self.assertIn("usage", message)
        self.assertEqual(store.query(kind=PENDING_KIND), [])


class TestNoteInterest(unittest.TestCase):
    def test_notes_a_topic(self):
        store = InMemoryStore()
        tracker = InterestTracker(store)

        message = note_interest(tracker, "rocketry")

        self.assertIn("rocketry", message)
        self.assertEqual(len(tracker.list_interests()), 1)

    def test_empty_topic_shows_usage(self):
        tracker = InterestTracker(InMemoryStore())

        message = note_interest(tracker, "")

        self.assertIn("usage", message)
        self.assertEqual(tracker.list_interests(), [])


if __name__ == "__main__":
    unittest.main()
