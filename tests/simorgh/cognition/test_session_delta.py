"""Stage 3 item 2: a streamed reply reaches the bus as session.delta, and a
reply that turns out to be a tool call is taken back."""

import asyncio
import dataclasses
import unittest

from simorgh.cognition.config import Config as CognitionConfig, ProviderConfig
from simorgh.cognition.providers.streaming import STOP, TEXT, Delta
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse

from .test_service import CognitionServiceTestCase


class _Streamer:
    def __init__(self, pieces):
        self.name, self._pieces = "s", pieces

    def available(self):
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        return ProviderResponse(text="".join(self._pieces), provider=self.name)

    async def stream(self, messages, *, tools, max_tokens, timeout=None):
        for piece in self._pieces:
            yield Delta(TEXT, text=piece)
        yield Delta(STOP)


class ASessionDelta(CognitionServiceTestCase):
    async def _stream(self, pieces, *, stream=True):
        base = CognitionConfig()
        config = dataclasses.replace(base, provider_order=("s", "floor"), assembly_request_timeout=0.05,
                                     providers={**base.providers, "s": ProviderConfig(max_calls=10)})
        await self._make(providers=[_Streamer(pieces)], config=config)
        seen = []

        async def _on(message):
            seen.append(message.payload)

        await self.bus.subscribe(topics.SESSION_DELTA, _on)
        reply = await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}], "tools": ["read_file"],
            "expected": "tool_calls", "budget": {"max_tokens": 1000, "max_cost_usd": 0.1},
            "require_real_provider": False, **({"stream": True, "stream_to": "conv-1"} if stream else {})}),
            timeout=5.0)
        await asyncio.sleep(0.05)
        return seen, reply.payload

    async def test_prose_streams_to_the_session(self):
        seen, reply = await self._stream(["It is ", "three o'clock."])
        self.assertEqual("".join(d["text"] for d in seen), "It is three o'clock.")
        self.assertEqual({d["session_id"] for d in seen}, {"conv-1"})
        self.assertEqual(reply["text"], "It is three o'clock.")

    async def test_a_tool_call_after_a_preamble_is_taken_back(self):
        seen, reply = await self._stream(["Let me look.\n", "READ_FILE: docs/a.md"])
        self.assertTrue(seen[-1].get("reset"))
        self.assertEqual(reply["tool_calls"][0]["tool"], "read_file")

    async def test_nothing_streams_unless_asked(self):
        seen, _ = await self._stream(["hello"], stream=False)
        self.assertEqual(seen, [])
