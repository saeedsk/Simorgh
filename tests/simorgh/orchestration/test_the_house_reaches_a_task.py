"""Stage 6 item 7: a task runs for minutes and the house does not hold
still for it. A situation that changes reaches the agent working in it,
as an ordinary turn, under the same gate as everything else."""

from __future__ import annotations

import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run


class TheHouseReachesATask(unittest.TestCase):
    @run
    async def test_an_open_task_is_told_and_a_chat_turn_is_not(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            task = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
            task.messages = [{"role": "user", "content": "fix the thing"}]
            chat = Session(task_id="c1", kind="chat", mode="execute", profile=profiles.CHAT)
            chat.messages = [{"role": "user", "content": "hello"}]
            runner._open = {"t1": task, "c1": chat}  # noqa: SLF001 -- as `run` would have left them

            told = runner.note_environment("child_alone", True, people={"Iris": "living room"})

        self.assertEqual(told, 1)
        self.assertIn("child alone is now true", task.messages[-1]["content"])
        self.assertIn("Iris in the living room", task.messages[-1]["content"])
        self.assertEqual(len(chat.messages), 1, "a one-exchange chat turn is left alone")

    @run
    async def test_nothing_open_is_nothing_to_tell(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            self.assertEqual(runner.note_environment("tv_playing", False), 0)


class OnlyChangesAreNews(unittest.TestCase):
    def test_the_facet_reports_a_flip_once(self):
        import time

        from simorgh.worldmodel.facets.home import HomeFacet

        clock = lambda: time.mktime((2026, 9, 19, 21, 0, 0, 0, 0, -1))  # noqa: E731
        home = HomeFacet(clock=clock)
        first = dict(home.changes())
        self.assertIn("tv_playing", first, "the first look reports the state it found")
        self.assertEqual(home.changes(), [], "nothing moved, nothing to say")
        home.observe("tv.family_room", kind="tv", state="playing")
        self.assertEqual(dict(home.changes()).get("tv_playing"), True)
        self.assertEqual(home.changes(), [])


if __name__ == "__main__":
    unittest.main()
