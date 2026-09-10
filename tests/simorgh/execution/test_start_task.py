"""`start_task`: the way out of a one-shot reply.

A chat turn does not resume. It gets a step budget, spends it, and if
the work is unfinished the next message starts again from nothing --
which is why "rebuild the voxel game" was attempted three times on
2026-09-09 and each attempt rewrote the file from scratch. A task
carries its own budget and is re-offered with its work intact.

All of that machinery existed. What was missing was any way to get
from "make me a Minecraft game" to a task without the person knowing
to type `improve ... steps=40` instead."""

from __future__ import annotations

import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.tools import StartTaskTool


class _Reply:
    def __init__(self, payload: dict) -> None:
        self.payload = payload


class _Bus:
    def __init__(self, payload: dict | None = None, *, raises: Exception | None = None) -> None:
        self.payload = payload if payload is not None else {"task_id": "t-42"}
        self.raises = raises
        self.requests: list = []

    async def request(self, message, *, timeout=None):
        self.requests.append(message)
        if self.raises:
            raise self.raises
        return _Reply(self.payload)


def _ctx(bus=None, *, task_id: str | None = None) -> ToolContext:
    return ToolContext(action_id="a1", task_id=task_id, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None, bus=bus)


class StartTaskTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = StartTaskTool(Config())

    async def test_it_creates_a_task(self):
        bus = _Bus()
        result = await self.tool.run({"goal": "rebuild the voxel game"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(bus.requests), 1)
        message = bus.requests[0]
        self.assertEqual(message.type, topics.TASK_CREATE)
        self.assertEqual(message.payload["description"], "rebuild the voxel game")
        self.assertEqual(message.payload["kind"], "patch")
        self.assertEqual(message.payload["mode"], "execute")

    async def test_it_gets_a_real_step_budget_not_a_chat_sized_one(self):
        bus = _Bus()
        await self.tool.run({"goal": "build a game"}, ctx=_ctx(bus))
        self.assertGreaterEqual(bus.requests[0].payload["max_steps"], 40)

    async def test_a_requested_budget_is_honoured(self):
        bus = _Bus()
        await self.tool.run({"goal": "build a game", "steps": 60}, ctx=_ctx(bus))
        self.assertEqual(bus.requests[0].payload["max_steps"], 60)

    async def test_an_absurd_budget_is_capped(self):
        """A misjudged request must not be able to spend an afternoon of
        provider quota before anyone looks."""
        bus = _Bus()
        await self.tool.run({"goal": "build a game", "steps": 100000}, ctx=_ctx(bus))
        self.assertEqual(bus.requests[0].payload["max_steps"], StartTaskTool.MAX_STEPS)

    async def test_a_tiny_budget_is_raised_to_something_usable(self):
        bus = _Bus()
        await self.tool.run({"goal": "build a game", "steps": 1}, ctx=_ctx(bus))
        self.assertGreaterEqual(bus.requests[0].payload["max_steps"], 5)

    async def test_a_subject_file_is_carried_through(self):
        bus = _Bus()
        await self.tool.run({"goal": "rebuild it", "subject": "workspace/midcraft.html"},
                            ctx=_ctx(bus))
        self.assertEqual(bus.requests[0].payload["subject"], "workspace/midcraft.html")

    async def test_no_subject_is_simply_absent_rather_than_empty(self):
        bus = _Bus()
        await self.tool.run({"goal": "look into something"}, ctx=_ctx(bus))
        self.assertNotIn("subject", bus.requests[0].payload)

    async def test_the_kind_can_be_chosen(self):
        bus = _Bus()
        await self.tool.run({"goal": "find out about X", "kind": "research"}, ctx=_ctx(bus))
        self.assertEqual(bus.requests[0].payload["kind"], "research")

    async def test_an_unknown_kind_falls_back_rather_than_failing_the_contract(self):
        bus = _Bus()
        await self.tool.run({"goal": "x", "kind": "nonsense"}, ctx=_ctx(bus))
        self.assertEqual(bus.requests[0].payload["kind"], "patch")

    async def test_it_tells_the_person_what_was_started_and_how_to_watch_it(self):
        result = await self.tool.run({"goal": "build a game"}, ctx=_ctx(_Bus()))
        self.assertIn("t-42", result.output)
        self.assertIn("tasks", result.output)
        self.assertIn("cancel t-42", result.output)

    async def test_it_says_the_task_will_not_start_over(self):
        """The whole reason to reach for it."""
        result = await self.tool.run({"goal": "build a game"}, ctx=_ctx(_Bus()))
        self.assertIn("picks up where it leaves off", result.output)

    async def test_an_empty_goal_is_refused(self):
        result = await self.tool.run({"goal": "   "}, ctx=_ctx(_Bus()))
        self.assertFalse(result.ok)

    async def test_a_duplicate_is_reported_rather_than_started_twice(self):
        bus = _Bus({"task_id": "t-99", "deduplicated_against": "t-7"})
        result = await self.tool.run({"goal": "build a game"}, ctx=_ctx(bus))
        self.assertTrue(result.ok)
        self.assertTrue(result.metadata["deduplicated"])
        self.assertIn("t-7", result.output)

    async def test_a_bus_that_will_not_answer_is_a_result_not_a_crash(self):
        bus = _Bus(raises=TimeoutError("nobody answered"))
        result = await self.tool.run({"goal": "build a game"}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        self.assertIn("could not start", result.error)

    async def test_no_task_id_coming_back_is_not_reported_as_success(self):
        result = await self.tool.run({"goal": "x"}, ctx=_ctx(_Bus({})))
        self.assertFalse(result.ok)

    async def test_without_a_bus_it_says_so(self):
        result = await self.tool.run({"goal": "x"}, ctx=_ctx(None))
        self.assertFalse(result.ok)
        self.assertIn("bus", result.error)


class ForkBombTestCase(unittest.IsolatedAsyncioTestCase):
    """A task that can start tasks is how a quiet afternoon becomes a
    fork bomb. Decomposition is Planning's job and it already does it."""

    async def test_it_refuses_from_inside_a_task(self):
        bus = _Bus()
        result = await StartTaskTool(Config()).run(
            {"goal": "build a game"}, ctx=_ctx(bus, task_id="t-1"))
        self.assertFalse(result.ok)
        self.assertIn("already a task", result.error)
        self.assertEqual(bus.requests, [], "a refusal must not have created anything")

    async def test_only_the_chat_profile_is_offered_it(self):
        from simorgh.orchestration.profiles import BY_KIND

        offered = {kind for kind, profile in BY_KIND.items() if "start_task" in profile.tools}
        self.assertEqual(offered, {"chat"})


class ScaffoldTestCase(unittest.TestCase):
    def test_the_chat_scaffold_says_to_judge_the_size_first(self):
        """A tool nothing tells the model to reach for is a tool that is
        never reached for."""
        from simorgh.orchestration import scaffolds
        from simorgh.orchestration.profiles import CHAT

        # Assert on phrases that survive the paragraph's line wrapping,
        # not on a sentence that happens to break across two lines.
        rendered = " ".join(scaffolds.render(CHAT).split())
        self.assertIn("start_task", rendered)
        self.assertIn("Judge the SIZE first", rendered)
        self.assertIn("does not resume", rendered)

    def test_the_description_explains_the_difference_that_matters(self):
        description = StartTaskTool(Config()).description
        self.assertIn("resumes", description)
