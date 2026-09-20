"""Stage 3 item 7: a one-line bridge before a slow turn.

A `patch` or `research` turn can take a minute before it says anything.
The bridge is one short line streamed while the real reply is still
being written -- "I'll look at the failing test" -- so the person knows
Sim started.

The rule that matters, and the acceptance case, is that it is **never
the answer**: it is not appended to `session.messages`, it is not the
outcome's text, and a session that ran ten steps says it once. A bridge
that could end up in the transcript would be a turn Sim answered
without thinking.
"""

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration.session import SessionRunner


class _Profile:
    def __init__(self, scaffold):
        self.scaffold = scaffold
        self.name = scaffold
        self.tools = ()


class _Session:
    def __init__(self, scaffold="patch", task_id="t1"):
        self.profile = _Profile(scaffold)
        self.task_id = task_id
        self.trace = "tr1"
        self.messages: list[dict] = []


class _Bus:
    source = "orchestration"

    def __init__(self, text="I'll look at the failing test."):
        self.requests: list[Message] = []
        self._text = text

    async def request(self, message, timeout=None):
        self.requests.append(message)
        return Message.new(topics.COGNITION_THINK + ".reply", source="cognition",
                           payload={"text": self._text})


def _runner(bus, *, on=True) -> SessionRunner:
    runner = SessionRunner.__new__(SessionRunner)
    runner._bus = bus            # noqa: SLF001
    runner._bridge_on = on       # noqa: SLF001
    runner._bridge_timeout_s = 2.0  # noqa: SLF001
    runner._bridged = set()      # noqa: SLF001
    return runner


class TheBridge(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_turn_gets_one_line(self):
        bus = _Bus()
        session = _Session("patch")
        said = await _runner(bus)._bridge(session, "fix the failing test")  # noqa: SLF001
        self.assertEqual(said, "I'll look at the failing test.")
        self.assertEqual(len(bus.requests), 1)

    async def test_it_is_not_recorded_as_the_turn_text(self):
        """The acceptance case: nothing about the bridge reaches the
        transcript the model or the ledger will read back."""
        bus = _Bus()
        session = _Session("patch")
        await _runner(bus)._bridge(session, "fix the failing test")  # noqa: SLF001
        self.assertEqual(session.messages, [], "the bridge is said, not remembered")

    async def test_a_chat_turn_gets_nothing(self):
        bus = _Bus()
        said = await _runner(bus)._bridge(_Session("chat"), "hello")  # noqa: SLF001
        self.assertEqual(said, "")
        self.assertEqual(bus.requests, [], "a chat turn is already fast")

    async def test_once_per_session_however_many_steps(self):
        bus = _Bus()
        runner, session = _runner(bus), _Session("research")
        for _ in range(5):
            await runner._bridge(session, "find out who makes these")  # noqa: SLF001
        self.assertEqual(len(bus.requests), 1)

    async def test_off_by_default(self):
        bus = _Bus()
        said = await _runner(bus, on=False)._bridge(_Session("patch"), "fix it")  # noqa: SLF001
        self.assertEqual(said, "")
        self.assertEqual(bus.requests, [], "a second model call per turn is opt-in")

    async def test_it_asks_for_a_real_provider_and_almost_no_tokens(self):
        """A canned line in Sim's voice from the floor would be worse
        than silence, and a bridge that costs real money is not cheap."""
        bus = _Bus()
        await _runner(bus)._bridge(_Session("patch"), "fix the failing test")  # noqa: SLF001
        payload = bus.requests[0].payload
        self.assertTrue(payload["require_real_provider"])
        self.assertLessEqual(payload["budget"]["max_tokens"], 32)
        self.assertEqual(payload["tools"], [])
        self.assertTrue(payload["stream"], "it is shown while the real reply is written")

    async def test_a_model_that_does_not_answer_costs_the_turn_nothing(self):
        class _Dead(_Bus):
            async def request(self, message, timeout=None):
                raise TimeoutError("no answer")

        said = await _runner(_Dead())._bridge(_Session("patch"), "fix it")  # noqa: SLF001
        self.assertEqual(said, "")


if __name__ == "__main__":
    unittest.main()
