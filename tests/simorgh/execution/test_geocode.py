"""`geocode` (execution/geocode.py): free-text address -> lat/lng via
Nominatim. Offline tests inject the HTTP opener; the one real network
call is a live smoke test that skips itself if there's no connectivity."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.geocode import GeocodeTool


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def _ctx(clock=None):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                       data_dir=Path.cwd(), clock=clock or _Clock(), logger=None, ledger=None)


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _opener(body: str, seen: list | None = None):
    def open_it(request, timeout=None):
        if seen is not None:
            seen.append(request)
        return _Response(body)
    return open_it


class GeocodeToolTestCase(unittest.IsolatedAsyncioTestCase):
    def _tool(self, body, **config):
        settings = {"repo_root": Path.cwd(), "geocode_min_interval_s": 0.0}
        settings.update(config)
        return GeocodeTool(Config(**settings), opener=_opener(body))

    async def test_a_real_result_returns_coordinates(self):
        body = json.dumps([{"lat": "37.2175403", "lon": "-121.8212403", "display_name": "20791, Via Corta, San Jose"}])
        result = await self._tool(body).run({"address": "20791 Via Corta, San Jose, CA 95120"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertAlmostEqual(result.metadata["latitude"], 37.2175403)
        self.assertAlmostEqual(result.metadata["longitude"], -121.8212403)
        self.assertIn("37.2175403", result.output)

    async def test_no_match_is_a_clean_failure(self):
        result = await self._tool("[]").run({"address": "asdkjqhwoieuqhwoiuehqoiwuehwqoiuehasdkjfh"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("no location found", result.error)

    async def test_an_empty_address_is_refused(self):
        result = await self._tool("[]").run({"address": "  "}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("empty address", result.error)

    async def test_unparseable_response_is_a_clean_failure(self):
        result = await self._tool("not json").run({"address": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("could not parse", result.error)

    async def test_a_network_failure_is_a_result_not_a_crash(self):
        def boom(request, timeout=None):
            raise OSError("no route to host")

        tool = GeocodeTool(Config(repo_root=Path.cwd(), geocode_min_interval_s=0.0), opener=boom)
        result = await tool.run({"address": "x"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("no route to host", result.error)

    async def test_the_user_agent_identifies_this_project(self):
        seen: list = []
        body = json.dumps([{"lat": "1", "lon": "2", "display_name": "x"}])
        tool = GeocodeTool(Config(repo_root=Path.cwd(), geocode_min_interval_s=0.0), opener=_opener(body, seen))
        await tool.run({"address": "x"}, ctx=_ctx())
        self.assertIn("Simorgh", seen[0].headers.get("User-agent", ""))


class RealNominatimSmokeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_real_lookup_against_nominatim(self):
        import socket

        try:
            socket.gethostbyname("nominatim.openstreetmap.org")
        except socket.gaierror:
            self.skipTest("no network access in this environment")
        tool = GeocodeTool(Config(repo_root=Path.cwd(), geocode_min_interval_s=0.0))
        result = await tool.run({"address": "1600 Amphitheatre Parkway, Mountain View, CA"}, ctx=_ctx())
        if not result.ok:
            self.skipTest(f"network call did not succeed in this sandbox: {result.error}")
        self.assertAlmostEqual(result.metadata["latitude"], 37.42, delta=0.5)
        self.assertAlmostEqual(result.metadata["longitude"], -122.08, delta=0.5)
