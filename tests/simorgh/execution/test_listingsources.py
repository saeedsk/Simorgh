"""`search_listings`' provider layer (execution/listingsources.py).

No test here touches the network: every one injects its own opener or
scraper. What is pinned is the behaviour that has to hold before anyone
configures a key, since that is the state the code ships in.

The load-bearing property is the DISCLAIMER. `search_listings` says in
every result where its data came from, because a caller deciding
whether to trust a price needs to know. When the source can change, the
caveat has to change with it -- a licensed result inheriting the
scraper's "unofficial, can break without warning" would be a lie in the
safe direction, which is still a lie, and would make a caller discount
good data.
"""

from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult
from simorgh.execution import listingsources
from simorgh.execution.config import Config
from simorgh.execution.listingsources import (
    HOMEHARVEST,
    NoSuchProvider,
    choose_provider,
    disclaimer_for,
    split_location,
)
from simorgh.execution.realestate import RealEstateListingsTool


class _Response:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, _n=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    def __init__(self, payload):
        self.payload, self.urls = payload, []

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        self.headers = dict(request.headers)
        return _Response(json.dumps(self.payload).encode())


def _ctx():
    return ToolContext(
        action_id="a1", task_id=None, scope={}, constraints={},
        data_dir=Path("."), clock=None, logger=None, ledger=None,
    )


class ChoosingTestCase(unittest.TestCase):
    def test_with_no_key_at_all_it_still_works(self):
        # Unlike `notify`, this must never refuse for lack of a key --
        # the scraper needs none, so there is always an answer.
        self.assertEqual(choose_provider("auto", {}), HOMEHARVEST)

    def test_a_licensed_key_is_preferred_over_the_scraper(self):
        # The ordering that matters: nobody who pays for RentCast wants
        # their listings still coming from a scraper.
        self.assertEqual(choose_provider("auto", {"RENTCAST_API_KEY": "k"}), "rentcast")

    def test_a_named_provider_without_its_key_is_an_error_not_a_fallback(self):
        # Falling back silently would hand back data from a source the
        # operator did not choose, wearing the wrong disclaimer.
        with self.assertRaises(NoSuchProvider) as caught:
            choose_provider("rentcast", {})
        self.assertIn("RENTCAST_API_KEY", str(caught.exception))

    def test_a_typo_in_the_provider_name_is_caught(self):
        with self.assertRaises(NoSuchProvider):
            choose_provider("rentkast", {"RENTCAST_API_KEY": "k"})

    def test_a_blank_key_does_not_count_as_configured(self):
        self.assertEqual(choose_provider("auto", {"RENTCAST_API_KEY": "  "}), HOMEHARVEST)


class DisclaimerTestCase(unittest.TestCase):
    def test_the_scraper_keeps_its_caveat(self):
        text = disclaimer_for(HOMEHARVEST)
        self.assertIn("unofficial", text)
        self.assertIn("NOT a licensed data API", text)

    def test_a_licensed_provider_does_not_inherit_the_scraper_caveat(self):
        text = disclaimer_for("rentcast")
        self.assertIn("licensed", text)
        self.assertNotIn("unofficial", text)
        self.assertNotIn("scraper", text)

    def test_every_provider_says_something_about_where_the_data_is_from(self):
        for name, _keys, text in listingsources.PROVIDERS:
            with self.subTest(provider=name):
                self.assertTrue(text.strip(), f"{name} would return data with no provenance")

    def test_every_keyed_provider_has_a_fetcher_and_the_scraper_does_not(self):
        for name, keys, _ in listingsources.PROVIDERS:
            with self.subTest(provider=name):
                self.assertEqual(bool(keys), name in listingsources.FETCHERS)


class SplitLocationTestCase(unittest.TestCase):
    def test_the_usual_shape(self):
        self.assertEqual(split_location("San Jose, CA 95120"), ("San Jose", "CA", "95120"))

    def test_a_zip_plus_four(self):
        self.assertEqual(split_location("Austin, TX 78701-1234"), ("Austin", "TX", "78701"))

    def test_partial_inputs_yield_empties_rather_than_guesses(self):
        self.assertEqual(split_location("Austin, TX"), ("Austin", "TX", ""))
        self.assertEqual(split_location("95120"), ("", "", "95120"))
        self.assertEqual(split_location("San Jose"), ("San Jose", "", ""))
        self.assertEqual(split_location(""), ("", "", ""))

    def test_a_leading_street_number_is_not_read_as_a_zip(self):
        # The same defect W21-11 found in `zip_in`: an unanchored match
        # turned a street number into a ZIP and filtered real listings
        # down to zero.
        self.assertEqual(split_location("12345 Main St, Austin, TX"),
                         ("12345 Main St, Austin", "TX", ""))


class EndToEndTestCase(unittest.IsolatedAsyncioTestCase):
    RENTCAST_ROW = {
        "addressLine1": "123 Almaden Rd", "city": "San Jose", "zipCode": "95120",
        "price": 1850000, "squareFootage": 2100, "bedrooms": 4, "bathrooms": 3,
        "latitude": 37.2, "longitude": -121.8, "listingUrl": "https://example.test/1",
    }

    def _tool(self, opener, env, **overrides):
        return RealEstateListingsTool(Config(**overrides), opener=opener, env=env)

    async def test_a_licensed_result_renders_with_the_licensed_disclaimer(self):
        opener = _Opener([self.RENTCAST_ROW])
        result = await self._tool(opener, {"RENTCAST_API_KEY": "k"}).run(
            {"location": "San Jose, CA 95120"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("123 Almaden Rd", result.output)
        self.assertIn("licensed", result.output)
        self.assertNotIn("unofficial", result.output)
        self.assertEqual(result.metadata["provider"], "rentcast")

    async def test_the_api_key_travels_in_a_header_never_the_url(self):
        # A key in a query string ends up in logs, proxies and history.
        opener = _Opener([self.RENTCAST_ROW])
        await self._tool(opener, {"RENTCAST_API_KEY": "secret-key"}).run(
            {"location": "San Jose, CA 95120"}, ctx=_ctx())
        self.assertNotIn("secret-key", opener.urls[0])
        self.assertIn("secret-key", json.dumps(opener.headers))

    async def test_the_structured_parameters_are_sent_not_the_raw_string(self):
        opener = _Opener([])
        await self._tool(opener, {"RENTCAST_API_KEY": "k"}).run(
            {"location": "San Jose, CA 95120"}, ctx=_ctx())
        url = opener.urls[0]
        self.assertIn("city=San+Jose", url)
        self.assertIn("state=CA", url)
        self.assertIn("zipCode=95120", url)

    async def test_a_licensed_result_still_honours_the_filters(self):
        cheap = dict(self.RENTCAST_ROW, price=500000, addressLine1="1 Cheap St")
        opener = _Opener([self.RENTCAST_ROW, cheap])
        result = await self._tool(opener, {"RENTCAST_API_KEY": "k"}).run(
            {"location": "San Jose, CA 95120", "max_price": 1000000}, ctx=_ctx())
        self.assertIn("1 Cheap St", result.output)
        self.assertNotIn("123 Almaden Rd", result.output)

    async def test_rows_reach_the_results_file_the_same_way(self):
        # Nothing downstream should know which provider answered.
        opener = _Opener([self.RENTCAST_ROW])
        result = await self._tool(opener, {"RENTCAST_API_KEY": "k"}).run(
            {"location": "San Jose, CA 95120"}, ctx=_ctx())
        self.assertEqual(len(result.metadata["rows"]), 1)
        self.assertEqual(result.metadata["rows"][0]["zip_code"], "95120")

    async def test_a_provider_failure_is_a_result_not_a_crash(self):
        def _boom(request, timeout=None):
            raise OSError("connection reset")

        result = await self._tool(_boom, {"RENTCAST_API_KEY": "k"}).run(
            {"location": "San Jose, CA"}, ctx=_ctx())
        self.assertIsInstance(result, ToolResult)
        self.assertFalse(result.ok)
        self.assertIn("rentcast", result.error)

    async def test_a_misconfigured_named_provider_refuses_and_names_the_variable(self):
        result = await self._tool(_Opener([]), {}, real_estate_provider="rentcast").run(
            {"location": "San Jose, CA"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("RENTCAST_API_KEY", result.error)

    async def test_with_no_key_it_falls_back_to_the_scraper(self):
        calls = []

        def _scraper(**kwargs):
            calls.append(kwargs)
            return [{"full_street_line": "9 Scraped Way", "city": "San Jose",
                     "zip_code": "95120", "list_price": 1000000}]

        tool = RealEstateListingsTool(Config(), scraper=_scraper, env={})
        result = await tool.run({"location": "San Jose, CA 95120"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("9 Scraped Way", result.output)
        self.assertIn("unofficial", result.output)
        self.assertEqual(result.metadata["provider"], HOMEHARVEST)
        self.assertEqual(len(calls), 1)

    async def test_a_missing_scraper_package_points_at_the_licensed_option(self):
        # The old message named only `pip install homeharvest`. Someone
        # who cannot install it has a second way out and should be told.
        # `None` in sys.modules is what makes an import raise ImportError,
        # whether or not the package is really installed on this machine.
        with unittest.mock.patch.dict("sys.modules", {"homeharvest": None}):
            result = await RealEstateListingsTool(Config(), env={}).run(
                {"location": "San Jose, CA"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("RENTCAST_API_KEY", result.error)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
