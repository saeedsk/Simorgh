"""`look_at_image`: any picture file, looked at (execution/vision.py).

Bench wave, 2026-09-29: a research session downloaded a video, pulled
60 frames out of it, and then said "without a vision tool in this
session I cannot classify species per frame" -- the eyes existed only
behind the cameras.
"""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.vision import LookAtImageTool

from .test_camera_describe import _Bus


class LookAtImageTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        (self.root / "workspace" / "scratch").mkdir(parents=True)
        for name in ("frame_01.png", "frame_02.jpg", "notes.txt"):
            (self.root / "workspace" / "scratch" / name).write_bytes(b"x")
        self.bus = _Bus("two emperor penguin chicks and a giant petrel")

    def _ctx(self):
        return types.SimpleNamespace(bus=self.bus, clock=lambda: 1_789_500_000.0, worktree=None,
                                     logger=types.SimpleNamespace(warning=lambda *a, **k: None,
                                                                  info=lambda *a, **k: None))

    async def _run(self, args):
        return await LookAtImageTool(Config(repo_root=self.root)).run(args, ctx=self._ctx())

    async def test_the_pictures_and_the_question_reach_a_provider_that_can_see(self):
        result = await self._run({"paths": ["workspace/scratch/frame_01.png", "workspace/scratch/frame_02.jpg"],
                                  "question": "Which bird species are in frame?"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("giant petrel", result.output)
        asked = self.bus.requests[-1].payload
        self.assertEqual(asked["images"], [str(self.root / "workspace/scratch/frame_01.png"),
                                           str(self.root / "workspace/scratch/frame_02.jpg")])
        self.assertTrue(asked["require_real_provider"], "the floor cannot see; it must not answer")
        self.assertIn("Which bird species", asked["messages"][0]["content"])

    async def test_a_path_outside_the_readable_folders_is_refused(self):
        result = await self._run({"paths": ["../etc/passwd.png"], "question": "?"})
        self.assertFalse(result.ok)
        self.assertIn("refused", result.error)
        self.assertEqual(self.bus.requests, [], "nothing is sent for a refused path")

    async def test_a_file_that_is_not_an_image_says_so(self):
        result = await self._run({"paths": ["workspace/scratch/notes.txt"], "question": "?"})
        self.assertFalse(result.ok)
        self.assertIn("not an image", result.error)

    async def test_more_than_four_is_refused_rather_than_truncated(self):
        result = await self._run({"paths": ["workspace/scratch/frame_01.png"] * 5, "question": "?"})
        self.assertFalse(result.ok)
        self.assertIn("at most 4", result.error)

    async def test_no_provider_that_can_see_is_an_error_not_a_blank_answer(self):
        self.bus = _Bus({"ok": False, "error": "no provider can see images"})
        result = await self._run({"paths": ["workspace/scratch/frame_01.png"], "question": "?"})
        self.assertFalse(result.ok)
        self.assertIn("could not look", result.error)

    async def test_one_path_as_a_string_is_accepted(self):
        result = await self._run({"paths": "workspace/scratch/frame_01.png", "question": "?"})
        self.assertTrue(result.ok, result.error)


if __name__ == "__main__":
    unittest.main()
