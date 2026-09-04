import tempfile
import unittest
from pathlib import Path

from src.agents.interests import InterestTracker
from src.agents.skills.research import SkillResearchAgent
from src.main import (
    build_router,
    extract_propose_topic,
    handle_turn,
    note_interest,
    propose_skill,
    run_skill_code,
    strip_command_slash,
)
from src.memory.long_term import InMemoryStore
from src.orchestrator.apply import APPLIED_KIND
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
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_clean_proposal_is_applied_immediately(self):
        store = InMemoryStore()
        message = propose_skill(
            SkillResearchAgent(), AuditGate(), store, "rocketry", repo_root=self.repo_root
        )

        self.assertIn("APPLIED", message)
        applied = store.query(kind=APPLIED_KIND)
        self.assertEqual(len(applied), 1)
        self.assertIn("rocketry", applied[0].content)
        written = self.repo_root / "src/agents/skills/rocketry.py"
        self.assertTrue(written.exists())
        self.assertIn("rocketry", written.read_text())

    def test_empty_topic_is_rejected_with_usage_message(self):
        store = InMemoryStore()
        message = propose_skill(
            SkillResearchAgent(), AuditGate(), store, "", repo_root=self.repo_root
        )

        self.assertIn("usage", message)
        self.assertEqual(store.query(kind=APPLIED_KIND), [])


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


class TestRunSkillCode(unittest.TestCase):
    def test_build_router_registers_skills_agent(self):
        router = build_router()
        self.assertIn("skills", router.agent_names())

    def test_runs_code_and_returns_stdout(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        output = run_skill_code(router, log, "print('hello from sandbox')")

        self.assertIn("hello from sandbox", output)

    def test_failing_code_is_reported_not_raised(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        output = run_skill_code(router, log, "raise ValueError('boom')")

        self.assertIn("ValueError", output)

    def test_empty_code_shows_usage(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        message = run_skill_code(router, log, "")

        self.assertIn("usage", message)

    def test_run_records_an_outcome(self):
        router = build_router()
        log = OutcomeLog(InMemoryStore())

        run_skill_code(router, log, "print('hi')")

        outcomes = log.recent()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].agent, "skills")
        self.assertTrue(outcomes[0].succeeded)


class TestStripCommandSlash(unittest.TestCase):
    def test_strips_a_leading_slash(self):
        self.assertEqual(strip_command_slash("/reflect"), "reflect")

    def test_strips_leading_slash_from_prefixed_command(self):
        self.assertEqual(strip_command_slash("/propose a calculator"), "propose a calculator")

    def test_leaves_input_without_a_leading_slash_unchanged(self):
        self.assertEqual(strip_command_slash("reflect"), "reflect")
        self.assertEqual(strip_command_slash("hey there"), "hey there")

    def test_bare_slash_becomes_empty_string(self):
        self.assertEqual(strip_command_slash("/"), "")

    def test_only_strips_one_leading_slash(self):
        self.assertEqual(strip_command_slash("//reflect"), "/reflect")


class TestExtractProposeTopic(unittest.TestCase):
    def test_propose_prefix_extracts_topic(self):
        text = "propose a calculator"
        self.assertEqual(extract_propose_topic(text, text.lower()), "a calculator")

    def test_improve_prefix_also_extracts_topic(self):
        text = "improve yourself with a calculator"
        self.assertEqual(
            extract_propose_topic(text, text.lower()), "yourself with a calculator"
        )

    def test_improve_prefix_is_case_insensitive(self):
        text = "Improve error handling"
        self.assertEqual(extract_propose_topic(text, text.lower()), "error handling")

    def test_non_matching_input_returns_none(self):
        text = "hey there"
        self.assertIsNone(extract_propose_topic(text, text.lower()))

    def test_word_containing_improve_is_not_mistaken_for_the_prefix(self):
        text = "improvement tracking"
        self.assertIsNone(extract_propose_topic(text, text.lower()))


if __name__ == "__main__":
    unittest.main()
