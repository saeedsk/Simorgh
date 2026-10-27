"""Stage 17 item 1: every think records, on its `cognition.provider_call`
span, the input split by block (prefix, tools, memory, question, window,
results), estimated with `estimate_tokens` (chars/4), beside the
provider's own `tokens_in` and `tokens_cached`."""

from __future__ import annotations

import dataclasses
import unittest
from contextlib import asynccontextmanager

from simorgh.cognition.api import Capabilities
from simorgh.cognition.config import Config as CognitionConfig, ProviderConfig
from simorgh.cognition.tokens import BLOCKS, ESTIMATOR, estimate_tokens, split_messages
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ProviderResponse

from .test_service import CognitionServiceTestCase


class _Span:
    def __init__(self, name, attrs):
        self.name, self.attrs = name, dict(attrs or {})
        self.trace_id, self.span_id, self.parent_id = "", "", None

    def set(self, key, value):
        self.attrs[key] = value


class _Telemetry:
    def __init__(self):
        self.spans = []

    @asynccontextmanager
    async def span(self, name, *, trace_id, parent_id=None, attrs=None):
        span = _Span(name, attrs)
        self.spans.append(span)
        yield span

    def sample(self, *a, **k):
        return None

    def event(self, *a, **k):
        return None

    async def query(self, trace_id):
        return []


class _Provider:
    capabilities = Capabilities(supports_tools=True)

    def __init__(self, name="p"):
        self.name = name
        self.seen = []

    def available(self):
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.seen.append((messages, tools))
        return ProviderResponse(text="ok", provider=self.name, cost_usd=0.0, input_tokens=1234,
                                output_tokens=5, cached_input_tokens=800)


class TheSplitOfMessages(unittest.TestCase):
    def test_each_message_lands_in_one_block(self):
        messages = [
            {"role": "system", "content": "m" * 40},                       # memory
            {"role": "user", "content": "q" * 20, "protected": True},       # question
            {"role": "assistant", "content": "READ_FILE: a.py"},            # window
            {"role": "user", "content": "Result of read_file:\n" + "x" * 79},  # results
            {"role": "tool", "tool_call_id": "c1", "content": "y" * 40},    # results
        ]
        split = split_messages(messages)
        self.assertEqual(split["memory"], 10)
        self.assertEqual(split["question"], 5)
        self.assertEqual(split["window"], estimate_tokens("READ_FILE: a.py"))
        self.assertEqual(split["results"], 25 + 10)

    def test_without_a_protected_turn_the_first_plain_user_turn_is_the_question(self):
        split = split_messages([{"role": "user", "content": "Result of x:\n1"},
                                {"role": "user", "content": "do it"}, {"role": "user", "content": "more"}])
        self.assertEqual(split["question"], estimate_tokens("do it"))
        self.assertEqual(split["window"], estimate_tokens("more"))


class TheProviderCallSpanCarriesTheSplit(CognitionServiceTestCase):
    async def _think(self, *, native: bool):
        provider = _Provider()
        base = CognitionConfig()
        config = dataclasses.replace(base, provider_order=("p", "floor"), assembly_request_timeout=0.05, providers={
            **base.providers, "p": ProviderConfig(max_calls=10, window_seconds=3600.0,
                                                  **({"tool_dialect": "native"} if native else {}))})
        await self._make(providers=[provider], config=config)
        telemetry = _Telemetry()
        self.service._ctx = dataclasses.replace(self.ctx, telemetry=telemetry)
        messages = [{"role": "system", "content": "Things you remember:\n" + "m" * 200},
                    {"role": "user", "content": "what is on?", "protected": True}]
        await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": "chat", "messages": messages, "tools": ["web_search", "remember"],
            "expected": "tool_calls", "task_rules": "Answer briefly.", "channel": "voice",
            "budget": {"max_tokens": 500, "max_cost_usd": 0.1}, "require_real_provider": False,
        }), timeout=5.0)
        (span,) = [s for s in telemetry.spans if s.name == "cognition.provider_call"]
        return span, provider, messages

    async def test_marker_dialect(self):
        span, provider, messages = await self._think(native=False)
        attrs = span.attrs
        self.assertEqual(attrs["tokens_in"], 1234)
        self.assertEqual(attrs["tokens_cached"], 800)
        self.assertEqual(attrs["estimator"], ESTIMATOR)
        self.assertEqual(attrs["channel"], "voice")
        split = attrs["split"]
        self.assertEqual(tuple(split), BLOCKS)
        sent, _tools = provider.seen[0]
        system = [m["content"] for m in sent if m["role"] == "system"]
        self.assertEqual(len(system), 2)
        # The protected blocks are estimated one by one, so the joined text
        # differs by the separators' rounding at most.
        self.assertAlmostEqual(split["prefix"], estimate_tokens(system[0]), delta=3)
        self.assertIn("Answer briefly.", system[0])
        self.assertEqual(split["tools"], estimate_tokens(system[-1]))
        self.assertIn("WEB_SEARCH", system[-1])
        self.assertEqual(split["memory"], estimate_tokens(messages[0]["content"]))
        self.assertGreater(split["question"], 0)
        self.assertEqual(split["results"], 0)

    async def test_native_dialect_counts_the_schemas(self):
        native, _, _ = await self._think(native=True)
        await self.asyncTearDown()
        marker, _, _ = await self._think(native=False)
        self.assertGreater(native.attrs["split"]["tools"], marker.attrs["split"]["tools"])
        self.assertEqual(native.attrs["split"]["prefix"], marker.attrs["split"]["prefix"])


if __name__ == "__main__":
    unittest.main()
