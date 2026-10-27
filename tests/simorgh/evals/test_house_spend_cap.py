"""A paid house run's cap sits where cognition reads it (2026-10-27).

`[cognition] max_spend_usd` is a key nothing reads; until this date the
house runner and the house bench wrote only that, so their paid runs were
held by the provider's shipped day budget and nothing smaller."""

import unittest

from simorgh.cognition.config import Config
from simorgh.evals.house.bench import capped_providers


class TheCapIsOnEachProvider(unittest.TestCase):
    def test_cognition_reads_the_cap_and_keeps_the_prices(self):
        tables = capped_providers(("together", "gemini", "floor"), 0.5)
        self.assertNotIn("floor", tables)
        config = Config.from_mapping({"providers": tables})
        shipped = Config().providers
        for name in ("together", "gemini"):
            self.assertEqual(config.providers[name].max_spend_usd, 0.5)
            self.assertEqual(config.providers[name].price_in, shipped[name].price_in)

    def test_a_dialect_rides_along_without_zeroing_the_table(self):
        tables = capped_providers(("together",), 0.5, tool_dialect="markers")
        provider = Config.from_mapping({"providers": tables}).providers["together"]
        self.assertEqual(provider.tool_dialect, "markers")
        self.assertEqual(provider.model, Config().providers["together"].model)


if __name__ == "__main__":
    unittest.main()
