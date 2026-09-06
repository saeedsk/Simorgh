"""Cognition `Service`, over a real (memory-backend) Bus/Ledger and a
real Context -- the same composition shape the Kernel uses, built by
hand here so this package's tests don't depend on `simorgh.kernel`
(boundary rule; see `tests/simorgh/worldmodel/test_service.py` for the
same pattern used elsewhere in this repo). A fake `Provider` (not a real
CLI/API call) stands in as `providers=[...]` -- the constructor seam
`simorgh/cognition/service.py` adds specifically for this."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.cognition.config import Config as CognitionConfig, ProviderConfig
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
    async def _make(self, *, providers=None, config=None):
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
        config = config or CognitionConfig(
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

    async def test_compact_request_honors_allow_summarize_and_calls_the_real_provider(self):
        # 04 section 3.3: "Never calls a model unless allow_summarize:true"
        # -- this is the opt-in path, exercised end to end through the
        # real Router (purpose=consolidate) rather than a hardcoded False.
        # `collapse_keep_full_segments=1` leaves real "older" content for
        # layer 5 to fold -- the default (4) would let layer 2's snip
        # alone bring 5 segments down to exactly 4, leaving nothing left
        # to summarize.
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
            collapse_keep_full_segments=1,
        )
        await self._make(providers=[_FakeProvider(text="SUMMARY: consolidated")], config=config)
        messages = [{"role": "user", "content": " ".join(f"w{i}" for i in range(500))} for _ in range(5)]
        request = Message.new(topics.COGNITION_COMPACT_REQUEST, source="test", payload={
            "session_id": "s1", "target_tokens": 5, "messages": messages, "allow_summarize": True,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertIn("5", reply.payload["layers_applied"])
        self.assertIsNotNone(reply.payload["summary_ref"])

    async def test_compaction_pipeline_reports_the_reply_compaction_block(self):
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05, tool_result_max_tokens=50,
        )
        await self._make(providers=[_FakeProvider(text="ok")], config=config)
        messages = [{"role": "tool", "name": "search", "content": " ".join(f"w{i}" for i in range(500))}]
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": messages,
            "budget": {"max_tokens": 1_000, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertIn(1, [int(n) for n in reply.payload["compaction"]["layers_applied"]])
        self.assertIn("budget", reply.payload)
        self.assertTrue(reply.payload["budget"]["within_budget"])

    async def test_context_too_large_when_a_protected_block_alone_exceeds_the_budget(self):
        await self._make(providers=[_FakeProvider()])
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "x" * 10_000}],
            "budget": {"max_tokens": 1, "max_cost_usd": 0.1}, "require_real_provider": False,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "context_too_large")

    async def test_context_too_large_when_elastic_content_still_cannot_fit_after_all_layers(self):
        # Distinct from the "protected block alone" case above: here the
        # budget comfortably covers the protected blocks, but even after
        # every compaction layer the elastic content is still over --
        # protected means protected (principle 4.6), so this fails loudly
        # rather than truncating.
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05, collapse_keep_full_segments=1,
        )
        await self._make(providers=[_FakeProvider()], config=config)
        # No spaces at all -- layer 1's line-based preview and layer 3's
        # whitespace stripping have nothing to work with, and it's the
        # sole (therefore always-newest, never-headlined) segment.
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "x" * 4_000}],
            "budget": {"max_tokens": 60, "max_cost_usd": 0.1}, "require_real_provider": False,
            "allow_summarize": False,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "context_too_large")

    async def test_budget_exceeded_when_the_requests_own_cost_ceiling_cannot_be_met(self):
        # Per-call budget accounting (04 section 7): Cognition refuses to
        # overspend a single request's own stated budget, distinct from
        # "no real provider available."
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
            providers={"fake_llm": ProviderConfig(price_in=1_000_000.0, price_out=1_000_000.0)},
        )
        await self._make(providers=[_FakeProvider()], config=config)
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": [{"role": "user", "content": "hi"}],
            "budget": {"max_tokens": 1000, "max_cost_usd": 0.0000001}, "require_real_provider": True,
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertFalse(reply.payload["ok"])
        self.assertEqual(reply.payload["error"]["code"], "budget_exceeded")

    async def test_compact_pre_and_done_events_fire_when_a_think_call_needs_layer_5(self):
        seen: list[str] = []

        async def _on_pre(message):
            seen.append("pre")

        async def _on_done(message):
            seen.append("done")

        # `snip_keep_last_segments` larger than the message count makes
        # layer 2 a no-op, so layer 4's per-segment headlines (each ~7
        # tokens, independent of the original content's size) are what
        # actually needs shrinking further -- many small headlines still
        # add up past a tight budget, but folding them into one summary
        # (layer 5) comfortably fits alongside the untouched newest turn.
        config = CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
            collapse_keep_full_segments=1, snip_keep_last_segments=100,
        )
        await self._make(providers=[_FakeProvider(text="SUMMARY: consolidated")], config=config)
        await self.bus.subscribe(topics.COGNITION_COMPACT_PRE, _on_pre)
        await self.bus.subscribe(topics.COGNITION_COMPACT_DONE, _on_done)

        older = [{"role": "user", "content": " ".join(f"w{i}" for i in range(30))} for _ in range(15)]
        messages = older + [{"role": "user", "content": "the newest turn"}]
        request = Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": messages,
            "budget": {"max_tokens": 123, "max_cost_usd": 0.1}, "require_real_provider": False,
            "allow_summarize": True, "session_id": "s1",
        })
        reply = await self.bus.request(request, timeout=5.0)
        self.assertNotIn("error", reply.payload)
        self.assertIn(5, [int(n) for n in reply.payload["compaction"]["layers_applied"]])
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(seen, ["pre", "done"])


if __name__ == "__main__":
    unittest.main()
