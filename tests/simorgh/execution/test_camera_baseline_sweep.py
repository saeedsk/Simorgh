"""Learning a camera's scene is the machine's job (execution/vision.py).

A baseline only ever advanced when motion fired a camera, so a camera
that nothing walks past never learnt one, and the first real event on it
was judged against nothing at all. Seven NVR cameras sat blank that way.

Worse, it made a person responsible for a machine's job. On 2026-09-16
the creator was offered three ways to fix it by hand -- seed from stills,
walk past each camera four times, or change a sample count -- and
answered: "camera baselining should happen automatically, user should
not get bothered with this kind of details, this are machine's job." And
then: "I expect camera motion detect work flawlessly once it is enabled
... don't leave task and corner cases here and there to user."

So the sweep goes and gets them. These tests are about it being bounded
and self-terminating -- a background task that visits cameras forever
would be a worse answer than the blank baseline it replaces.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import types
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolResult
from simorgh.execution.config import Config
from simorgh.execution.vision import CameraVision


class _Logger:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def _note(self, level, event, **kw):
        self.lines.append((level, event))

    def info(self, event, **kw):
        self._note("info", event, **kw)

    def warning(self, event, **kw):
        self._note("warning", event, **kw)

    def debug(self, event, **kw):
        self._note("debug", event, **kw)


class _ListTool:
    def __init__(self, cameras, *, ok=True):
        self._cameras = cameras
        self._ok = ok
        self.calls = 0

    async def run(self, args, *, ctx):
        self.calls += 1
        if not self._ok:
            return ToolResult(ok=False, error="refused: no NVR configured")
        return ToolResult(ok=True, output="...", metadata={"cameras": self._cameras})


class _Registry:
    def __init__(self, **tools):
        self._tools = tools

    def get(self, name):
        return self._tools.get(name)


class BaselineSweepTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.logger = _Logger()
        self.looked: list[tuple[str, str]] = []

    def _vision(self, *, nvr=None, ring=None, **settings):
        config = Config(repo_root=self.root, **settings)
        ctx = types.SimpleNamespace(clock=types.SimpleNamespace(now=lambda: 1_700_000_000.0),
                                    logger=self.logger, ledger=None, bus=None)
        tools = {}
        if nvr is not None:
            tools["cam_list"] = nvr
        if ring is not None:
            tools["ring_list"] = ring
        vision = CameraVision(config=config, registry=_Registry(**tools), ctx=ctx)

        async def _look(payload, camera):
            self.looked.append((camera, str(payload.get("host") or "")))
            vision._busy.discard(camera)  # noqa: SLF001 -- as the real one does

        vision._look = _look  # noqa: SLF001
        return vision

    def _learn(self, camera: str, scene: str = "a driveway and a gate") -> None:
        path = self.root / "workspace/cameras/baselines.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        known = json.loads(path.read_text()) if path.exists() else {}
        known[camera] = {"scene": scene, "samples": [scene]}
        path.write_text(json.dumps(known))

    async def test_it_visits_every_camera_that_has_no_scene(self):
        vision = self._vision(nvr=_ListTool(["Front Window", "Office"]))
        self.assertEqual(sorted(await vision._unlearned()),  # noqa: SLF001
                         [("Front Window", ""), ("Office", "")])

    async def test_a_camera_that_already_knows_its_scene_is_left_alone(self):
        self._learn("Office")
        vision = self._vision(nvr=_ListTool(["Front Window", "Office"]))
        self.assertEqual(await vision._unlearned(), [("Front Window", "")])  # noqa: SLF001

    async def test_ring_cameras_are_named_from_dicts_and_carry_their_host(self):
        """The NVR lists strings and Ring lists dicts; the host has to be
        right or a Ring snapshot skips `_ring_lock` and comes back empty."""
        vision = self._vision(ring=_ListTool([{"name": "Front Door", "kind": "doorbell"}]))
        self.assertEqual(await vision._unlearned(), [("Front Door", "ring")])  # noqa: SLF001

    async def test_a_source_that_refuses_is_skipped_not_fatal(self):
        vision = self._vision(nvr=_ListTool([], ok=False),
                              ring=_ListTool([{"name": "Garden"}]))
        self.assertEqual(await vision._unlearned(), [("Garden", "ring")])  # noqa: SLF001

    async def test_the_sweep_looks_at_each_unlearned_camera(self):
        vision = self._vision(nvr=_ListTool(["Front Window", "Office"]),
                              camera_vision_baseline_first_s=0.0,
                              camera_vision_baseline_every_s=0.0)
        await vision.start()
        await asyncio.sleep(0.05)
        await vision.stop()
        self.assertEqual(sorted({c for c, _ in self.looked}), ["Front Window", "Office"])

    async def test_it_stops_for_good_once_every_camera_knows_its_scene(self):
        """Bounded by construction: a sweep that ran forever would be a
        worse answer than the blank baseline it replaces."""
        self._learn("Front Window")
        self._learn("Office")
        vision = self._vision(nvr=_ListTool(["Front Window", "Office"]),
                              camera_vision_baseline_first_s=0.0,
                              camera_vision_baseline_every_s=0.0)
        await vision.start()
        await asyncio.sleep(0.05)
        self.assertTrue(vision._sweep is None or vision._sweep.done(),  # noqa: SLF001
                        "the sweep should have returned")
        self.assertEqual(self.looked, [])
        self.assertIn(("info", "camera_vision_baselines_complete"), self.logger.lines)

    async def test_it_can_be_switched_off(self):
        vision = self._vision(nvr=_ListTool(["Front Window"]),
                              camera_vision_baseline_sweep=False)
        await vision.start()
        self.assertIsNone(vision._sweep)  # noqa: SLF001

    async def test_vision_being_off_means_no_sweep_either(self):
        vision = self._vision(nvr=_ListTool(["Front Window"]), camera_vision=False)
        await vision.start()
        self.assertIsNone(vision._sweep)  # noqa: SLF001

    async def test_stopping_twice_is_harmless(self):
        vision = self._vision(nvr=_ListTool(["Front Window"]),
                              camera_vision_baseline_first_s=99.0)
        await vision.start()
        await vision.stop()
        await vision.stop()


if __name__ == "__main__":
    unittest.main()
