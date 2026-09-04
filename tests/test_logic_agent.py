import unittest

from src.agents.logic.base import LogicAgent
from src.cognition.provider import CognitionRouter, LLMResponse, ProviderUnavailable
from src.memory.short_term import ShortTermMemory
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.persona_state import PersonaState
from src.orchestrator.router import AgentRequest


class FakeProvider:
    def __init__(self, name="fake", text="a real llm reply", raises=None):
        self.name = name
        self._text = text
        self._raises = raises
        self.prompts = []

    def available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        return LLMResponse(text=self._text, provider_name=self.name)


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


class TestLogicAgentWithCognition(unittest.TestCase):
    def test_uses_llm_response_when_a_real_provider_answers(self):
        fake = FakeProvider(text="Hi! Great to hear from you.")
        agent = LogicAgent(cognition=CognitionRouter([fake]))
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Hi! Great to hear from you.")
        self.assertEqual(response.metadata["source"], "llm")

    def test_falls_back_to_rule_based_when_provider_raises(self):
        fake = FakeProvider(raises=ProviderUnavailable("down"))
        agent = LogicAgent(cognition=CognitionRouter([fake]))
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Here's my take: hello")
        self.assertEqual(response.metadata["source"], "rule_based")

    def test_falls_back_to_rule_based_when_only_the_deterministic_floor_answers(self):
        # CognitionRouter() with no real providers -> deterministic_fallback
        agent = LogicAgent(cognition=CognitionRouter())
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Here's my take: hello")
        self.assertEqual(response.metadata["source"], "rule_based")

    def test_prompt_includes_persona_and_mood(self):
        fake = FakeProvider()
        agent = LogicAgent(cognition=CognitionRouter([fake]))
        bus = SharedMemoryBus()

        agent.handle(AgentRequest(text="hello"), bus)

        prompt = fake.prompts[0]
        self.assertIn("Sim", prompt)
        self.assertIn("valence", prompt)
        self.assertIn("hello", prompt)

    def test_prompt_includes_recent_history_when_short_term_given(self):
        fake = FakeProvider()
        short_term = ShortTermMemory()
        short_term.add("what's your name", "I'm Sim.")
        agent = LogicAgent(cognition=CognitionRouter([fake]), short_term=short_term)
        bus = SharedMemoryBus()

        agent.handle(AgentRequest(text="nice to meet you"), bus)

        prompt = fake.prompts[0]
        self.assertIn("what's your name", prompt)
        self.assertIn("I'm Sim.", prompt)

    def test_without_cognition_behaves_exactly_as_before(self):
        agent = LogicAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="hello"), bus)

        self.assertEqual(response.output, "Here's my take: hello")
        self.assertEqual(response.metadata["source"], "rule_based")


if __name__ == "__main__":
    unittest.main()
