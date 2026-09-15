"""Per-purpose routes and a strong tier (long-run design section 7)."""

from __future__ import annotations

import unittest

from simorgh.cognition.api import Purpose
from simorgh.cognition.config import Config
from simorgh.cognition.providers.base import FloorProvider
from simorgh.cognition.providers.together import TogetherProvider
from simorgh.cognition.router import Router
from tests.simorgh.cognition.test_router import _FakeProvider, _budget
from tests.simorgh.helpers import FakeClock


class RoutesConfig(unittest.TestCase):
    def test_routes_and_extra_instances_load_from_config(self):
        cfg = Config.from_mapping({
            "providers": {"together_strong": {"backend": "together", "model": "zai-org/GLM-5.3",
                                              "reasoning_effort": "medium", "price_in": 1.4, "price_out": 4.4}},
            "routes": {"draft": ["together_strong"], "strong": ["together_strong"]},
        })
        self.assertEqual(cfg.routes["draft"], ("together_strong",))
        strong = cfg.providers["together_strong"]
        self.assertEqual((strong.backend, strong.model, strong.reasoning_effort), ("together", "zai-org/GLM-5.3", "medium"))
        self.assertIn("together", cfg.providers, "the default provider is kept")
        self.assertEqual(Config().routes, {}, "no routes by default")


class RouterOrderPerCall(unittest.IsolatedAsyncioTestCase):
    async def test_a_call_may_carry_its_own_order(self):
        cheap, strong = _FakeProvider("cheap"), _FakeProvider("strong")
        router = Router([cheap, strong], {}, FloorProvider(), order=("cheap", "strong"), clock=FakeClock())
        default, _ = await router.complete(Purpose.DRAFT, [], tools=None, budget=_budget(), timeout=30.0)
        self.assertEqual(default.provider, "cheap")
        routed, _ = await router.complete(Purpose.DRAFT, [], tools=None, budget=_budget(), timeout=30.0,
                                          order=("strong", "cheap"))
        self.assertEqual(routed.provider, "strong")


class TogetherInstance(unittest.TestCase):
    def test_an_extra_instance_has_its_own_name_and_prices(self):
        strong = TogetherProvider(api_key="k", model="zai-org/GLM-5.3", name="together_strong", price_in=1.4, price_out=4.4)
        self.assertEqual(strong.name, "together_strong")
        self.assertAlmostEqual(strong._bill(1_000_000, 0, 0), 1.4)
        self.assertAlmostEqual(TogetherProvider(api_key="k")._bill(1_000_000, 1_000_000, 0), 0.65, "defaults unchanged")
        self.assertEqual(TogetherProvider(api_key="k").name, "together")


if __name__ == "__main__":
    unittest.main()
