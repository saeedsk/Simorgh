"""`search_listings`: real, current for-sale (or for-rent) property data
via the `homeharvest` package (github.com/Bunsly/HomeHarvest) -- an
actively-maintained open-source library that reads Realtor.com's own
site backend the way a browser does. This is deliberately NOT a
hand-rolled scraper: the creator, 2026-09-07, wants external toolset
libraries reused rather than reinvented, with Guardian seeing every
call and the dependency staying optional -- exactly the shape this
fills.

This closes the gap the 2026-09-09 real-estate-app experiment
surfaced: asked to build a San Jose 95120 listings browser with data
matching Zillow/Realtor.com, Sim correctly refused to fabricate data
and built the UI against clearly-labeled sample data instead, since no
listings source was configured. Live-tested here the same day: a real
query for "San Jose, CA 95120" returned real Almaden Valley street
addresses, prices, and coordinates.

Two things worth saying plainly, and said in every result's own text
(not just in this docstring):

- **Unofficial.** `homeharvest` reads Realtor.com's internal endpoints,
  not a published/licensed data API -- it can break or get rate-limited
  with no warning, the same caveat that applies to any scraper, however
  well-maintained. It is NOT Zillow-sourced (Zillow's backend is far
  more defended); a caller who needs Zillow-parity should say so and
  verify manually, not assume this tool covers it.
- **Broad by default.** `location="San Jose, CA 95120"` alone returns
  listings across many San Jose ZIP codes, not just 95120 (live-tested:
  1104 rows for the metro query, 50 of them actually in 95120) --
  `zip_code` here filters the results client-side after fetching, since
  homeharvest's own location matching doesn't narrow that precisely.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass

from simorgh.contracts.protocols import ToolContext, ToolResult

from . import listingsources
from .config import Config

# Kept as a name for the tests and callers that already import it; the
# real source of truth is `listingsources.disclaimer_for(provider)`,
# because the caveat has to change when the data does.
_DISCLAIMER = listingsources.SCRAPER_DISCLAIMER


class ListingsUnavailable(Exception):
    """No search was run: the dependency is missing, the request was
    malformed, or the rate limit was already spent."""


@dataclass(frozen=True)
class Listing:
    address: str
    city: str
    zip_code: str
    price: float | None
    sqft: float | None
    price_per_sqft: float | None
    beds: float | None
    baths: float | None
    latitude: float | None
    longitude: float | None
    url: str

    def render(self, index: int) -> str:
        money = f"${self.price:,.0f}" if self.price is not None else "price unknown"
        size = f"{self.sqft:,.0f} sqft" if self.sqft is not None else "sqft unknown"
        ppsf = f"${self.price_per_sqft:,.0f}/sqft" if self.price_per_sqft is not None else ""
        beds_baths = ""
        if self.beds is not None or self.baths is not None:
            beds_baths = f"{self.beds or '?'}bd/{self.baths or '?'}ba"
        detail = " · ".join(p for p in (size, ppsf, beds_baths) if p)
        loc = f" ({self.latitude:.5f}, {self.longitude:.5f})" if self.latitude is not None and self.longitude is not None else ""
        return f"{index}. {money} -- {self.address}, {self.city} {self.zip_code}\n   {detail}{loc}"


def _num(row, key):
    value = row.get(key)
    try:
        return float(value) if value is not None and value == value else None  # NaN != NaN
    except (TypeError, ValueError):
        return None


def rows_to_listings(rows: list[dict]) -> list[Listing]:
    listings = []
    for row in rows:
        price = _num(row, "list_price")
        sqft = _num(row, "sqft")
        ppsf = _num(row, "price_per_sqft")
        if ppsf is None and price is not None and sqft:
            ppsf = round(price / sqft, 2)
        listings.append(Listing(
            address=str(row.get("full_street_line") or row.get("street") or "unknown address"),
            city=str(row.get("city") or ""),
            zip_code=str(row.get("zip_code") or ""),
            price=price, sqft=sqft, price_per_sqft=ppsf,
            beds=_num(row, "beds"), baths=_num(row, "full_baths"),
            latitude=_num(row, "latitude"), longitude=_num(row, "longitude"),
            url=str(row.get("property_url") or ""),
        ))
    return listings


# Anchored to the end of the string (a real address's ZIP is its last
# token: "San Jose, CA 95120", "Austin, TX 78701-1234"), not anywhere in
# it. An unanchored `\b(\d{5})\b` also matches a leading street number --
# live-caught 2026-09-09, observer W21-11: `location="12345 Main St,
# Austin, TX"` extracted "12345" as the ZIP (the street number, not a
# ZIP at all) and silently filtered 200 real Austin listings down to
# zero, because none of them happen to carry ZIP 12345. Anchoring to the
# end fixes that case (the string ends in "TX", not digits) while still
# matching every real trailing-ZIP location.
_ZIP_RE = re.compile(r"(?<!\d)(\d{5})(?:-\d{4})?\s*$")


def zip_in(location: str) -> str:
    """The 5-digit ZIP at the end of a location string, or "".

    Live-caught 2026-09-09, the acceptance trial: asked for ZIP 95120,
    the model called `search_listings` with `location="San Jose, CA
    95120"` and no `zip_code` filter. homeharvest's own location match
    is metro-wide, so the page it built was titled 95120 and listed
    properties in 95123, 95116, 95111, 95139 and 95122 -- wrong data,
    presented confidently, with every mechanical check passing because
    the *page* was fine. Writing the ZIP where a human would write it
    must not silently mean "ignore it": it is now the filter unless the
    caller says otherwise.

    Anchored to the end of the string so a leading street number that
    happens to be 5 digits (see the module docstring's caveat above)
    is never mistaken for it.
    """
    match = _ZIP_RE.search((location or "").strip())
    return match.group(1) if match else ""


def render(listings: list[Listing], location: str, matched: int, total: int,
           *, zip_code: str = "", implied_zip: bool = False, disclaimer: str = "") -> str:
    header = f"{matched} listing(s) for {location!r}"
    if zip_code:
        header += f", filtered to ZIP {zip_code}"
        if implied_zip:
            header += " (taken from the location -- pass zip_code to override)"
    if matched != total:
        header += f" (of {total} fetched before filtering)"
    header += f" -- {disclaimer or _DISCLAIMER}"
    if not listings:
        return header
    body = "\n".join(listing.render(index) for index, listing in enumerate(listings, start=1))
    return f"{header}:\n{body}"


class RealEstateListingsTool:
    name = "search_listings"
    description = (
        "Search real, current for-sale property listings by location (city/ZIP), with optional "
        "price/sqft/bed filters. Unofficial data source -- see the tool's output disclaimer."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object", "required": ["location"],
        "properties": {
            "location": {"type": "string"},
            "zip_code": {"type": "string"},
            "min_price": {"type": "number"}, "max_price": {"type": "number"},
            "min_sqft": {"type": "number"}, "max_sqft": {"type": "number"},
            "min_price_per_sqft": {"type": "number"}, "max_price_per_sqft": {"type": "number"},
        },
    }

    def __init__(self, config: Config, *, scraper=None, opener=None, env=None) -> None:
        self._config = config
        self._scraper = scraper
        self._opener = opener or urllib.request.urlopen
        self._env = env if env is not None else os.environ
        self._recent_calls: deque[float] = deque()

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        location = str(args.get("location") or "").strip()
        if not location:
            return ToolResult(ok=False, error="refused: an empty location")
        # The two-part marker's second line is meant to be a JSON object
        # of filters, merged into `args` by the router. When it is not
        # JSON the router leaves it under `filters`, which nothing here
        # reads -- so before this, "under 2 million please" was silently
        # dropped and the search ran unfiltered, returning results that
        # looked like an answer to a question nobody had asked
        # (wave-21 observer W21-10).
        leftover = args.get("filters")
        if leftover:
            return ToolResult(
                ok=False,
                error=("refused: the second line must be a JSON object of filters, e.g. "
                       '{"zip_code": "95120", "max_price": 2500000} -- got '
                       f"{str(leftover)[:80]!r}, which names no filter this tool has"),
            )
        try:
            self._enforce_rate_limit(ctx)
        except ListingsUnavailable as exc:
            return ToolResult(ok=False, error=str(exc))

        # Which source answers is a configuration question, not the
        # model's. `auto` prefers a licensed API when a key is set and
        # falls back to the scraper otherwise, so this tool works with
        # no account and gets better the day somebody adds one.
        try:
            provider = listingsources.choose_provider(self._config.real_estate_provider, self._env)
        except listingsources.NoSuchProvider as exc:
            return ToolResult(ok=False, error=f"refused: {exc}")

        limit = max(self._config.real_estate_max_results * 10, 200)
        try:
            if provider == listingsources.HOMEHARVEST:
                rows = await asyncio.wait_for(
                    asyncio.to_thread(self._scrape, location, limit),
                    timeout=self._config.real_estate_timeout_s,
                )
            else:
                rows = await asyncio.wait_for(
                    asyncio.to_thread(
                        listingsources.FETCHERS[provider], self._opener, self._env,
                        location=location, limit=limit,
                        timeout=self._config.real_estate_timeout_s,
                    ),
                    timeout=self._config.real_estate_timeout_s + 5.0,
                )
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error="timeout")
        except ListingsUnavailable as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 -- a source failure is a result, never a crash
            return ToolResult(ok=False, error=f"search failed via {provider}: {exc!r}")
        total = len(rows)
        listings = rows_to_listings(rows)
        # An explicit filter wins; otherwise a ZIP written into the
        # location is the filter (see `zip_in`).
        zip_code = str(args.get("zip_code") or "").strip()
        implied_zip = False
        if not zip_code:
            zip_code = zip_in(location)
            implied_zip = bool(zip_code)
        if zip_code:
            listings = [l for l in listings if l.zip_code == zip_code]
        listings = _apply_numeric_filters(listings, args)
        matched_listings = listings
        matched = len(listings)
        listings = listings[: self._config.real_estate_max_results]

        return ToolResult(
            ok=True, output=render(listings, location, len(listings), total,
                                   zip_code=zip_code, implied_zip=implied_zip,
                                   disclaimer=listingsources.disclaimer_for(provider)),
            metadata={
                "location": location, "total_fetched": total, "matched": matched,
                "returned": len(listings), "provider": provider,
                "source": listingsources.disclaimer_for(provider),
                "zip_code": zip_code, "zip_from_location": implied_zip,
                # Every match, not just the rendered page of them:
                # Execution writes these to a file under `results/` and
                # names the path in the output, so the data can actually
                # be analysed (comparables, price distributions) instead
                # of being summarised away. See `service.py::_store_rows`.
                "rows": [asdict(listing) for listing in matched_listings],
            },
        )

    def _scrape(self, location: str, limit: int) -> list[dict]:
        scraper = self._scraper
        if scraper is None:
            try:
                from homeharvest import scrape_property as scraper
            except ImportError:
                raise ListingsUnavailable(
                    "refused: the `homeharvest` package is not installed (pip install homeharvest) "
                    "-- or configure a licensed provider: "
                    + "; ".join(f"{name} ({', '.join(keys)})"
                                for name, keys, _ in listingsources.PROVIDERS if keys)
                ) from None
        df = scraper(location=location, listing_type="for_sale", past_days=60, limit=limit)
        return df.to_dict("records") if hasattr(df, "to_dict") else list(df or [])

    def _enforce_rate_limit(self, ctx: ToolContext) -> None:
        now = ctx.clock.now() if ctx.clock else time.monotonic()
        cutoff = now - self._config.real_estate_window_s
        while self._recent_calls and self._recent_calls[0] < cutoff:
            self._recent_calls.popleft()
        if len(self._recent_calls) >= self._config.real_estate_max_calls:
            raise ListingsUnavailable(
                f"rate limit exceeded: {len(self._recent_calls)}/{self._config.real_estate_max_calls} "
                f"listing searches in the last {self._config.real_estate_window_s:.0f}s"
            )
        self._recent_calls.append(now)


def _apply_numeric_filters(listings: list[Listing], args: dict) -> list[Listing]:
    bounds = (
        ("min_price", "price", lambda v, b: v >= b), ("max_price", "price", lambda v, b: v <= b),
        ("min_sqft", "sqft", lambda v, b: v >= b), ("max_sqft", "sqft", lambda v, b: v <= b),
        ("min_price_per_sqft", "price_per_sqft", lambda v, b: v >= b),
        ("max_price_per_sqft", "price_per_sqft", lambda v, b: v <= b),
    )
    for arg_key, field, cmp in bounds:
        bound = args.get(arg_key)
        if bound is None:
            continue
        listings = [l for l in listings if getattr(l, field) is not None and cmp(getattr(l, field), bound)]
    return listings
