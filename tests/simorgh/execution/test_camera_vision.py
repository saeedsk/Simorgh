"""What the cameras saw (execution/vision.py).

A camera event says "channel 3, person". These tests are about the
sentence that comes back: a couple of stills, a model that can see them,
and the answer on screen with the date and time and out loud.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import types
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolResult
from simorgh.execution.config import Config
import simorgh.execution.vision as vision_mod
from simorgh.execution.vision import CameraVision
from tests.simorgh.helpers import FakeClock, assert_valid


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[tuple] = []

    def warning(self, event, **fields) -> None:
        self.warnings.append((event, fields))

    def info(self, *a, **k) -> None:
        pass

    def debug(self, *a, **k) -> None:
        pass


class _Bus:
    def __init__(self, answer="a delivery van has pulled up and someone is walking to the door") -> None:
        self.published: list = []
        self.requests: list = []
        self._answer = answer

    async def publish(self, message) -> None:
        assert_valid(message)          # every payload here is a real contract
        self.published.append(message)

    async def request_or_error(self, message, *, timeout=None):
        assert_valid(message)
        self.requests.append(message)
        if isinstance(self._answer, dict):
            return types.SimpleNamespace(payload=self._answer)
        return types.SimpleNamespace(payload={"ok": True, "text": self._answer})

    def of_type(self, topic) -> list:
        return [m for m in self.published if m.type == topic]


class _Snapshot:
    """Stands in for `cam_snapshot` / `ring_snapshot`."""

    def __init__(self, name="cam_snapshot", *, ok=True, many=False) -> None:
        self.name = name
        self.calls: list[dict] = []
        self._ok = ok
        self._many = many

    async def run(self, args, *, ctx) -> ToolResult:
        self.calls.append(dict(args))
        if not self._ok:
            return ToolResult(ok=False, error="refused: the camera would not answer")
        index = len(self.calls)
        if self._many:
            return ToolResult(ok=True, metadata={"paths": [f"workspace/cameras/ring/front-{index}.jpg"]})
        return ToolResult(ok=True, metadata={"path": f"workspace/cameras/front-{index}.jpg"})


class _Registry:
    def __init__(self, **tools) -> None:
        self._tools = tools

    def get(self, name):
        return self._tools.get(name)


def _direct(registry):
    """The test's stand-in for the action path: Execution passes
    `SelfActions.run`, which proposes the call and waits for Guardian and
    `_on_approved` (test_own_calls_go_through_guardian.py proves that
    half). Here the fake tool simply answers."""

    async def act(tool_name, args, *, rationale=""):
        return await registry.get(tool_name).run(args, ctx=None)

    return act


class CameraVisionTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.clock = FakeClock()
        self.logger = _Logger()
        self.bus = _Bus()
        self.snapshot = _Snapshot()

    def _knows(self, camera: str = "Front Door",
               scene: str = "a front door, a porch light and a path") -> None:
        """A camera whose usual view Sim has already learnt.

        The first event on an UNKNOWN camera learns the scene and says
        nothing -- deliberately (the creator, 2026-09-16: stop describing
        the house). These tests are about the event that comes after.
        """
        path = self.root / "workspace/cameras/baselines.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({camera: scene}), encoding="utf-8")

    def _vision(self, *, tools=None, **settings) -> CameraVision:
        config = Config(repo_root=self.root, camera_vision_gap_s=0.0, **settings)
        ctx = types.SimpleNamespace(clock=self.clock, logger=self.logger, ledger=None, bus=self.bus)
        registry = _Registry(**({"cam_snapshot": self.snapshot} if tools is None else tools))
        return CameraVision(config=config, registry=registry, ctx=ctx, act=_direct(registry))

    async def _event(self, vision, **payload) -> None:
        body = {"channel": 1, "camera": "Front Door", "kinds": ["person"]}
        body.update(payload)
        await vision.on_camera_event(types.SimpleNamespace(payload=body))
        for task in list(vision._tasks):  # noqa: SLF001 -- the looking runs off the bus handler
            await task

    # -- the whole chain ---------------------------------------------------
    async def test_an_event_becomes_a_described_scene_on_screen_and_out_loud(self):
        self._knows()
        vision = self._vision()
        await self._event(vision)

        self.assertEqual(len(self.snapshot.calls), 2, "a couple of stills, not one")
        self.assertEqual(self.snapshot.calls[0], {"camera": "Front Door"})

        asked = self.bus.requests[-1]
        self.assertEqual(asked.type, topics.COGNITION_THINK)
        self.assertEqual(asked.payload["images"],
                         [str(self.root / "workspace/cameras/front-1.jpg"),
                          str(self.root / "workspace/cameras/front-2.jpg")],
                         "absolute paths: Cognition reads them itself")
        self.assertTrue(asked.payload["require_real_provider"], "no canned floor answer about a camera")
        self.assertIn("Front Door", asked.payload["messages"][0]["content"])
        self.assertIn("person", asked.payload["messages"][0]["content"], "what the camera reported is context")

        notice = self.bus.of_type(topics.UI_NOTICE)[-1].payload["text"]
        self.assertIn("Front Door", notice)
        self.assertIn("a delivery van has pulled up", notice)
        self.assertRegex(notice, r"\d{2} \w{3} \d{2}:\d{2}", f"the date and the time belong on screen: {notice!r}")

        spoken = self.bus.of_type(topics.VOICE_SPEAK_REQUEST)[-1].payload["text"]
        self.assertIn("a delivery van has pulled up", spoken)
        self.assertNotRegex(spoken, r"\d{2}:\d{2}", "nobody wants the timestamp read aloud")

    # -- not once per motion event ----------------------------------------
    async def test_one_camera_is_looked_at_once_until_the_cooldown_passes(self):
        vision = self._vision(camera_vision_cooldown_s=90.0)
        await self._event(vision)
        await self._event(vision)
        self.assertEqual(len(self.bus.requests), 1, "a person in frame keeps firing motion; that is one scene")

        self.clock.advance(91.0)
        await self._event(vision)
        self.assertEqual(len(self.bus.requests), 2)

    async def test_a_different_camera_is_its_own_scene(self):
        vision = self._vision()
        await self._event(vision)
        await self._event(vision, camera="Back Gate")
        self.assertEqual(len(self.bus.requests), 2)

    # -- the other camera source ------------------------------------------
    async def test_a_ring_event_uses_the_ring_camera_and_takes_one_frame(self):
        """One frame from Ring, not two.

        Ring throttles: three cameras firing at once with two stills each
        is six snapshot calls in a few seconds, and every one came back
        empty for a whole day (2026-09-16) while the same cameras answered
        in 2.4s asked singly. The NVR still takes a pair -- it is wired and
        answers concurrently."""
        ring = _Snapshot("ring_snapshot", many=True)
        vision = self._vision(tools={"ring_snapshot": ring, "cam_snapshot": self.snapshot})
        await self._event(vision, host="ring", camera="Driveway")
        self.assertEqual(len(ring.calls), 1, "Ring is asked once")
        self.assertEqual(self.snapshot.calls, [], "a Ring event does not go to the NVR")
        self.assertEqual(self.bus.requests[-1].payload["images"],
                         [str(self.root / "workspace/cameras/ring/front-1.jpg")])

    # -- when it cannot ----------------------------------------------------
    async def test_no_eyes_is_said_once_not_once_per_event(self):
        self._knows()
        self.bus = _Bus(answer={"ok": False, "error": {"code": "no_real_provider",
                                                       "detail": "nothing here can look at a picture"}})
        vision = self._vision(camera_vision_cooldown_s=0.0)
        await self._event(vision)
        await self._event(vision)
        notices = [m.payload["text"] for m in self.bus.of_type(topics.UI_NOTICE)]
        self.assertEqual(len(notices), 1, f"said once: {notices}")
        self.assertIn("could not look", notices[0])
        self.assertEqual(self.bus.of_type(topics.VOICE_SPEAK_REQUEST), [], "nothing true to say, so nothing said")

    async def test_a_camera_that_will_not_give_a_still_says_nothing(self):
        vision = self._vision(tools={"cam_snapshot": _Snapshot(ok=False)})
        await self._event(vision)
        self.assertEqual(self.bus.requests, [], "no stills, no guess about what happened")
        self.assertEqual(self.bus.published, [])
        self.assertTrue(any(e == "camera_vision_snapshot_refused" for e, _f in self.logger.warnings))

    async def test_no_snapshot_tool_at_all_is_quiet(self):
        vision = self._vision(tools={})
        await self._event(vision)
        self.assertEqual(self.bus.published, [])

    # -- the switches ------------------------------------------------------
    async def test_turned_off_nothing_happens(self):
        vision = self._vision(camera_vision=False)
        await self._event(vision)
        self.assertEqual(self.snapshot.calls, [])
        self.assertEqual(self.bus.published, [])

    async def test_the_screen_can_have_it_without_the_voice(self):
        self._knows()
        vision = self._vision(camera_vision_speak=False)
        await self._event(vision)
        self.assertEqual(len(self.bus.of_type(topics.UI_NOTICE)), 1)
        self.assertEqual(self.bus.of_type(topics.VOICE_SPEAK_REQUEST), [])

    async def test_a_model_that_answers_nothing_is_not_announced(self):
        self.bus = _Bus(answer={"ok": True, "text": "   "})
        vision = self._vision()
        await self._event(vision)
        self.assertEqual(self.bus.published, [], "an empty description is not news")



class _VisionHarness(unittest.IsolatedAsyncioTestCase):
    """The rig both camera-vision suites run on: a fake clock, a bus
    that answers with scripted model replies, and one camera event."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.clock = FakeClock()
        self.logger = _Logger()
        self.snapshot = _Snapshot()
        self.asked: list = []

    def _vision(self, answers, *, samples=1):
        """`answers` is consumed one per model call, in order.

        `samples` is how many separate events the camera must see before
        its scene is trusted. Most tests here are about what happens
        AFTER a scene exists, so they take the one-shot form; the
        confirmation itself is tested in `LearningTheSceneTestCase`.
        """
        replies = list(answers)
        outer = self

        class _AskingBus(_Bus):
            async def request_or_error(self, message, *, timeout=None):
                outer.asked.append(message.payload["messages"][0]["content"])
                return types.SimpleNamespace(payload={"ok": True, "text": replies.pop(0)})

        self.bus = _AskingBus()
        config = Config(repo_root=self.root, camera_vision_gap_s=0.0,
                        camera_vision_baseline_samples=samples)
        ctx = types.SimpleNamespace(clock=self.clock, logger=self.logger, ledger=None, bus=self.bus)
        registry = _Registry(cam_snapshot=self.snapshot)
        return CameraVision(config=config, registry=registry, ctx=ctx, act=_direct(registry))

    async def _event(self, vision, **payload):
        body = {"channel": 1, "camera": "Front", "kinds": ["motion"]}
        body.update(payload)
        await vision.on_camera_event(types.SimpleNamespace(payload=body))
        for task in list(vision._tasks):  # noqa: SLF001
            await task


class ReportingTheEventNotTheHouse(_VisionHarness):
    """The creator, live 2026-09-16, after Sim announced "a residential
    street with a driveway ... the street is quiet, with no visible
    movement or people": "you are descbing my home, isntead i expect you
    to describe the event ... avoide telling me imag estatis componenets
    an djust tell me what happened".
    """

    async def test_the_first_event_learns_the_scene_and_says_nothing(self):
        vision = self._vision(["a driveway, a wooden trellis and a garden bed"])
        await self._event(vision)
        self.assertEqual(self.bus.published, [], "learning is not news")
        saved = json.loads((self.root / "workspace/cameras/baselines.json").read_text())
        self.assertIn("driveway", saved["Front"]["scene"])
        self.assertIn("FIXED things", self.asked[0], "it asked for the scene, not the event")

    async def test_a_later_event_is_judged_against_that_scene(self):
        vision = self._vision(["a driveway and a garden bed",
                               "a delivery driver is leaving a parcel by the door"])
        await self._event(vision)
        self.clock.advance(1_000)
        await self._event(vision)
        said = self.bus.of_type(topics.UI_NOTICE)[-1].payload["text"]
        self.assertIn("delivery driver", said)
        self.assertIn("a driveway and a garden bed", self.asked[1], "the scene is given to the model by name")
        self.assertIn("ONLY what is happening", self.asked[1])

    async def test_nothing_but_the_usual_view_is_not_announced(self):
        vision = self._vision(["a driveway and a garden bed", "NOTHING"])
        await self._event(vision)
        self.clock.advance(1_000)
        await self._event(vision)
        self.assertEqual(self.bus.of_type(topics.UI_NOTICE), [], "a quiet street is not an event")
        self.assertEqual(self.bus.of_type(topics.VOICE_SPEAK_REQUEST), [])

    async def test_a_full_stop_does_not_turn_nothing_into_news(self):
        vision = self._vision(["a driveway", "Nothing."])
        await self._event(vision)
        self.clock.advance(1_000)
        await self._event(vision)
        self.assertEqual(self.bus.of_type(topics.UI_NOTICE), [])

    async def test_the_scene_is_learnt_once_and_reused(self):
        vision = self._vision(["a driveway", "NOTHING", "a fox crossing the drive"])
        for _ in range(3):
            await self._event(vision)
            self.clock.advance(1_000)
        self.assertEqual(len(self.asked), 3, "the scene was not re-learnt")
        self.assertIn("fox", self.bus.of_type(topics.UI_NOTICE)[-1].payload["text"])


if __name__ == "__main__":
    unittest.main()


class LearningTheSceneTestCase(_VisionHarness):
    """A camera fires BECAUSE something moved, so the frames it learns
    from are the worst possible evidence for "what is always here".

    Learning from one event made whatever triggered it part of the
    house forever: a car in the drive, a bin at the kerb, a parcel on
    the step. The parcel is the one that bites -- baked into the scene,
    it makes every later delivery "nothing new", and "was there a
    package today?" is what these cameras are actually asked.
    """

    async def test_one_sample_is_not_enough_to_trust(self):
        vision = self._vision(["a driveway and a parked van"], samples=3)
        await self._event(vision)
        saved = json.loads((self.root / "workspace/cameras/baselines.json").read_text())
        self.assertEqual(saved["Front"]["scene"], "", "one look is not a scene")
        self.assertEqual(saved["Front"]["samples"], ["a driveway and a parked van"])

    async def test_nothing_is_announced_while_the_scene_is_still_being_learnt(self):
        vision = self._vision(["a driveway and a van", "a driveway"], samples=3)
        await self._event(vision)
        self.clock.advance(1_000)
        await self._event(vision)
        self.assertEqual(self.bus.published, [], "learning is not news")

    async def test_the_last_sample_confirms_against_the_earlier_ones(self):
        vision = self._vision(["a driveway and a parked van", "a driveway and a bin",
                               "a driveway"], samples=3)
        for _ in range(3):
            await self._event(vision)
            self.clock.advance(1_000)
        self.assertIn("in every one of those descriptions", self.asked[2])
        self.assertIn("a driveway and a parked van", self.asked[2], "the earlier samples are shown")
        self.assertIn("a driveway and a bin", self.asked[2])
        saved = json.loads((self.root / "workspace/cameras/baselines.json").read_text())
        self.assertEqual(saved["Front"]["scene"], "a driveway")

    async def test_the_confirmed_scene_is_what_later_events_are_judged_against(self):
        vision = self._vision(["a driveway and a van", "a driveway and a bin", "a driveway",
                               "a courier leaving a parcel"], samples=3)
        for _ in range(4):
            await self._event(vision)
            self.clock.advance(1_000)
        self.assertIn("a driveway", self.asked[3])
        self.assertIn("parcel", self.bus.of_type(topics.UI_NOTICE)[-1].payload["text"])

    async def test_a_baseline_saved_in_the_older_shape_is_still_honoured(self):
        """The value used to be the scene string itself. A camera that
        already learnt its scene must not have to learn it again."""
        path = self.root / "workspace/cameras/baselines.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"Front": "a driveway and a garden bed"}))
        vision = self._vision(["a fox crossing the drive"], samples=3)
        await self._event(vision)
        self.assertIn("a driveway and a garden bed", self.asked[0])
        self.assertIn("fox", self.bus.of_type(topics.UI_NOTICE)[-1].payload["text"])

    def test_the_scene_prompts_exclude_what_can_walk_or_be_carried_away(self):
        for prompt in (vision_mod.BASELINE_PROMPT, vision_mod.CONFIRM_PROMPT):
            for movable in ("people", "animals", "vehicles", "packages", "bins", "bicycles"):
                self.assertIn(movable, prompt)
        self.assertNotIn("permanently parked vehicles", vision_mod.BASELINE_PROMPT)
