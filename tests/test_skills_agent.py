import unittest

from src.agents.skills.base import SkillsAgent
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.router import AgentRequest


class TestSkillsAgent(unittest.TestCase):
    def test_successful_skill_raises_cognitive_load_a_little(self):
        agent = SkillsAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="print('42')"), bus)

        self.assertEqual(response.output.strip(), "42")
        self.assertAlmostEqual(bus.read().cognitive_load, 0.05)

    def test_failed_skill_raises_cognitive_load_more_and_reports_stderr(self):
        agent = SkillsAgent()
        bus = SharedMemoryBus()

        response = agent.handle(AgentRequest(text="raise RuntimeError('nope')"), bus)

        self.assertIn("RuntimeError", response.output)
        self.assertAlmostEqual(bus.read().cognitive_load, 0.1)


if __name__ == "__main__":
    unittest.main()
