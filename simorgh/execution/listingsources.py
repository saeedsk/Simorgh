"""Where `search_listings` gets its data, and what it is honest about.

`search_listings` began with exactly one source: `homeharvest`, which
reads Realtor.com's own site backend. That works, needs no account, and
is the reason the tool exists at all -- but it is an unofficial scraper,
and the tool says so in every single result because a caller deciding
whether to trust a price needs to know where it came from.

This module adds licensed alternatives WITHOUT requiring one. Built
before any key exists, on purpose (the creator, 2026-09-09: build it so
that "when the skill will be needed, user will provide account or api
key ... but still the sim infra needs to be ready"). Each provider is
switched on by an environment variable and off by its absence.

`auto` prefers a licensed API over the scraper when a key is present.
That ordering is the opposite of `notify`'s -- and deliberate. For a
notification, any working provider is as good as another. For DATA, the
licensed source is better than the scraper in the way that matters: it
has terms, a rate limit you are entitled to, and it does not break the
week Realtor.com changes an endpoint. Nobody who sets RENTCAST_API_KEY
wants their listings still coming from a scraper.

The disclaimer travels WITH the provider, never as a constant. A
licensed result must not inherit the scraper's "unofficial, can break
without warning" caveat -- that would be a lie in the safe direction,
which is still a lie, and a caller who reads it would discount good
data. Equally, a scraped result must never lose it.

Every provider normalises to the same row shape `rows_to_listings`
already consumes (`full_street_line`/`city`/`zip_code`/`list_price`/
`sqft`/`beds`/`full_baths`/`latitude`/`longitude`/`property_url`), so
nothing downstream -- filters, rendering, the `results/` file -- knows
or cares which one answered.

| provider | variables | notes |
|---|---|---|
| `rentcast` | `RENTCAST_API_KEY` | licensed; free tier exists |
| `attom` | `ATTOM_API_KEY` | licensed; property/AVM data |
| `homeharvest` | none | the unofficial default; always available |

Adding one is a row in `PROVIDERS`, a `_fetch_*`, and a row shape.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .netsafety import validate_public_http_url

HOMEHARVEST = "homeharvest"

RENTCAST_URL = "https://api.rentcast.io/v1/listings/sale"
ATTOM_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0/sale/snapshot"

SCRAPER_DISCLAIMER = (
    "via homeharvest (reads Realtor.com's own site backend -- an unofficial, actively-maintained "
    "open-source scraper, NOT a licensed data API and NOT Zillow-sourced; can break or rate-limit "
    "without warning; verify anything important directly against Realtor.com/Zillow)"
)

# provider -> (required env vars, disclaimer). Order is preference order
# for `auto`: licensed first, scraper last.
PROVIDERS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("rentcast", ("RENTCAST_API_KEY",),
     "via the RentCast API (a licensed data provider under your own account and its terms; "
     "coverage and freshness are RentCast's, not Realtor.com's -- listings the two disagree on "
     "are worth checking by hand)"),
    ("attom", ("ATTOM_API_KEY",),
     "via the ATTOM Data API (a licensed provider under your own account and its terms; "
     "ATTOM's sale snapshot is assessor/deed-derived, so it can lag an active MLS listing)"),
    (HOMEHARVEST, (), SCRAPER_DISCLAIMER),
)


class NoSuchProvider(Exception):
    """The configured provider name is not one this module has."""


def _keys_for(provider: str) -> tuple[str, ...] | None:
    for name, keys, _ in PROVIDERS:
        if name == provider:
            return keys
    return None


def disclaimer_for(provider: str) -> str:
    for name, _, text in PROVIDERS:
        if name == provider:
            return text
    return SCRAPER_DISCLAIMER


def missing_for(provider: str, env) -> list[str]:
    keys = _keys_for(provider)
    if keys is None:
        raise NoSuchProvider(provider)
    return [key for key in keys if not (env.get(key) or "").strip()]


def choose_provider(configured: str, env) -> str:
    """The provider to use.

    `auto` takes the first one whose keys are all present -- which,
    given PROVIDERS' order, means a licensed API when one is configured
    and the scraper otherwise. Unlike `notify`, this never raises for
    lack of a key: `homeharvest` needs none, so there is always an
    answer. An explicitly-named provider missing its key is a different
    matter -- that is a misconfiguration, and silently falling back to
    the scraper would hand back data from a source the operator did not
    choose, wearing the wrong disclaimer.
    """
    configured = (configured or "auto").strip().lower()
    if configured == "auto":
        for name, keys, _ in PROVIDERS:
            if all((env.get(key) or "").strip() for key in keys):
                return name
        return HOMEHARVEST
    missing = missing_for(configured, env)  # raises NoSuchProvider on a typo
    if missing:
        raise NoSuchProvider(
            f"{configured} needs {', '.join(missing)} in the environment "
            f"(or set real_estate_provider = \"auto\" to fall back to {HOMEHARVEST})"
        )
    return configured


def _get_json(opener, url: str, params: dict, headers: dict, timeout: float) -> dict | list:
    full = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, '')})}"
    validate_public_http_url(full, allow_private=False)
    request = urllib.request.Request(full, headers=headers)
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace") or "null")


def _text(value) -> str:
    return "" if value is None else str(value)


def _fetch_rentcast(opener, env, *, location: str, limit: int, timeout: float) -> list[dict]:
    city, state, zip_code = split_location(location)
    body = _get_json(
        opener, RENTCAST_URL,
        {"city": city, "state": state, "zipCode": zip_code, "status": "Active", "limit": limit},
        {"X-Api-Key": env["RENTCAST_API_KEY"].strip(), "Accept": "application/json"}, timeout,
    )
    records = body if isinstance(body, list) else (body or {}).get("listings") or []
    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        rows.append({
            "full_street_line": _text(record.get("addressLine1") or record.get("formattedAddress")),
            "city": _text(record.get("city")), "zip_code": _text(record.get("zipCode")),
            "list_price": record.get("price"), "sqft": record.get("squareFootage"),
            "beds": record.get("bedrooms"), "full_baths": record.get("bathrooms"),
            "latitude": record.get("latitude"), "longitude": record.get("longitude"),
            "property_url": _text(record.get("listingUrl")),
        })
    return rows


def _fetch_attom(opener, env, *, location: str, limit: int, timeout: float) -> list[dict]:
    city, state, zip_code = split_location(location)
    body = _get_json(
        opener, ATTOM_URL,
        {"postalcode": zip_code, "cityname": city if not zip_code else "", "pagesize": limit},
        {"apikey": env["ATTOM_API_KEY"].strip(), "Accept": "application/json"}, timeout,
    )
    rows = []
    for record in ((body or {}).get("property") or []):
        if not isinstance(record, dict):
            continue
        address = record.get("address") or {}
        location_block = record.get("location") or {}
        sale = (record.get("sale") or {}).get("amount") or {}
        building = ((record.get("building") or {}).get("size") or {})
        rooms = (record.get("building") or {}).get("rooms") or {}
        rows.append({
            "full_street_line": _text(address.get("line1")),
            "city": _text(address.get("locality")), "zip_code": _text(address.get("postal1")),
            "list_price": sale.get("saleamt"), "sqft": building.get("livingsize"),
            "beds": rooms.get("beds"), "full_baths": rooms.get("bathsfull"),
            "latitude": location_block.get("latitude"), "longitude": location_block.get("longitude"),
            "property_url": "",
        })
    return rows


FETCHERS = {"rentcast": _fetch_rentcast, "attom": _fetch_attom}


def split_location(location: str) -> tuple[str, str, str]:
    """`"San Jose, CA 95120"` -> `("San Jose", "CA", "95120")`.

    Licensed APIs take structured city/state/zip parameters rather than
    homeharvest's one free-text location, so the same string a caller
    already writes has to be pulled apart. Every part is optional and an
    unparseable string yields empties rather than a guess -- the API
    then answers on whatever it did get, which beats inventing a city.
    """
    import re

    text = (location or "").strip().rstrip(",")
    zip_code = ""
    zip_match = re.search(r"(?<!\d)(\d{5})(?:-\d{4})?\s*$", text)
    if zip_match:
        zip_code = zip_match.group(1)
        text = text[: zip_match.start()].strip().rstrip(",").strip()
    state = ""
    state_match = re.search(r",\s*([A-Za-z]{2})\s*$", text)
    if state_match:
        state = state_match.group(1).upper()
        text = text[: state_match.start()].strip()
    city = text.strip().rstrip(",").strip()
    return city, state, zip_code
