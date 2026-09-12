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

    def play_youtube(self, name, video_id):
        self.calls.append(("play_youtube", name, video_id))

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
        with tempfile.TemporaryDirectory() as tmp:
            tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=cast,
                                                   reachable=lambda url: True, settings_home=Path(tmp))}
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


class SetupTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_setup_opens_the_api_mints_a_token_and_remembers_the_one_tv(self):
        import stat
        import tempfile
        import tomllib
        from simorgh.contracts.protocols import ToolContext
        cast = _FakeCast(("Family Room TV",))
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            tools = {t.name: t for t in cast_tools(Config(), cast=cast, reachable=lambda url: True, env={},
                                                   settings_home=home)}
            ctx = ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=home / "data",
                              clock=None, logger=None, ledger=None, bus=_Bus())
            result = await tools["cast_setup"].run({}, ctx=ctx)
            self.assertTrue(result.ok, result.error)
            config = tomllib.loads((home / "simorgh.toml").read_text())
            self.assertEqual(config["interface"]["http_host"], "0.0.0.0")
            self.assertIn("SIM_API_TOKEN", config["execution"]["secrets"])
            self.assertEqual(config["execution"]["cast_device"], "Family Room TV")
            secrets_path = home / "secrets.toml"
            token = tomllib.loads(secrets_path.read_text())["SIM_API_TOKEN"]
            self.assertGreaterEqual(len(token), 24)
            self.assertEqual(stat.S_IMODE(secrets_path.stat().st_mode), 0o600)
            self.assertIn("restart Sim", result.output)
            self.assertNotIn(token, result.output, "the token is never printed")
            # Run again: the token is kept, nothing is minted twice.
            again = await tools["cast_setup"].run({}, ctx=ctx)
            self.assertTrue(again.ok)
            self.assertIn("already set", again.output)
            self.assertEqual(tomllib.loads(secrets_path.read_text())["SIM_API_TOKEN"], token)


class SettingsPathsTestCase(unittest.TestCase):
    def test_the_files_are_the_kernels_own(self):
        import os
        from simorgh.execution.media.cast import settings_paths
        config_path, secrets_path = settings_paths()
        self.assertEqual(config_path.name, "simorgh.toml")
        self.assertEqual(secrets_path, config_path.parent / "secrets.toml")
        self.assertNotEqual(config_path.parent, Path(os.getcwd()).parent, "never the working directory's parent")


class YouTubeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_youtube_page_plays_full_screen_through_the_youtube_receiver(self):
        from simorgh.execution.media.cast import youtube_id
        self.assertEqual(youtube_id("https://www.youtube.com/watch?v=Ph-wjyyq1nA"), "Ph-wjyyq1nA")
        self.assertEqual(youtube_id("https://youtu.be/Ph-wjyyq1nA?t=3"), "Ph-wjyyq1nA")
        self.assertEqual(youtube_id("https://example.com/clip.mp4"), "")
        cast = _FakeCast()
        tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=cast,
                                               reachable=lambda url: True)}
        bus = _Bus()
        full = await tools["cast_play"].run({"url": "https://www.youtube.com/watch?v=Ph-wjyyq1nA", "mode": "full"},
                                            ctx=_ctx(bus))
        self.assertTrue(full.ok, full.error)
        self.assertEqual(cast.calls[-1], ("play_youtube", "Living Room TV", "Ph-wjyyq1nA"))
        framed = await tools["cast_play"].run({"url": "https://youtu.be/Ph-wjyyq1nA"}, ctx=_ctx(bus))
        self.assertTrue(framed.ok)
        self.assertEqual(bus.published[-1].payload["mode"], "frame")
