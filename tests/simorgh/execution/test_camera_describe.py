"""`camera_describe`: asking a camera what it can see (execution/vision.py).

The creator, live 2026-09-15: "Do you have the ability to kind of the
image recognition for the ring cameras?" -- and Sim, with the watcher
running in the very same process, answered "no built-in image
recognition on my side". The capability existed; nothing offered it to
the model, so it did not know.
"""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolResult
from simorgh.execution.config import Config
from simorgh.execution.vision import CameraDescribeTool, vision_tools


class _Bus:
    def __init__(self, answer="a grey van parked across the drive, nobody in sight") -> None:
        self.requests = []
        self._answer = answer

    async def request_or_error(self, message, *, timeout=None):
        self.requests.append(message)
        if isinstance(self._answer, dict):
            return types.SimpleNamespace(payload=self._answer)
        return types.SimpleNamespace(payload={"ok": True, "text": self._answer})


class _Snapshot:
    def __init__(self, name, *, ok=True, error="") -> None:
        self.name = name
        self.calls = []
        self._ok = ok
        self._error = error

    async def run(self, args, *, ctx):
        self.calls.append(dict(args))
        if not self._ok:
            return ToolResult(ok=False, error=self._error)
        return ToolResult(ok=True, metadata={"path": f"workspace/cameras/{self.name}-{len(self.calls)}.jpg"})


class CameraDescribeTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.bus = _Bus()

    def _tool(self, *, nvr=None, ring=None, **settings):
        config = Config(repo_root=self.root, camera_vision_gap_s=0.0, **settings)
        tool = CameraDescribeTool(config)
        tool._snapshot_tools = lambda: [t for t in (nvr, ring) if t is not None]  # noqa: SLF001
        return tool

    def _ctx(self):
        return types.SimpleNamespace(bus=self.bus, clock=lambda: 1_789_500_000.0,
                                     logger=types.SimpleNamespace(warning=lambda *a, **k: None,
                                                                  info=lambda *a, **k: None))

    async def test_it_describes_what_the_camera_sees(self):
        nvr = _Snapshot("cam_snapshot")
        result = await self._tool(nvr=nvr).run({"camera": "Front Window"}, ctx=self._ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("a grey van parked across the drive", result.output)
        self.assertEqual(len(nvr.calls), 2, "a couple of stills, as the watcher takes")
        asked = self.bus.requests[-1]
        self.assertEqual(asked.payload["images"],
                         [str(self.root / "workspace/cameras/cam_snapshot-1.jpg"),
                          str(self.root / "workspace/cameras/cam_snapshot-2.jpg")])
        self.assertTrue(asked.payload["require_real_provider"], "no canned answer about a camera")

    async def test_a_ring_camera_falls_back_from_the_nvr(self):
        nvr = _Snapshot("cam_snapshot", ok=False, error="refused: Front Door is a Ring camera, not one on the NVR")
        ring = _Snapshot("ring_snapshot")
        result = await self._tool(nvr=nvr, ring=ring).run({"camera": "Front Door"}, ctx=self._ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(ring.calls), 2)

    async def test_no_picture_says_why_and_does_not_guess(self):
        nvr = _Snapshot("cam_snapshot", ok=False, error="refused: not on the NVR")
        ring = _Snapshot("ring_snapshot", ok=False, error="Ring had no fresh still")
        result = await self._tool(nvr=nvr, ring=ring).run({"camera": "Front Door"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("no picture", result.error)
        self.assertIn("Ring had no fresh still", result.error)
        self.assertEqual(self.bus.requests, [], "nothing to look at, so nothing was asked")

    async def test_a_model_that_cannot_look_is_reported_not_invented(self):
        self.bus = _Bus(answer={"ok": False, "error": {"code": "no_real_provider",
                                                       "detail": "nothing here can look at a picture"}})
        result = await self._tool(nvr=_Snapshot("cam_snapshot")).run({"camera": "Office"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("could not look", result.error)

    async def test_it_needs_a_camera_named(self):
        result = await self._tool(nvr=_Snapshot("cam_snapshot")).run({}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("which camera", result.error)

    def test_the_tool_is_offered_and_reads_only(self):
        tools = vision_tools(Config(repo_root=self.root))
        self.assertEqual([t.name for t in tools], ["camera_describe"])
        self.assertTrue(tools[0].read_only, "looking changes nothing")


if __name__ == "__main__":
    unittest.main()
