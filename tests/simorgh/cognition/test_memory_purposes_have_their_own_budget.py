"""Stage 15 follow-up: `memory.summary` and `memory.reconcile` are
purposes of their own, each with a budget row, and that row caps the
purpose over a rolling window -- so a night of summaries is refused
before it reaches the provider day chat shares, and chat is untouched."""

from __future__ import annotations

import unittest

from simorgh.cognition.api import Budget, Purpose
from simorgh.cognition.config import DEFAULT_PURPOSE_BUDGETS, Config as CognitionConfig, ProviderConfig
from simorgh.cognition.providers.base import TEMPLATES
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.registry import get_spec

# The module, not its TestCase: a TestCase imported by name would run its
# tests a second time from here.
from tests.simorgh.cognition import test_service as _base

_FakeProvider = _base._FakeProvider


class MemoryPurposesTest(unittest.IsolatedAsyncioTestCase):
    _make = _base.CognitionServiceTestCase._make

    async def asyncTearDown(self):
        if hasattr(self, "service"):
            await _base.CognitionServiceTestCase.asyncTearDown(self)

    def test_the_purposes_exist_everywhere_a_purpose_must(self):
        allowed = get_spec(topics.COGNITION_THINK).schema["properties"]["purpose"]["enum"]
        for name in ("memory.summary", "memory.reconcile"):
            self.assertIn(name, allowed, "the wire admits it")
            self.assertIn(Purpose(name), TEMPLATES, "the floor has an honest line for it")
            budget = DEFAULT_PURPOSE_BUDGETS[name]
            self.assertIsNotNone(budget.window_max_usd, "a background purpose is capped over the day")
            self.assertIsNotNone(budget.window_max_calls)
        self.assertIsNone(DEFAULT_PURPOSE_BUDGETS["chat"].window_max_usd, "chat keeps the provider's day")

    def test_a_purpose_window_is_read_from_toml(self):
        config = CognitionConfig.from_mapping({"purposes": {"memory.summary": {
            "max_tokens_in": 2000, "max_tokens_out": 100, "max_cost_usd": 0.01, "window_max_calls": 3}}})
        self.assertEqual(config.purposes["memory.summary"].window_max_calls, 3)
        self.assertIn("memory.reconcile", config.purposes, "the other default row is kept")

    async def _ask(self, purpose: str):
        return await self.bus.request(Message.new(topics.COGNITION_THINK, source="test", payload={
            "purpose": purpose, "messages": [{"role": "user", "content": "q"}],
            "budget": {"max_tokens": 100, "max_cost_usd": 0.02}, "require_real_provider": False,
        }), timeout=5.0)

    async def test_a_night_of_summaries_stops_at_its_cap_and_chat_still_answers(self):
        llm = _FakeProvider("fake_llm")
        purposes = dict(DEFAULT_PURPOSE_BUDGETS)
        purposes["memory.summary"] = Budget(4_000, 300, 0.02, window_max_calls=2, window_seconds=3600.0)
        await self._make(providers=[llm], config=CognitionConfig(
            provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
            providers={"fake_llm": ProviderConfig(max_calls=100, window_seconds=3600.0)}, purposes=purposes))
        for _ in range(2):
            reply = await self._ask("memory.summary")
            self.assertIs(reply.payload.get("floor"), False, reply.payload)
        refused = await self._ask("memory.summary")
        self.assertIs(refused.payload.get("ok"), False)
        self.assertEqual(refused.payload["error"]["code"], "budget_exceeded")
        self.assertIn("memory.summary", refused.payload["error"]["detail"])
        self.assertEqual(llm.calls, 2, "the refused call never reached the provider")
        chat = await self._ask("chat")
        self.assertEqual(chat.payload.get("provider"), "fake_llm", "chat is not charged for the summaries")
        reconcile = await self._ask("memory.reconcile")
        self.assertEqual(reconcile.payload.get("provider"), "fake_llm", "each memory purpose has its own window")
        # The window slides: an hour on, the summaries may run again.
        self.clock.advance(3601.0)
        again = await self._ask("memory.summary")
        self.assertEqual(again.payload.get("provider"), "fake_llm")

    async def test_the_window_survives_a_restart(self):
        llm = _FakeProvider("fake_llm")
        purposes = dict(DEFAULT_PURPOSE_BUDGETS)
        purposes["memory.reconcile"] = Budget(4_000, 300, 0.02, window_max_usd=0.0015, window_seconds=3600.0)
        config = CognitionConfig(provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05,
                                 providers={"fake_llm": ProviderConfig(max_calls=100, window_seconds=3600.0)},
                                 purposes=purposes)
        await self._make(providers=[llm], config=config)
        for _ in range(2):    # $0.001 each: the second takes it past $0.0015
            await self._ask("memory.reconcile")
        await self.service.stop()
        from simorgh.cognition.service import Service

        self.service = Service(config=config, providers=[llm])
        await self.service.start(self.ctx)
        refused = await self._ask("memory.reconcile")
        self.assertEqual(refused.payload["error"]["code"], "budget_exceeded", "counted from cognition:calls")
