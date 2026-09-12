"""Sim on the TV (execution/media/cast.py) against a fake Cast backend:
the page goes up only when the TV can fetch it, a video is framed or
played full screen, and every state change is announced on the bus."""

from __future__ import annotations

import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.media.cast import Device, cast_tools


class _Bus:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, message) -> None:
        self.published.append(message)


class _FakeCast:
    def __init__(self, names=("Living Room TV",)) -> None:
        self.names = list(names)
        self.calls: list[tuple] = []

    def devices(self):
        return [Device(name=n, model="Chromecast", host="10.0.0.9") for n in self.names]

    def show_page(self, name, url):
        self.calls.append(("show_page", name, url))

    def play(self, name, url, *, content_type, title):
        self.calls.append(("play", name, url, content_type, title))

    def stop(self, name):
        self.calls.append(("stop", name))

    def volume(self, name, level):
        self.calls.append(("volume", name, level))


def _ctx(bus=None) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=Path("."), clock=None,
                       logger=None, ledger=None, bus=bus)


class CastTestCase(unittest.IsolatedAsyncioTestCase):
    def _tools(self, names=("Living Room TV",), reachable=True, **overrides) -> tuple[dict, _FakeCast, _Bus]:
        cast = _FakeCast(names)
        tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv", **overrides),
                                               cast=cast, reachable=lambda url: reachable, env={"SIM_API_TOKEN": "s3"})}
        return tools, cast, _Bus()

    async def test_devices_are_listed_by_name(self):
        tools, cast, bus = self._tools(("Living Room TV", "Bedroom"))
        result = await tools["cast_devices"].run({}, ctx=_ctx(bus))
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["devices"], ["Living Room TV", "Bedroom"])

    async def test_the_page_goes_up_with_the_token_and_the_state_is_announced(self):
        tools, cast, bus = self._tools()
        result = await tools["cast_show"].run({}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(cast.calls, [("show_page", "Living Room TV", "http://10.0.0.5:8765/tv?token=s3")])
        self.assertEqual(bus.published[-1].type, topics.TV_STATE)
        self.assertEqual(bus.published[-1].payload["mode"], "none")
        self.assertNotIn("s3", result.output, "the token is not echoed")

    async def test_an_unreachable_page_is_refused_with_the_fix(self):
        tools, cast, bus = self._tools(reachable=False)
        result = await tools["cast_show"].run({}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        self.assertIn("http_host", result.error)
        self.assertEqual(cast.calls, [])

    async def test_several_devices_need_a_name_or_the_setting(self):
        tools, cast, bus = self._tools(("Living Room TV", "Bedroom"))
        result = await tools["cast_show"].run({}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        self.assertIn("several Cast devices", result.error)
        result = await tools["cast_show"].run({"device": "bedroom"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(cast.calls[-1][1], "Bedroom")
        tools, cast, bus = self._tools(("Living Room TV", "Bedroom"), cast_device="Living Room TV")
        self.assertTrue((await tools["cast_show"].run({}, ctx=_ctx(bus))).ok)

    async def test_a_video_is_framed_in_the_page_or_played_full_screen(self):
        tools, cast, bus = self._tools()
        framed = await tools["cast_play"].run({"url": "https://example.com/clip.mp4", "mode": "frame", "title": "Clip"},
                                              ctx=_ctx(bus))
        self.assertTrue(framed.ok, framed.error)
        self.assertEqual(cast.calls, [], "framing is the page's job, not the device's")
        self.assertEqual(bus.published[-1].payload, {"mode": "frame", "url": "https://example.com/clip.mp4", "title": "Clip"})
        full = await tools["cast_play"].run({"url": "https://example.com/clip.mp4", "mode": "full"}, ctx=_ctx(bus))
        self.assertTrue(full.ok, full.error)
        self.assertEqual(cast.calls[-1], ("play", "Living Room TV", "https://example.com/clip.mp4", "video/mp4", ""))
        self.assertEqual(bus.published[-1].payload["mode"], "full")
        bad = await tools["cast_play"].run({"url": "file:///etc/passwd"}, ctx=_ctx(bus))
        self.assertFalse(bad.ok)

    async def test_stop_clears_the_frame_or_the_device(self):
        tools, cast, bus = self._tools()
        self.assertTrue((await tools["cast_stop"].run({"what": "frame"}, ctx=_ctx(bus))).ok)
        self.assertEqual(cast.calls, [])
        self.assertEqual(bus.published[-1].payload["mode"], "none")
        self.assertTrue((await tools["cast_stop"].run({}, ctx=_ctx(bus))).ok)
        self.assertEqual(cast.calls[-1], ("stop", "Living Room TV"))

    async def test_volume_keeps_the_media_domains_limits(self):
        tools, cast, bus = self._tools(media_max_volume_unattended=60, media_quiet_hours="")
        self.assertTrue((await tools["cast_volume"].run({"level": 40}, ctx=_ctx(bus))).ok)
        self.assertEqual(cast.calls[-1], ("volume", "Living Room TV", 0.4))
        loud = await tools["cast_volume"].run({"level": 95}, ctx=_ctx(bus))
        self.assertFalse(loud.ok)

    async def test_without_pychromecast_the_tools_refuse_by_name(self):
        from simorgh.execution.media import cast as cast_mod
        original = cast_mod.available
        cast_mod.available = lambda: (False, "needs pychromecast (pip install pychromecast)")
        try:
            tools = {t.name: t for t in cast_tools(Config())}
            result = await tools["cast_devices"].run({}, ctx=_ctx())
            self.assertFalse(result.ok)
            self.assertIn("pychromecast", result.error)
        finally:
            cast_mod.available = original


class RememberedTvTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_the_default_is_remembered_marked_and_saved(self):
        import tempfile
        from simorgh.contracts.protocols import ToolContext
        cast = _FakeCast(("Living Room TV", "Bedroom"))
        tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=cast,
                                               reachable=lambda url: True)}
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=Path(tmp) / "data",
                              clock=None, logger=None, ledger=None, bus=_Bus())
            refused = await tools["cast_show"].run({}, ctx=ctx)
            self.assertFalse(refused.ok)
            self.assertIn("tv use", refused.error)
            wrong = await tools["cast_use"].run({"device": "Kitchen"}, ctx=ctx)
            self.assertFalse(wrong.ok)
            chosen = await tools["cast_use"].run({"device": "living room"}, ctx=ctx)
            self.assertTrue(chosen.ok, chosen.error)
            self.assertIn("the TV is Living Room TV", chosen.output)
            self.assertIn('cast_device = "Living Room TV"', (Path(tmp) / "simorgh.toml").read_text())
            shown = await tools["cast_show"].run({}, ctx=ctx)
            self.assertTrue(shown.ok, shown.error)
            self.assertEqual(cast.calls[-1][1], "Living Room TV")
            listed = await tools["cast_devices"].run({}, ctx=ctx)
            self.assertIn("* Living Room TV", listed.output)
            self.assertEqual(listed.metadata["default"], "Living Room TV")
