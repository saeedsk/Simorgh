"""A task waiting on something that never happens has a way back.

`task.wake` is one of three ways a WAITING task returns to AVAILABLE --
its moment passing, its topic being heard, or this -- and it is the only
MANUAL one. Planning has subscribed to it since waiting tasks existed.
Nothing in `simorgh/` ever published it (`tools/scan_half_wired.py`,
2026-09-23): no command, no tool, nothing. A task parked on an event
that never came had no way back at all.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.interface import dispatch
from simorgh.interface.parser import parse


class _Clock:
    def now(self):
        return 0.0


class _Bus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def new(self, type, payload, **_kw):
        return (type, payload)

    async def publish(self, message):
        self.published.append(message)


class AWaitingTaskCanBeWoken(unittest.IsolatedAsyncioTestCase):
    async def _run(self, line: str):
        bus = _Bus()
        command = parse(line)
        outcome = await dispatch.dispatch(command, bus=bus, clock=_Clock(), session_id="s",
                                          vitals=None, ledger=None)
        return bus, outcome

    async def test_waking_one_publishes_the_topic_planning_listens_for(self):
        bus, outcome = await self._run("tasks wake c27949cb5a98")
        self.assertEqual(len(bus.published), 1)
        topic, payload = bus.published[0]
        self.assertEqual(topic, topics.TASK_WAKE)
        self.assertEqual(payload["task_id"], "c27949cb5a98")
        self.assertIn("cli:", payload["why"], "who woke it is part of the record")
        self.assertIn("c27949cb5a98", outcome.text)

    async def test_without_an_id_it_says_how(self):
        bus, outcome = await self._run("tasks wake")
        self.assertEqual(bus.published, [], "nothing is woken by accident")
        self.assertIn("tasks wake <task_id>", outcome.text)

    async def test_the_other_verbs_are_untouched(self):
        for line in ("tasks", "tasks all"):
            bus, _outcome = await self._run(line)
            self.assertEqual([t for t, _ in bus.published], [], line)


if __name__ == "__main__":
    unittest.main()
