import unittest

from src.agents.logic.base import LogicAgent
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.persona_state import PersonaState
from src.orchestrator.router import AgentRequest


class TestLogicAgent(unittest.TestCase):
    def test_default_mood_gives_plain_framing(self):
        agent = LogicAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="what's the weather"), bus)

        self.assertEqual(response.output, "Here's my take: what's the weather")

    def test_negative_high_arousal_mood_gives_calming_framing(self):
        state = PersonaState()
        state.set_state(valence=-0.8, arousal=0.8)
        bus = SharedMemoryBus(state)
        agent = LogicAgent()

        response = agent.handle(AgentRequest(text="everything is broken"), bus)

        self.assertTrue(response.output.startswith("Let's slow down"))

    def test_positive_high_arousal_mood_gives_energetic_framing(self):
        state = PersonaState()
        state.set_state(valence=0.8, arousal=0.8)
        bus = SharedMemoryBus(state)
        agent = LogicAgent()

        response = agent.handle(AgentRequest(text="let's ship it"), bus)

        self.assertTrue(response.output.startswith("Let's dive right in"))

    def test_high_cognitive_load_gives_focused_framing(self):
        state = PersonaState()
        state.set_state(cognitive_load=0.9)
        bus = SharedMemoryBus(state)
        agent = LogicAgent()

        response = agent.handle(AgentRequest(text="one more thing"), bus)

        self.assertTrue(response.output.startswith("Focusing carefully here"))

    def test_raises_cognitive_load_after_handling(self):
        bus = SharedMemoryBus()
        agent = LogicAgent()

        agent.handle(AgentRequest(text="hi"), bus)

        self.assertAlmostEqual(bus.read().cognitive_load, 0.05)


if __name__ == "__main__":
    unittest.main()
