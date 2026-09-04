import unittest

from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.router import AgentRequest, AgentResponse, Router, SubAgent


class EchoAgent(SubAgent):
    name = "echo"

    def handle(self, request: AgentRequest, bus: SharedMemoryBus) -> AgentResponse:
        bus.publish_delta(self.name, valence=0.1)
        return AgentResponse(agent=self.name, output=request.text.upper())


class TestRouter(unittest.TestCase):
    def test_register_and_dispatch(self):
        router = Router()
        router.register(EchoAgent())

        response = router.dispatch("echo", AgentRequest(text="hi"))

        self.assertEqual(response.agent, "echo")
        self.assertEqual(response.output, "HI")

    def test_dispatch_unknown_agent_raises(self):
        router = Router()
        with self.assertRaises(KeyError):
            router.dispatch("missing", AgentRequest(text="hi"))

    def test_agents_share_the_router_bus(self):
        router = Router()
        router.register(EchoAgent())

        router.dispatch("echo", AgentRequest(text="hi"))

        self.assertAlmostEqual(router.bus.read().valence, 0.1)

    def test_dispatch_many_returns_keyed_responses(self):
        router = Router()
        router.register(EchoAgent())

        responses = router.dispatch_many(["echo"], AgentRequest(text="hi"))

        self.assertEqual(responses["echo"].output, "HI")

    def test_unregister_removes_agent(self):
        router = Router()
        router.register(EchoAgent())
        router.unregister("echo")

        self.assertNotIn("echo", router.agent_names())
        with self.assertRaises(KeyError):
            router.dispatch("echo", AgentRequest(text="hi"))


if __name__ == "__main__":
    unittest.main()
