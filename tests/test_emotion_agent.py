import unittest

from src.agents.emotion.base import EmotionAgent
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.persona_state import Valence
from src.orchestrator.router import AgentRequest


class TestEmotionAgent(unittest.TestCase):
    def test_positive_input_raises_valence_and_reacts_positively(self):
        agent = EmotionAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="This is great, thanks!"), bus)

        self.assertGreater(bus.read().valence, 0)
        self.assertIs(bus.read().valence_label, Valence.POSITIVE)
        self.assertIn(response.output, {"That's exciting!", "That sounds nice.", "That's pleasant."})

    def test_negative_input_lowers_valence_and_reacts_negatively(self):
        agent = EmotionAgent()
        bus = SharedMemoryBus()

        agent.handle(AgentRequest(text="This is terrible and broken"), bus)

        self.assertLess(bus.read().valence, 0)

    def test_urgent_input_raises_arousal(self):
        agent = EmotionAgent()
        bus = SharedMemoryBus()

        agent.handle(AgentRequest(text="urgent emergency help now"), bus)

        self.assertGreater(bus.read().arousal, 0.3)

    def test_neutral_input_leaves_state_near_baseline(self):
        agent = EmotionAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="the file is in the folder"), bus)

        self.assertEqual(bus.read().valence, 0.0)
        self.assertEqual(response.output, "Okay.")


if __name__ == "__main__":
    unittest.main()
