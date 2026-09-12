"""The cameras (execution/home/cameras.py) against a fake NVR and a
fake ffmpeg: naming, snapshots, lights, the siren, moves, recordings,
live streams framed, tiled or full screen, and pushed events."""

from __future__ import annotations

import asyncio
import os
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.home.cameras import Camera, cameras_tools


class _Bus:
    def __init__(self) -> None:
        self.published = []
        self.handlers = {}

    async def publish(self, message) -> None:
        self.published.append(message)

    async def subscribe(self, topic, handler, **kw):
        self.handlers[topic] = handler

        class _Sub:
            async def unsubscribe(self_inner) -> None:
                pass
        return _Sub()


class _FakeNvr:
    def __init__(self) -> None:
        self.cameras = [Camera(1, "Front Window", "NVC-B12M", True), Camera(7, "Office", "NVC-B12M", True),
                        Camera(11, "Pool", "NVC-B12M", False)]
        self.calls: list[tuple] = []
        self.subscribed = None

    async def connect(self):
        return {"name": "NVR", "model": "NVS16", "firmware": "v3", "cameras": 3}

    async def channels(self):
        return list(self.cameras)

    async def state(self, ch):
        return {"motion": ch == 1, "person": ch == 1, "recording": True, "light": False, "ir": True}

    async def snapshot(self, ch):
        return b"\xff\xd8fakejpeg" + bytes([ch])

    async def stream_url(self, ch, stream="sub"):
        return f"rtsp://x/Preview_{ch:02d}_{stream}"

    async def light(self, ch, on):
        self.calls.append(("light", ch, on))

    async def ir(self, ch, on):
        self.calls.append(("ir", ch, on))

    async def siren(self, ch, seconds):
        self.calls.append(("siren", ch, seconds))

    async def ptz(self, ch, command, *, preset=None, speed=None):
        self.calls.append(("ptz", ch, command, preset))

    async def recordings(self, ch, start, end):
        return [{"start": "2026-09-12 08:00:00", "end": "2026-09-12 08:01:00", "file": "a.mp4", "seconds": 60, "kinds": ["person"]}]

    async def subscribe(self, webhook):
        self.subscribed = webhook

    async def renew(self):
        pass

    async def unsubscribe(self):
        self.subscribed = None

    def events(self, body):
        return [1] if "channel1" in body else []

    async def kinds_for(self, ch):
        return ["person"]


def _fake_ffmpeg(tmp: Path) -> str:
    """Writes the playlist its last argument names, then sleeps like ffmpeg would."""
    import sys
    script = tmp / "ffmpeg"
    script.write_text(f"#!{sys.executable}\nimport os, sys, time\nout = sys.argv[-1]\n"
                      "os.makedirs(os.path.dirname(out), exist_ok=True)\nopen(out, 'w').write('#EXTM3U\\n')\n"
                      "time.sleep(3600)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)



def bus_msgs(case):
    bus = getattr(case, "bus", None) or case.ctx.bus
    return bus.published


class CamerasTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.nvr = _FakeNvr()
        self.bus = _Bus()
        self.tools = {t.name: t for t in cameras_tools(Config(cast_page_url="http://10.0.0.5:8765/tv"), nvr=self.nvr,
                                                        env={"SIM_API_TOKEN": "s3"}, ffmpeg=_fake_ffmpeg(self.root),
                                                        clock=lambda: datetime(2026, 9, 12, 12, 0).timestamp())}
        self.ctx = ToolContext(action_id="a1", task_id=None, scope={}, constraints={}, data_dir=self.root, clock=None,
                               logger=None, ledger=None, bus=self.bus)

    def tearDown(self) -> None:
        stream = self.tools["cam_stream"]
        stream._stop(None)  # noqa: SLF001
        self._tmp.cleanup()

    async def test_list_and_state(self):
        listed = await self.tools["cam_list"].run({}, ctx=self.ctx)
        self.assertTrue(listed.ok)
        self.assertIn(" 2. Front Window", listed.output)
        self.assertIn("OFFLINE", listed.output)
        state = await self.tools["cam_state"].run({"camera": "front"}, ctx=self.ctx)
        self.assertEqual(state.output, "Front Window: motion, person  [recording, ir]")
        every = await self.tools["cam_state"].run({}, ctx=self.ctx)
        self.assertIn("Office: quiet", every.output)

    async def test_naming_by_number_name_or_words(self):
        for wanted in ("2", "Front Window", "front", "window front"):
            snap = await self.tools["cam_snapshot"].run({"camera": wanted}, ctx=self.ctx)
            self.assertTrue(snap.ok, (wanted, snap.error))
            self.assertIn("Front Window: workspace/cameras/Front_Window-", snap.output)
        bad = await self.tools["cam_snapshot"].run({"camera": "garage"}, ctx=self.ctx)
        self.assertIn("no camera called 'garage'", bad.error)
        self.assertIn("Front Window, Office, Pool", bad.error)

    async def test_lights_siren_ptz_and_recordings(self):
        self.assertTrue((await self.tools["cam_light"].run({"camera": "office on"}, ctx=self.ctx)).ok)
        self.assertTrue((await self.tools["cam_ir"].run({"camera": "office", "on": False}, ctx=self.ctx)).ok)
        siren = await self.tools["cam_siren"].run({"camera": "pool 8"}, ctx=self.ctx)
        self.assertTrue(siren.ok, siren.error)
        long = await self.tools["cam_siren"].run({"camera": "pool", "seconds": 999}, ctx=self.ctx)
        self.assertTrue(long.ok)
        self.assertTrue((await self.tools["cam_ptz"].run({"camera": "office preset 3"}, ctx=self.ctx)).ok)
        self.assertTrue((await self.tools["cam_ptz"].run({"camera": "office", "command": "left"}, ctx=self.ctx)).ok)
        self.assertEqual(self.nvr.calls, [("light", 7, True), ("ir", 7, False), ("siren", 11, 8), ("siren", 11, 30),
                                          ("ptz", 7, "ToPos", 3), ("ptz", 7, "Left", None)])
        recs = await self.tools["cam_recordings"].run({"camera": "front today"}, ctx=self.ctx)
        self.assertIn("Front Window: 1 clip(s) today", recs.output)
        self.assertIn("08:00 -> 08:01  person", recs.output)

    async def test_one_camera_framed_several_tiled_and_stop(self):
        one = await self.tools["cam_stream"].run({"camera": "office"}, ctx=self.ctx)
        self.assertTrue(one.ok, one.error)
        state = self.bus.published[-1]
        self.assertEqual(state.type, topics.TV_STATE)
        self.assertEqual(state.payload["mode"], "frame")
        self.assertEqual(state.payload["url"], "http://10.0.0.5:8765/tv/hls/7/index.m3u8")
        self.assertTrue((self.root / "workspace/cameras/hls/7/index.m3u8").exists())
        grid = await self.tools["cam_stream"].run({"camera": "front, office"}, ctx=self.ctx)
        self.assertTrue(grid.ok, grid.error)
        state = self.bus.published[-1].payload
        self.assertEqual(state["mode"], "grid")
        self.assertEqual(state["titles"], ["Front Window", "Office"])
        self.assertEqual(len(state["urls"]), 2)
        every = await self.tools["cam_stream"].run({"camera": "all", "mode": "grid"}, ctx=self.ctx)
        self.assertTrue(every.ok)
        self.assertEqual(self.bus.published[-1].payload["titles"], ["Front Window", "Office"], "only the online ones")
        # `dash`: relays for the dashboard's strip, the TV's page untouched, the name written beside the playlist
        before = len(bus_msgs(self))
        dash = await self.tools["cam_stream"].run({"camera": "all", "mode": "dash"}, ctx=self.ctx)
        self.assertTrue(dash.ok, dash.error)
        self.assertIn("dashboard", dash.output)
        self.assertEqual(len(bus_msgs(self)), before, "nothing is published to the TV")
        import json as _json
        meta = _json.loads((self.root / "workspace" / "cameras" / "hls" / "1" / "camera.json").read_text())
        self.assertEqual((meta["channel"], meta["name"]), (1, "Front Window"))
        stopped = await self.tools["cam_stream"].run({"camera": "all stop"}, ctx=self.ctx)
        self.assertTrue(stopped.ok)
        self.assertEqual(self.bus.published[-1].payload["mode"], "none")
        self.assertEqual(self.tools["cam_stream"]._prefs.streams, {})  # noqa: SLF001

    async def test_watch_subscribes_with_the_token_and_relays_events(self):
        on = await self.tools["cam_watch"].run({"on": True}, ctx=self.ctx)
        self.assertTrue(on.ok, on.error)
        self.assertEqual(self.nvr.subscribed, "http://10.0.0.5:8765/api/hooks/reolink?token=s3")
        for _ in range(20):
            if topics.UI_HOOK_RECEIVED in self.bus.handlers:
                break
            await asyncio.sleep(0.01)
        handler = self.bus.handlers[topics.UI_HOOK_RECEIVED]

        class _Msg:
            payload = {"name": "reolink", "body": "<xml>channel1 motion</xml>"}
        await handler(_Msg())
        kinds = [m for m in self.bus.published if m.type == topics.CAMERA_EVENT]
        self.assertEqual(kinds[-1].payload, {"channel": 1, "camera": "Front Window", "kinds": ["person"]})
        notices = [m for m in self.bus.published if m.type == topics.UI_NOTICE]
        self.assertIn("Front Window: person", notices[-1].payload["text"])
        off = await self.tools["cam_watch"].run({"on": "off"}, ctx=self.ctx)
        self.assertTrue(off.ok)
        self.assertIsNone(self.nvr.subscribed)

    async def test_setup_stores_the_login_owner_only(self):
        home = self.root / "home"
        tools = {t.name: t for t in cameras_tools(Config(), nvr=self.nvr, env={}, settings_home=home)}
        result = await tools["cam_setup"].run({"host": "192.168.50.42", "username": "sim", "password": "pw"}, ctx=self.ctx)
        self.assertTrue(result.ok, result.error)
        self.assertIn("3 camera(s)", result.output)
        text = (home / "secrets.toml").read_text()
        self.assertIn('REOLINK_PASSWORD = "pw"', text)
        self.assertEqual(stat.S_IMODE((home / "secrets.toml").stat().st_mode), 0o600)
        self.assertNotIn("pw", result.output)
