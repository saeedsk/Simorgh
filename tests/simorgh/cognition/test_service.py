"""Cognition `Service`, over a real (memory-backend) Bus/Ledger and a
real Context -- the same composition shape the Kernel uses, built by
hand here so this package's tests don't depend on `simorgh.kernel`
(boundary rule; see `tests/simorgh/worldmodel/test_service.py` for the
same pattern used elsewhere in this repo). A fake `Provider` (not a real
CLI/API call) stands in as `providers=[...]` -- the constructor seam
`simorgh/cognition/service.py` adds specifically for this."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.cognition.config import Config as CognitionConfig
from simorgh.cognition.service import Service
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, ProviderResponse
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class _FakeProvider:
    def __init__(self, name: str = "fake_llm", *, text: str = "the real answer", raises: Exception | None = None):
        self.name = name
        self._text = text
        self._raises = raises
        self.calls = 0

    def available(self) -> bool:
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return ProviderResponse(text=self._text, provider=self.name, input_tokens=10, output_tokens=5, cost_usd=0.001)


class CognitionServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def _make(self, *, providers=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="cognition", ledger=self.ledger, clock=self.clock)
        await self.bus.start()

        self.ctx = Context(
            name="cognition", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
        )
        self.service = Service(config=config, providers=providers)
        await self.service.start(self.ctx)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        self._tmp.cleanup()

    async def test_think_with_a_fake_provider_returns_its_answer_not_the_floor(self):
        await self._make(providers=[_FakeProvider(text="42")])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "what is the answer"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertEqual(reply.payload["text"], "42")
        self.assertEqual(reply.payload["provider"], "fake_llm")
        self.assertFalse(reply.payload["floor"])
        self.assertFalse(reply.payload["non_answer"])

    async def test_think_with_no_real_provider_returns_an_honest_floor_reply(self):
        await self._make(providers=[])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertTrue(reply.payload["floor"])
        self.assertEqual(reply.payload["provider"], "floor")
        self.assertIn("[floor]", reply.payload["text"])

    async def test_require_real_provider_with_none_available_is_an_honest_error_not_a_fabrication(self):
        await self._make(providers=[])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": True,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "no_real_provider")
        self.assertTrue(reply.payload["error"]["retryable"])

    async def test_tool_calls_expected_kind_maps_the_wire_tools_list_to_markers(self):
        await self._make(providers=[_FakeProvider(text="READ: src/foo.py\nbecause it's relevant")])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "find the bug"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
            "expected": "tool_calls", "tools": ["READ", "DRAFT"],
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertEqual(reply.payload["tool_calls"], [{"tool": "read", "args": {"argument": "src/foo.py"}}])

    async def test_edit_blocks_expected_kind_parses_search_replace(self):
        text = "<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE\n"
        await self._make(providers=[_FakeProvider(text=text)])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "draft", "messages": [{"role": "user", "content": "fix it"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
            "expected": "edit_blocks",
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertEqual(reply.payload["edit_blocks"], [{"search": "foo", "replace": "bar"}])

    async def test_verdict_expected_kind_non_answer_is_reported_not_a_false_rejection(self):
        await self._make(providers=[_FakeProvider(text="I need more information before I can decide.")])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "review", "messages": [{"role": "user", "content": "is this correct?"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
            "expected": "verdict",
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertTrue(reply.payload["non_answer"])

    async def test_invalid_purpose_is_a_clean_error_not_a_crash(self):
        await self._make(providers=[])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "bogus", "messages": [], "budget": {"max_tokens": 1000, "max_cost_usd": 0.1},
            "require_real_provider": False,
        })
        with self.assertRaises(Exception):
            # "purpose" isn't even a valid wire enum value -- caught by contract
            # validation before it reaches the handler at all.
            await self.bus.request(request, timeout=5.0)

    async def test_paused_state_rejects_think_requests_until_resumed(self):
        await self._make(providers=[_FakeProvider()])
        await self.bus.publish(Message.new(topics.SYSTEM_STATE_CHANGED, source="test", payload={
            "state": "paused", "reason": "test",
        }))
        for _ in range(5):
            import asyncio
            await asyncio.sleep(0)
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "paused")

    async def test_compact_request_returns_layers_and_token_counts(self):
        await self._make(providers=[])
        request = Message.new(topics.COGNITION_COMPACT_REQUEST, source="test", payload={
            "session_id": "s1", "target_tokens": 10_000,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertIn("layers_applied", reply.payload)
        self.assertIn("tokens_before", reply.payload)


if __name__ == "__main__":
    unittest.main()
