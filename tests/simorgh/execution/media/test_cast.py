"""Sim on the TV (execution/media/cast.py) against a fake Cast backend:
the page goes up only when the TV can fetch it, a video is framed or
played full screen, and every state change is announced on the bus."""

from __future__ import annotations

import asyncio
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

    #: what media_state answers, in order; the last repeats
    states: list = ["PLAYING", "IDLE"]

    def media_state(self, name):
        state = self.states[0] if len(self.states) == 1 else self.states.pop(0)
        self.calls.append(("media_state", name, state))
        return state

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
        self.assertEqual(cast.calls, [("show_page", "Living Room TV", "http://10.0.0.5:8765/dash?token=s3")],
                         "the dashboard is what goes on the TV by default (the creator saw the bare terminal, 2026-09-12)")
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
    async def test_a_youtube_page_is_fetched_as_a_file_and_cast_to_the_plain_player(self):
        # 2026-09-13, the creator's TV: YouTube's embedded player is blank
        # inside the Cast receiver and its own receiver answered "400
        # screen_ids parameter error". The video goes as a file instead.
        import tempfile
        from simorgh.execution.media.cast import youtube_id
        self.assertEqual(youtube_id("https://www.youtube.com/watch?v=Ph-wjyyq1nA"), "Ph-wjyyq1nA")
        self.assertEqual(youtube_id("https://youtu.be/Ph-wjyyq1nA?t=3"), "Ph-wjyyq1nA")
        self.assertEqual(youtube_id("https://example.com/clip.mp4"), "")
        fetched = []

        def fake_fetch(video, cache_dir):
            fetched.append(video)
            path = Path(cache_dir) / f"{video}.mp4"
            path.write_bytes(b"\x00" * 16)
            return path, ""

        with tempfile.TemporaryDirectory() as tmp:
            cast = _FakeCast()
            tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=cast,
                                                   reachable=lambda url: True, fetch=fake_fetch, media_dir=Path(tmp))}
            tools["cast_play"].IDLE_POLL_S = 0.01
            bus = _Bus()
            full = await tools["cast_play"].run({"url": "https://www.youtube.com/watch?v=Ph-wjyyq1nA", "mode": "full",
                                                 "title": "Sugar Man"}, ctx=_ctx(bus))
            self.assertTrue(full.ok, full.error)
            self.assertIn("fetching", full.output)
            self.assertTrue(bus.published[-1].payload.get("fetching"), "the page is told the video is on its way")
            await asyncio.gather(*tools["cast_play"]._fetches)  # noqa: SLF001
            self.assertEqual(fetched, ["Ph-wjyyq1nA"])
            plays = [c for c in cast.calls if c[0] == "play"]
            self.assertEqual(plays[-1], ("play", "Living Room TV", "http://10.0.0.5:8765/tv/media/Ph-wjyyq1nA.mp4",
                                         "video/mp4", "Sugar Man"), "the file, through the plain media receiver")
            states = [m.payload for m in bus.published if m.type == topics.TV_STATE]
            self.assertEqual(states[-2]["stream"], "/tv/media/Ph-wjyyq1nA.mp4")
            # the video ended (PLAYING, then IDLE): the dashboard is put back
            self.assertEqual(cast.calls[-1], ("show_page", "Living Room TV", "http://10.0.0.5:8765/dash"))
            self.assertEqual(states[-1], {"mode": "none"})
            # "framed" on the TV is full screen too: the TV's browser draws a framed video white
            cast.states = ["PLAYING", "IDLE"]
            framed = await tools["cast_play"].run({"url": "https://youtu.be/Ph-wjyyq1nA"}, ctx=_ctx(bus))
            self.assertTrue(framed.ok)
            self.assertIn("cannot draw a video inside the page", framed.output)
            self.assertEqual(bus.published[-1].payload["mode"], "frame")
            await asyncio.gather(*tools["cast_play"]._fetches)  # noqa: SLF001
            states = [m.payload for m in bus.published if m.type == topics.TV_STATE]
            self.assertEqual(states[-2], {"mode": "full", "url": "https://youtu.be/Ph-wjyyq1nA",
                                          "stream": "/tv/media/Ph-wjyyq1nA.mp4"})
            self.assertEqual([c for c in cast.calls if c[0] == "play"][-1][2], "http://10.0.0.5:8765/tv/media/Ph-wjyyq1nA.mp4")

    async def test_when_the_video_cannot_be_fetched_the_page_is_told_why(self):
        tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=_FakeCast(),
                                               reachable=lambda url: True,
                                               fetch=lambda v, d: (None, "yt-dlp is not installed"), media_dir=Path("."))}
        bus = _Bus()
        r = await tools["cast_play"].run({"url": "https://youtu.be/Ph-wjyyq1nA"}, ctx=_ctx(bus))
        self.assertTrue(r.ok)
        await asyncio.gather(*tools["cast_play"]._fetches)  # noqa: SLF001
        self.assertEqual(bus.published[-1].payload["problem"], "yt-dlp is not installed")
        self.assertNotIn("stream", bus.published[-1].payload)

    async def test_without_a_tv_the_page_plays_the_file_itself(self):
        import tempfile

        class NoTv(_FakeCast):
            def devices(self):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=NoTv(),
                                                   reachable=lambda url: True, media_dir=Path(tmp),
                                                   fetch=lambda v, d: ((Path(d) / f"{v}.mp4").write_bytes(b"x") and None) or (Path(d) / f"{v}.mp4", ""))}
            bus = _Bus()
            r = await tools["cast_play"].run({"url": "https://youtu.be/Ph-wjyyq1nA"}, ctx=_ctx(bus))
            self.assertTrue(r.ok, r.error)
            await asyncio.gather(*tools["cast_play"]._fetches)  # noqa: SLF001
            self.assertEqual(bus.published[-1].payload, {"mode": "frame", "url": "https://youtu.be/Ph-wjyyq1nA",
                                                         "stream": "/tv/media/Ph-wjyyq1nA.mp4"})


class MarkerFormsTestCase(unittest.IsolatedAsyncioTestCase):
    """The model writes one line after the marker; the tool reads the
    rest of the line itself."""

    async def test_one_line_forms(self):
        cast = _FakeCast(("Living Room TV", "Bedroom"))
        tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv", cast_device="Living Room TV",
                                                      media_quiet_hours=""),
                                               cast=cast, reachable=lambda url: True)}
        bus = _Bus()
        r = await tools["cast_play"].run({"url": "https://www.youtube.com/watch?v=abc123 full Bedroom"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.metadata["device"], "Bedroom")
        self.assertEqual(r.metadata["video"], "abc123")
        for t in list(tools["cast_play"]._fetches):  # noqa: SLF001 -- no fake fetch here: let the real one report
            t.cancel()
        r = await tools["cast_play"].run({"url": "<https://x/clip.mp4>"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error)
        self.assertEqual(bus.published[-1].payload["mode"], "frame")
        r = await tools["cast_show"].run({"target": "Bedroom"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error)
        self.assertEqual(cast.calls[-1][1], "Bedroom")
        r = await tools["cast_show"].run({"target": "https://example.com/board"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error)
        self.assertEqual(cast.calls[-1], ("show_page", "Living Room TV", "https://example.com/board"))
        r = await tools["cast_volume"].run({"level": "35 Bedroom"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error)
        self.assertEqual(cast.calls[-1], ("volume", "Bedroom", 0.35))


class DashViewTestCase(unittest.IsolatedAsyncioTestCase):
    """`dash_view` (2026-09-12): the TV's remote never reaches a Cast
    receiver, so the dashboard is turned from Sim -- a bus message the
    HTTP API keeps and the page polls -- or from the phone page whose
    link the tool hands out."""

    def _tools(self):
        cast = _FakeCast()
        tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=cast,
                                               reachable=lambda url: True, env={"SIM_API_TOKEN": "s3"})}
        return tools, cast, _Bus()

    async def test_a_view_a_timeframe_and_a_symbol_are_announced_normalised(self):
        tools, cast, bus = self._tools()
        result = await tools["dash_view"].run({"view": "stocks", "timeframe": "1m", "symbol": "amd"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(bus.published[-1].type, topics.DASH_STATE)
        self.assertEqual(bus.published[-1].payload, {"view": "markets", "timeframe": "1M", "symbol": "AMD"})
        self.assertIn("markets", result.output)
        self.assertEqual(cast.calls, [], "steering the page touches no device")

    async def test_a_timeframe_alone_implies_the_markets_view_and_rotation_is_bounded(self):
        tools, cast, bus = self._tools()
        result = await tools["dash_view"].run({"timeframe": "1Y"}, ctx=_ctx(bus))
        self.assertTrue(result.ok)
        self.assertEqual(bus.published[-1].payload, {"timeframe": "1Y", "view": "markets"})
        result = await tools["dash_view"].run({"rotate_s": 99999}, ctx=_ctx(bus))
        self.assertEqual(bus.published[-1].payload, {"rotate_s": 3600})
        result = await tools["dash_view"].run({"rotate_s": 0}, ctx=_ctx(bus))
        self.assertIn("rotation off", result.output)
        result = await tools["dash_view"].run({"scale": 0.5}, ctx=_ctx(bus))
        self.assertEqual(bus.published[-1].payload, {"scale": 0.5}); self.assertIn("0.5", result.output)

    async def test_nonsense_is_refused_with_the_choices(self):
        tools, cast, bus = self._tools()
        result = await tools["dash_view"].run({"view": "kitchen"}, ctx=_ctx(bus))
        self.assertFalse(result.ok); self.assertIn("ambient", result.error)
        result = await tools["dash_view"].run({"timeframe": "5Y"}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        result = await tools["dash_view"].run({}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        self.assertEqual(bus.published, [])

    async def test_the_remote_link_carries_the_token_and_points_at_the_remote_page(self):
        tools, cast, bus = self._tools()
        result = await tools["dash_view"].run({"action": "remote"}, ctx=_ctx(bus))
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["url"], "http://10.0.0.5:8765/remote?token=s3")
        link = await tools["dash_view"].run({"action": "link"}, ctx=_ctx(bus))
        self.assertEqual(link.metadata["url"], "http://10.0.0.5:8765/dash?token=s3")

    async def test_cast_show_puts_the_dashboard_up_by_default_and_the_bare_terminal_on_request(self):
        tools, cast, bus = self._tools()
        result = await tools["cast_show"].run({}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(cast.calls[-1], ("show_page", "Living Room TV", "http://10.0.0.5:8765/dash?token=s3"))
        self.assertIn("dashboard", result.output)
        result = await tools["cast_show"].run({"page": "tv"}, ctx=_ctx(bus))
        self.assertEqual(cast.calls[-1][2], "http://10.0.0.5:8765/tv?token=s3")
        result = await tools["cast_show"].run({"target": "terminal"}, ctx=_ctx(bus))
        self.assertEqual(cast.calls[-1][2], "http://10.0.0.5:8765/tv?token=s3", "the marker form names the page too")

    async def test_a_view_name_opens_the_dashboard_on_that_view_not_a_tv_called_home(self):
        # Live 2026-09-13: `CAST_SHOW: home` and `CAST_SHOW: page=home` were
        # both refused as "no Cast device called 'home'".
        from simorgh.contracts import topics
        tools, cast, bus = self._tools()
        for form in ({"target": "home"}, {"target": "page=home"}, {"page": "home"}, {"view": "home"}, {"target": "cams"}):
            result = await tools["cast_show"].run(form, ctx=_ctx(bus))
            self.assertTrue(result.ok, (form, result.error))
            self.assertEqual(cast.calls[-1], ("show_page", "Living Room TV", "http://10.0.0.5:8765/dash?token=s3"), form)
            views = [m.payload["view"] for m in bus.published if m.type == topics.DASH_STATE]
            self.assertEqual(views[-1], "cameras" if form == {"target": "cams"} else "home", form)
            self.assertIn(views[-1], result.output)
        result = await tools["cast_show"].run({"target": "page=tv device=Living Room TV"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(cast.calls[-1], ("show_page", "Living Room TV", "http://10.0.0.5:8765/tv?token=s3"))


class AndroidTvToolsTestCase(unittest.IsolatedAsyncioTestCase):
    """The TV's own apps (media/androidtv.py) through the tv_* tools and
    cast_play: paired, YouTube plays in the TV's app at its best quality;
    unpaired, the file path as before."""

    def setUp(self) -> None:
        import tempfile
        from tests.simorgh.execution.media.test_androidtv import FakeRemote
        from simorgh.execution.media import androidtv
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.certs = Path(self.tmp.name) / "tv"
        self.media = Path(self.tmp.name) / "media"; self.media.mkdir()
        FakeRemote.instances = []; androidtv._PENDING.clear()
        self.FakeRemote = FakeRemote

    def _tools(self, fetch=None):
        cast = _FakeCast()
        fetch = fetch or (lambda v, d: ((Path(d) / f"{v}.mp4").write_bytes(b"x") and None) or (Path(d) / f"{v}.mp4", ""))
        tools = {t.name: t for t in cast_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), cast=cast,
                                               reachable=lambda url: True, fetch=fetch, media_dir=self.media,
                                               remote_cls=self.FakeRemote, certs_dir=self.certs)}
        for t in tools.values():
            t.IDLE_POLL_S = 0.01
        return tools, cast, _Bus()

    async def test_pairing_through_the_tool_then_youtube_plays_in_the_tvs_own_app(self):
        tools, cast, bus = self._tools()
        first = await tools["tv_pair"].run({}, ctx=_ctx(bus))
        self.assertTrue(first.ok, first.error)
        self.assertIn("showing a code", first.output)
        wrong = await tools["tv_pair"].run({"pin": "000000"}, ctx=_ctx(bus))
        self.assertFalse(wrong.ok); self.assertIn("did not match", wrong.error)
        done = await tools["tv_pair"].run({"pin": self.FakeRemote.pin}, ctx=_ctx(bus))
        self.assertTrue(done.ok, done.error); self.assertIn("paired with Living Room TV", done.output)
        again = await tools["tv_pair"].run({}, ctx=_ctx(bus))
        self.assertIn("already paired", again.output)
        # now a YouTube video goes to the TV's own app, at its best quality
        r = await tools["cast_play"].run({"url": "https://www.youtube.com/watch?v=RqfZ3UTC14c", "mode": "full",
                                          "title": "Sugar Man"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error)
        self.assertIn("own YouTube app", r.output); self.assertIn("4K", r.output)
        self.assertEqual(r.metadata["native"], "YouTube")
        launched = [c for rem in self.FakeRemote.instances for c in rem.calls if isinstance(c, tuple) and c[0] == "launch"]
        self.assertEqual(launched, [("launch", "https://www.youtube.com/watch?v=RqfZ3UTC14c")])
        self.assertFalse([c for c in cast.calls if c[0] == "play"], "no file, no plain player")
        self.assertFalse(list(self.media.glob("*.mp4")), "nothing fetched")
        self.assertEqual(bus.published[-1].payload, {"mode": "full", "url": "https://www.youtube.com/watch?v=RqfZ3UTC14c",
                                                     "title": "Sugar Man", "native": "YouTube"})
        # framed on the TV: the TV's app as well
        r = await tools["cast_play"].run({"url": "https://youtu.be/RqfZ3UTC14c"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error); self.assertEqual(r.metadata.get("native"), "YouTube")
        # the other apps and the keys
        app = await tools["tv_app"].run({"app": "netflix"}, ctx=_ctx(bus))
        self.assertTrue(app.ok, app.error); self.assertIn("opened on Living Room TV: netflix", app.output)
        self.assertEqual(self.FakeRemote.instances[-1].calls[1], ("launch", "https://www.netflix.com/"))
        nope = await tools["tv_app"].run({"app": "solitaire"}, ctx=_ctx(bus))
        self.assertFalse(nope.ok); self.assertIn("no app called", nope.error)
        key = await tools["tv_key"].run({"key": "volume up"}, ctx=_ctx(bus))
        self.assertTrue(key.ok, key.error); self.assertEqual(key.metadata["key"], "VOLUME_UP")
        self.assertEqual(self.FakeRemote.instances[-1].calls[1], ("key", "VOLUME_UP"))

    async def test_unpaired_the_file_path_is_used_and_the_tools_say_how_to_pair(self):
        tools, cast, bus = self._tools()
        r = await tools["cast_play"].run({"url": "https://www.youtube.com/watch?v=RqfZ3UTC14c", "mode": "full"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error); self.assertIn("fetching", r.output); self.assertNotIn("native", r.metadata)
        await asyncio.gather(*tools["cast_play"]._fetches)  # noqa: SLF001
        self.assertEqual([c for c in cast.calls if c[0] == "play"][-1][2], "http://10.0.0.5:8765/tv/media/RqfZ3UTC14c.mp4")
        key = await tools["tv_key"].run({"key": "home"}, ctx=_ctx(bus))
        self.assertFalse(key.ok); self.assertIn("`tv pair`", key.error)

    async def test_an_earlier_videos_watcher_stands_down_when_the_tv_is_driven_again(self):
        # Live 2026-09-13: four watchers from four videos; one saw an idle
        # moment as the next video loaded and put the dashboard over it.
        tools, cast, bus = self._tools()
        cast.states = ["PLAYING"]      # the first video plays on and on
        r = await tools["cast_play"].run({"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "mode": "full"}, ctx=_ctx(bus))
        self.assertTrue(r.ok, r.error)
        await asyncio.sleep(0.05)      # the fetch is done; the watcher is polling
        self.assertTrue([c for c in cast.calls if c[0] == "media_state"])
        shown_before = len([c for c in cast.calls if c[0] == "show_page"])
        # somebody drives the TV: a new video; the old video's player goes idle for a moment
        cast.states = ["IDLE"]
        r2 = await tools["cast_play"].run({"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "mode": "full"}, ctx=_ctx(bus))
        await asyncio.sleep(0.05)
        self.assertEqual(len([c for c in cast.calls if c[0] == "show_page"]), shown_before,
                         "the first watcher did not put the dashboard over the second video")
        for t in list(tools["cast_play"]._fetches):  # noqa: SLF001
            t.cancel()
