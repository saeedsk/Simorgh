"""`Router` (docs/blueprint/subsystems/04-cognition.md section 5): ported
v1 `CognitionRouter` failover shape -- try each configured candidate in
order, skip an unavailable/exhausted/erroring one, fall through to the
floor unless `require_real_provider`."""

from __future__ import annotations

import unittest

from simorgh.cognition.api import Budget, NoRealProvider, ProviderUnavailable, Purpose
from simorgh.cognition.providers.base import FloorProvider
from simorgh.cognition.router import Router
from simorgh.contracts.protocols import ProviderResponse
from tests.simorgh.helpers import FakeClock


class _FakeProvider:
    def __init__(self, name: str, *, available: bool = True, error: Exception | None = None, response: ProviderResponse | None = None):
        self.name = name
        self._available = available
        self._error = error
        self._response = response or ProviderResponse(text=f"{name}-answer", provider=name)
        self.calls = 0

    def available(self) -> bool:
        return self._available

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._response


def _budget(**kw) -> Budget:
    return Budget(max_tokens_in=1_000, max_tokens_out=100, max_cost_usd=1.0, **kw)


class TestRouter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.floor = FloorProvider()

    async def test_picks_the_first_available_candidate_in_order(self):
        primary = _FakeProvider("claude_code_cli")
        secondary = _FakeProvider("gemini")
        router = Router([secondary, primary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertFalse(floor)
        self.assertEqual(response.provider, "claude_code_cli")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(secondary.calls, 0)

    async def test_unavailable_candidate_is_skipped(self):
        primary = _FakeProvider("claude_code_cli", available=False)
        secondary = _FakeProvider("gemini")
        router = Router([primary, secondary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(response.provider, "gemini")
        self.assertEqual(primary.calls, 0)

    async def test_a_raising_candidate_falls_through_to_the_next(self):
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("not logged in"))
        secondary = _FakeProvider("gemini")
        router = Router([primary, secondary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(response.provider, "gemini")
        self.assertFalse(floor)

    async def test_every_candidate_failing_falls_to_the_floor_by_default(self):
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("down"))
        router = Router([primary], {}, self.floor, order=("claude_code_cli",), clock=self.clock)
        response, floor = await router.complete(Purpose.PLAN, [], tools=None, budget=_budget(require_real=False), timeout=5.0)
        self.assertTrue(floor)
        self.assertEqual(response.provider, "floor")
        self.assertIn("[floor]", response.text)

    async def test_require_real_raises_instead_of_falling_to_the_floor(self):
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("down"))
        router = Router([primary], {}, self.floor, order=("claude_code_cli",), clock=self.clock)
        with self.assertRaises(NoRealProvider):
            await router.complete(Purpose.ENSEMBLE, [], tools=None, budget=_budget(require_real=True), timeout=5.0)

    async def test_no_candidates_configured_at_all_still_reaches_the_floor(self):
        router = Router([], {}, self.floor, order=(), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertTrue(floor)

    async def test_candidate_names_lists_order_then_floor(self):
        primary = _FakeProvider("claude_code_cli")
        router = Router([primary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        # "gemini" has no provider instance -- filtered out, unlike "claude_code_cli".
        self.assertEqual(router.candidate_names(), ["claude_code_cli", "floor"])


if __name__ == "__main__":
    unittest.main()
