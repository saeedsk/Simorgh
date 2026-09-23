"""Showing one camera full screen means the same thing for both brands.

The creator, 2026-09-22: "how to show ring camera on tv in fullscreen?"

`cameras show <name> full` relays RTSP through ffmpeg, and a Ring camera
has no RTSP -- Ring live video is WebRTC, negotiated inside the
dashboard's page. So the command could only refuse, and the true answer
was a remote-control dance: open the camera wall, move the focus onto
the right tile, press ok.

The page always knew how (`navCamOpen`). What was missing was a way to
ask for it by name.
"""

from __future__ import annotations

import json
import unittest

from simorgh.interface import dispatch


class _Outcome:
    def __init__(self, text):
        self.text = text


class WhenTheCameraIsARingOne(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls: list[tuple[str, dict]] = []

    async def _run_tool(self, *, bus, ledger, tool, raw, session_id, timeout=120.0):
        self.calls.append((tool, json.loads(raw)))
        if tool == "cam_stream":
            return _Outcome("refused: Front Door is a Ring camera, not one on the NVR -- "
                            "`ring live Front Door` or `ring snapshot Front Door`")
        return _Outcome("ok")

    async def _cameras(self, line: str):
        from unittest import mock

        with mock.patch.object(dispatch, "_run_tool", self._run_tool):
            return await dispatch._cameras(line, bus=None, ledger=None, session_id="s")   # noqa: SLF001

    async def _ring(self, line: str):
        from unittest import mock

        with mock.patch.object(dispatch, "_run_tool", self._run_tool):
            return await dispatch._ring(line, bus=None, ledger=None, session_id="s")      # noqa: SLF001

    async def test_a_refused_relay_becomes_the_other_route(self):
        await self._cameras("show Front Door full")
        self.assertEqual([t for t, _ in self.calls], ["cam_stream", "dash_view"],
                         "it tries the relay, and a Ring refusal is not a dead end")
        self.assertEqual(self.calls[-1][1], {"camera": "Front Door", "view": "cameras"})

    async def test_an_nvr_camera_still_relays_and_nothing_else_happens(self):
        async def _ok(*, bus, ledger, tool, raw, session_id, timeout=120.0):
            self.calls.append((tool, json.loads(raw)))
            return _Outcome("Driveway is live on the TV")

        from unittest import mock

        with mock.patch.object(dispatch, "_run_tool", _ok):
            await dispatch._cameras("show Driveway full", bus=None, ledger=None, session_id="s")  # noqa: SLF001
        self.assertEqual([t for t, _ in self.calls], ["cam_stream"])

    async def test_ring_live_names_the_camera(self):
        await self._ring("live Front Door")
        self.assertEqual(self.calls, [("dash_view", {"camera": "Front Door", "view": "cameras"})])

    async def test_ring_live_off_goes_back_to_the_wall(self):
        await self._ring("live off")
        self.assertEqual(self.calls, [("dash_view", {"camera": ""})])

    async def test_ring_live_with_no_camera_says_how(self):
        outcome = await self._ring("live")
        self.assertEqual(self.calls, [], "nothing is asked of the TV")
        self.assertIn("ring live <camera>", outcome.text)


if __name__ == "__main__":
    unittest.main()
