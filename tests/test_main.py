import unittest

from src.main import build_router, handle_turn
from src.memory.long_term import InMemoryStore
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


if __name__ == "__main__":
    unittest.main()
