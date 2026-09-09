"""`geocode`: turn a free-text address into latitude/longitude via
Nominatim, OpenStreetMap's free, keyless geocoding API. The natural
companion to `render_page`/`search_listings` and to any future map-
based tool: `search_listings` already gets coordinates from
homeharvest, but a plain address (from a user, a document, a listing
without coordinates) needs its own geocoding step, and every commercial
geocoder (Google, Mapbox, HERE) needs a paid API key -- Nominatim needs
none.

Nominatim's usage policy (https://operations.osmfoundation.org/policies/nominatim/)
caps unauthenticated use at roughly one request per second and requires
an identifying `User-Agent`; both are honored below (a minimum-interval
gate, same shape as `web_search`'s own throttle-avoidance pacing, and a
real User-Agent naming this project)."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from simorgh.contracts.protocols import ToolContext, ToolResult

from .config import Config

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class GeocodeTool:
    name = "geocode"
    description = "Turn a free-text address or place name into latitude/longitude (via Nominatim/OpenStreetMap, no API key needed)."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["address"], "properties": {"address": {"type": "string"}}}

    def __init__(self, config: Config, *, opener=None) -> None:
        self._config = config
        self._opener = opener or urllib.request.urlopen
        self._last_call = 0.0

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        address = str(args.get("address") or "").strip()
        if not address:
            return ToolResult(ok=False, error="refused: an empty address")
        query = urllib.parse.quote(address)
        request = urllib.request.Request(
            f"{NOMINATIM_URL}?q={query}&format=json&limit=1",
            headers={"User-Agent": self._config.geocode_user_agent},
        )
        try:
            body = await asyncio.wait_for(
                asyncio.to_thread(self._fetch, request), timeout=self._config.geocode_timeout_s,
            )
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error="timeout")
        except Exception as exc:  # noqa: BLE001 -- a network failure is a result, never a crash
            return ToolResult(ok=False, error=f"geocode failed: {exc!r}")

        try:
            results = json.loads(body)
        except json.JSONDecodeError:
            return ToolResult(ok=False, error="geocode failed: could not parse Nominatim's response")
        if not results:
            return ToolResult(ok=False, error=f"no location found for {address!r}")

        top = results[0]
        lat, lon = float(top["lat"]), float(top["lon"])
        display_name = top.get("display_name", address)
        return ToolResult(
            ok=True,
            output=f"{address!r} -> lat={lat}, lon={lon} ({display_name})",
            metadata={"latitude": lat, "longitude": lon, "display_name": display_name},
        )

    def _fetch(self, request) -> str:
        # Runs inside `asyncio.to_thread`, so a blocking sleep here paces
        # requests to Nominatim's own real clock without blocking the
        # event loop -- wall-clock, not the injected test clock, same
        # reasoning as `WebSearchTool._space_out`: this is about the
        # remote service's patience, not anything this process controls.
        self._space_out()
        with self._opener(request, timeout=self._config.geocode_timeout_s) as response:
            return response.read().decode("utf-8", errors="replace")

    def _space_out(self) -> None:
        wait = self._config.geocode_min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
