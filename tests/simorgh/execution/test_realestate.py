"""`search_listings` (execution/realestate.py): real property listings
via the optional `homeharvest` package. Unit tests inject a fake
scraper; one real end-to-end smoke test skips itself unless homeharvest
is installed and the network is reachable."""

from __future__ import annotations

import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.realestate import Listing, RealEstateListingsTool, render, rows_to_listings, zip_in


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def _ctx(clock=None):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                       data_dir=Path.cwd(), clock=clock or _Clock(), logger=None, ledger=None)


ROWS = [
    {"full_street_line": "20791 Via Corta", "city": "San Jose", "zip_code": "95120", "list_price": 4218000,
     "sqft": 5749, "price_per_sqft": 734, "beds": 5, "full_baths": 4, "latitude": 37.2173, "longitude": -121.8215,
     "property_url": "https://www.realtor.com/x"},
    {"full_street_line": "1232 Copper Peak Ln", "city": "San Jose", "zip_code": "95120", "list_price": 1080000,
     "sqft": 1298, "price_per_sqft": None, "beds": 2, "full_baths": 2, "latitude": 37.1954, "longitude": -121.8429,
     "property_url": "https://www.realtor.com/y"},
    {"full_street_line": "7402 Phinney Way", "city": "San Jose", "zip_code": "95139", "list_price": 1000000,
     "sqft": 1479, "price_per_sqft": 676, "beds": 3, "full_baths": 2, "latitude": 37.2217, "longitude": -121.7635,
     "property_url": "https://www.realtor.com/z"},
]


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return list(self._rows)


def _scraper(rows=ROWS, seen: list | None = None):
    def scrape(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        return _FakeFrame(rows)
    return scrape


class ZipInTestCase(unittest.TestCase):
    """Live-caught 2026-09-09, observer W21-11: a real query for
    `location="12345 Main St, Austin, TX"` against homeharvest returned
    200 real Austin listings (zip codes 78745, 78754, 78729, ...), none
    of them "12345" -- but the old unanchored `\\b(\\d{5})\\b` regex read
    the leading street number as a ZIP filter and silently zeroed the
    result out. The ZIP must be read from the end of the string, where a
    real address actually puts it."""

    def test_a_trailing_zip_is_found(self):
        self.assertEqual(zip_in("San Jose, CA 95120"), "95120")

    def test_a_trailing_zip_plus_four_is_found(self):
        self.assertEqual(zip_in("San Jose, CA 95120-1234"), "95120")

    def test_a_leading_street_number_is_not_mistaken_for_a_zip(self):
        self.assertEqual(zip_in("12345 Main St, Austin, TX"), "")

    def test_a_leading_five_digit_street_number_with_no_real_zip(self):
        self.assertEqual(zip_in("10001 Wilshire Blvd, Los Angeles CA"), "")

    def test_no_zip_at_all(self):
        self.assertEqual(zip_in("San Jose, CA"), "")


class RowsToListingsTestCase(unittest.TestCase):
    def test_a_missing_price_per_sqft_is_derived(self):
        listings = rows_to_listings(ROWS)
        self.assertAlmostEqual(listings[1].price_per_sqft, round(1080000 / 1298, 2))

    def test_a_present_price_per_sqft_is_kept_as_is(self):
        self.assertEqual(rows_to_listings(ROWS)[0].price_per_sqft, 734.0)

    def test_nan_values_become_none(self):
        row = dict(ROWS[0], list_price=float("nan"))
        self.assertIsNone(rows_to_listings([row])[0].price)


class RenderTestCase(unittest.TestCase):
    def test_every_result_carries_the_unofficial_source_disclaimer(self):
        text = render(rows_to_listings(ROWS), "San Jose, CA 95120", 3, 3)
        self.assertIn("unofficial", text)
        self.assertIn("NOT a licensed data API", text)
        self.assertIn("NOT Zillow-sourced", text)

    def test_the_filter_note_appears_when_fewer_matched_than_fetched(self):
        text = render(rows_to_listings(ROWS)[:2], "x", 2, 3)
        self.assertIn("of 3 fetched before filtering", text)

    def test_a_listing_line_shows_the_key_facts(self):
        text = render(rows_to_listings(ROWS)[:1], "x", 1, 1)
        self.assertIn("$4,218,000", text)
        self.assertIn("20791 Via Corta", text)
        self.assertIn("5,749 sqft", text)
        self.assertIn("$734/sqft", text)


class ToolTestCase(unittest.IsolatedAsyncioTestCase):
    def _tool(self, scraper=None, **config):
        settings = {"repo_root": Path.cwd()}
        settings.update(config)
        return RealEstateListingsTool(Config(**settings), scraper=scraper or _scraper())

    async def test_it_returns_listings_and_honest_metadata(self):
        result = await self._tool().run({"location": "San Jose, CA"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["total_fetched"], 3)
        self.assertEqual(result.metadata["returned"], 3)
        self.assertIn("unofficial", result.metadata["source"])
        self.assertIn("20791 Via Corta", result.output)

    async def test_a_zip_written_into_the_location_is_the_filter(self):
        """Live-caught by the 2026-09-09 acceptance trial: asked for ZIP
        95120, the model called `search_listings` with the ZIP inside
        `location` and no separate filter. homeharvest matches
        metro-wide, so the page it built was titled 95120 and listed
        properties in 95123, 95116, 95111, 95139 and 95122 -- confident,
        wrong, and mechanically unimpeachable because the *page* was
        fine."""
        result = await self._tool().run({"location": "San Jose, CA 95120"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["zip_code"], "95120")
        self.assertTrue(result.metadata["zip_from_location"])
        self.assertEqual(result.metadata["matched"], 2)
        self.assertNotIn("Phinney", result.output)  # 95139, correctly excluded
        self.assertIn("filtered to ZIP 95120", result.output)
        self.assertIn("taken from the location", result.output)

    async def test_an_explicit_zip_code_beats_the_one_in_the_location(self):
        result = await self._tool().run(
            {"location": "San Jose, CA 95120", "zip_code": "95139"}, ctx=_ctx())
        self.assertEqual(result.metadata["zip_code"], "95139")
        self.assertFalse(result.metadata["zip_from_location"])
        self.assertIn("Phinney", result.output)

    async def test_a_location_with_no_zip_is_not_narrowed(self):
        result = await self._tool().run({"location": "San Jose, CA"}, ctx=_ctx())
        self.assertEqual(result.metadata["zip_code"], "")
        self.assertEqual(result.metadata["matched"], 3)
        self.assertNotIn("filtered to ZIP", result.output)

    async def test_a_zip_code_filters_client_side(self):
        # Live-caught: homeharvest's own location match for "San Jose, CA
        # 95120" returned 1104 rows across many ZIPs, only 50 in 95120.
        result = await self._tool().run({"location": "San Jose, CA", "zip_code": "95120"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["matched"], 2)
        self.assertNotIn("Phinney", result.output)

    async def test_numeric_filters_apply(self):
        result = await self._tool().run(
            {"location": "x", "max_price": 1_500_000, "min_sqft": 1300}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["matched"], 1)
        self.assertIn("Phinney", result.output)

    async def test_max_results_caps_what_comes_back(self):
        result = await self._tool(real_estate_max_results=1).run({"location": "x"}, ctx=_ctx())
        self.assertEqual(result.metadata["matched"], 3)
        self.assertEqual(result.metadata["returned"], 1)

    async def test_an_empty_location_is_refused(self):
        result = await self._tool().run({"location": "  "}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("empty location", result.error)

    async def test_a_scraper_failure_is_a_result_not_a_crash(self):
        def boom(**kwargs):
            raise RuntimeError("realtor.com said no")

        result = await self._tool(scraper=boom).run({"location": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("realtor.com said no", result.error)

    async def test_the_rate_limit_is_its_own_and_refuses_past_the_cap(self):
        clock = _Clock()
        tool = self._tool(real_estate_max_calls=2, real_estate_window_s=60.0)
        for _ in range(2):
            self.assertTrue((await tool.run({"location": "x"}, ctx=_ctx(clock))).ok)
        blocked = await tool.run({"location": "x"}, ctx=_ctx(clock))
        self.assertFalse(blocked.ok)
        self.assertIn("rate limit", blocked.error)
        clock.t = 61.0
        self.assertTrue((await tool.run({"location": "x"}, ctx=_ctx(clock))).ok)


class RealHomeharvestSmokeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_real_query_returns_real_95120_listings(self):
        import importlib.util
        import socket

        if importlib.util.find_spec("homeharvest") is None:
            self.skipTest("homeharvest not installed")
        try:
            socket.gethostbyname("www.realtor.com")
        except socket.gaierror:
            self.skipTest("no network access in this environment")
        tool = RealEstateListingsTool(Config(repo_root=Path.cwd(), real_estate_max_results=5))
        result = await tool.run({"location": "San Jose, CA 95120", "zip_code": "95120"}, ctx=_ctx())
        if not result.ok:
            self.skipTest(f"live source did not answer in this sandbox: {result.error}")
        self.assertGreater(result.metadata["matched"], 0)
        self.assertIn("95120", result.output)
        self.assertIn("unofficial", result.output)

    async def test_a_street_number_that_looks_like_a_zip_is_not_used_as_a_filter(self):
        """Live-caught 2026-09-09, observer W21-11: `location="12345 Main
        St, Austin, TX"` returned 200 real Austin listings, none in ZIP
        "12345" (that's a street number, not a ZIP) -- the old
        unanchored ZIP regex filtered all 200 away to nothing."""
        import importlib.util
        import socket

        if importlib.util.find_spec("homeharvest") is None:
            self.skipTest("homeharvest not installed")
        try:
            socket.gethostbyname("www.realtor.com")
        except socket.gaierror:
            self.skipTest("no network access in this environment")
        tool = RealEstateListingsTool(Config(repo_root=Path.cwd(), real_estate_max_results=5))
        result = await tool.run({"location": "12345 Main St, Austin, TX"}, ctx=_ctx())
        if not result.ok:
            self.skipTest(f"live source did not answer in this sandbox: {result.error}")
        self.assertEqual(result.metadata["zip_code"], "")
        self.assertFalse(result.metadata["zip_from_location"])
        self.assertGreater(result.metadata["total_fetched"], 0)
        self.assertEqual(result.metadata["matched"], result.metadata["total_fetched"])
