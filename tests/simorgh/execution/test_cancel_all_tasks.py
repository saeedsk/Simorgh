""""Just clear all tasks" had no form at all (the creator, 2026-09-15).

`cancel_task` took an id, an origin, or keep-this-one. Asked to stop
everything, Sim wrote the marker with an empty argument five times, was
refused five times, and sent him to the terminal."""

from __future__ import annotations

import types
import unittest

from simorgh.contracts import topics
from simorgh.execution.config import Config
from simorgh.execution.tools import CancelTaskTool

TASKS = [
    {"task_id": "7e7f4e3262ac", "status": "available", "origin": "assistant", "description": "improve voice detection"},
    {"task_id": "06f8e7ca3fa1", "status": "available", "origin": "assistant", "description": "voice matching"},
    {"task_id": "aaaabbbbcccc", "status": "completed", "origin": "human", "description": "done already"},
]


class _Bus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)

    async def request(self, message, timeout: float = 0.0):
        return types.SimpleNamespace(payload={"tasks": TASKS})


class CancelEverything(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = CancelTaskTool(Config())
        self.bus = _Bus()

    async def _run(self, args: dict):
        return await self.tool.run(args, ctx=types.SimpleNamespace(bus=self.bus))

    async def test_all_stops_every_waiting_task(self):
        result = await self._run({"task_id": "all"})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(sorted(result.metadata["cancelled"]), ["06f8e7ca3fa1", "7e7f4e3262ac"])
        self.assertEqual([m.type for m in self.bus.published], [topics.TASK_CANCEL, topics.TASK_CANCEL])
        self.assertNotIn("aaaabbbbcccc", result.metadata["cancelled"], "a finished task is not stopped")

    async def test_the_other_words_for_it(self):
        for word in ("everything", "ALL", "*"):
            self.bus.published.clear()
            result = await self._run({"task_id": word})
            self.assertTrue(result.ok, f"{word}: {result.error}")
            self.assertEqual(len(result.metadata["cancelled"]), 2, word)

    async def test_one_id_still_stops_just_that_one(self):
        result = await self._run({"task_id": "7e7f"})
        self.assertEqual(result.metadata["cancelled"], ["7e7f4e3262ac"])

    async def test_nothing_at_all_says_what_to_say(self):
        result = await self._run({})
        self.assertFalse(result.ok)
        self.assertIn("`all`", result.error)


if __name__ == "__main__":
    unittest.main()
