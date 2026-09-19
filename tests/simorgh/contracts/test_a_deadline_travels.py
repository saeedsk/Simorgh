"""Stage 1 item 5: a deadline travels in the envelope."""

import asyncio
import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message, time_left


class ADeadlineTravels(unittest.IsolatedAsyncioTestCase):
    def test_caused_carries_it_and_json_keeps_it(self):
        m = Message.new(topics.PERCEPT_TEXT_RECEIVED, source="s", payload={"text": "x"}, deadline=100.0)
        c = m.caused(topics.COGNITION_THINK, {"purpose": "chat"}, source="o")
        self.assertEqual(c.deadline, 100.0)
        self.assertEqual(Message.from_json(c.to_json()).deadline, 100.0)
        self.assertEqual(time_left(c, 98.0), 2.0)
        self.assertEqual(time_left(c, 101.0), 0.0)
        self.assertIsNone(time_left(Message.new(topics.PERCEPT_TEXT_RECEIVED, source="s", payload={"text": "x"}), 1.0))

    async def test_a_request_stamps_its_timeout_and_keeps_an_earlier_one(self):
        now = [1000.0]
        backend = make_backend(BusConfig())
        await backend.start()
        client = make_client(backend, source="kernel", clock=lambda: now[0])
        seen = []

        async def _answer(message):
            seen.append(message.deadline)
            await client.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={"items": [], "truncated": False})

        await client.subscribe(topics.MEMORY_RETRIEVE, _answer)
        ask = lambda **kw: Message.new(topics.MEMORY_RETRIEVE, source="kernel", payload={"query": "q", "kinds": ["episodic"], "k": 1}, **kw)  # noqa: E731
        await client.request(ask(), timeout=5.0)
        await client.request(ask(deadline=1002.0), timeout=5.0)
        await client.request(ask(deadline=2000.0), timeout=5.0)
        self.assertEqual(seen, [1005.0, 1002.0, 1005.0])
        await backend.stop()
