"""go2rtc, the low-delay camera relay (domains/home/go2rtc.py) and its tool
`cam_webrtc` (cameras.py) -- with no binary, no network and no NVR.

What must hold: its API listens on this Mac only (the 2026-09-19 lesson,
when `/tv/hls/` let anyone on the LAN watch the house); the config that
carries the NVR password is never readable by others, not even for a
moment; and each stream is named after its own camera."""

from __future__ import annotations

import asyncio
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.domains.home import go2rtc as g
from simorgh.domains.home.cameras import Camera, cameras_tools
from simorgh.execution.config import Config
from tests.simorgh.domains.home.test_cameras import _FakeNvr


class TheConfig(unittest.TestCase):
    def test_the_api_listens_on_loopback_and_rtsp_is_off(self):
        text = g.config({"office": "rtsp://u:p@nvr/1"})
        self.assertIn('listen: "127.0.0.1:1984"', text)
        self.assertIn('rtsp:\n  listen: ""', text)
        self.assertIn("  office: rtsp://u:p@nvr/1", text)

    def test_the_password_file_is_owner_only_from_the_first_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = g.Go2rtc(Path(tmp))
            with mock.patch.object(os, "open", wraps=os.open) as opened:
                engine.write_config({"office": "rtsp://u:secret@nvr/1"})
            self.assertEqual(opened.call_args.args[2], 0o600, "created 0600, not tightened afterwards")
            mode = stat.S_IMODE(engine.config_path.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_a_platform_without_a_release_is_named(self):
        self.assertEqual(g.asset_for("Darwin", "arm64"), "go2rtc_mac_arm64.zip")
        self.assertEqual(g.asset_for("Plan9", "mips"), "")


class TheTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.nvr = _FakeNvr()
        tools = {t.name: t for t in cameras_tools(Config(repo_root=self.tmp.name), nvr=self.nvr, env={})}
        self.tool = tools["cam_webrtc"]
        self.tool._shared.clear()  # noqa: SLF001 -- one engine per Sim; a fresh one per test

    def _ctx(self):
        from simorgh.contracts.protocols import ToolContext

        return ToolContext(action_id="a", task_id=None, scope={}, constraints={}, data_dir=Path(self.tmp.name),
                           clock=None, logger=None, ledger=None)

    async def test_it_is_weighed_as_irreversible(self):
        self.assertEqual(self.tool.reversibility, "irreversible")

    async def test_status_without_the_binary_says_how_to_get_it_and_that_hls_still_works(self):
        with mock.patch.object(g.shutil, "which", return_value=None):
            result = await self.tool.run({"action": "status"}, ctx=self._ctx())
        self.assertTrue(result.ok)
        self.assertFalse(result.metadata["installed"])
        self.assertIn("install", result.output)

    async def test_each_stream_is_named_after_its_own_camera(self):
        """The names were paired by zipping SORTED stream ids with the
        cameras in NVR order -- "front_window" could come out as "Office"."""
        self.nvr.cameras = [Camera(7, "Office", "x", True), Camera(1, "Front Window", "x", True)]
        started = {}

        def fake_start(streams, **_kw):
            started.update(streams)
            return True, "go2rtc running"
        engine = self.tool._engine(Path(self.tmp.name))  # noqa: SLF001
        with mock.patch.object(g, "found", return_value="/bin/go2rtc"), \
             mock.patch.object(engine, "start", fake_start):
            result = await self.tool.run({"action": "start"}, ctx=self._ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["names"], {"office": "Office", "front_window": "Front Window"})
        self.assertEqual(started["office"], "rtsp://x/Preview_07_main")


if __name__ == "__main__":
    unittest.main()
