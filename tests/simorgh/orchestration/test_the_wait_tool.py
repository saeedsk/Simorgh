"""Stage 7 item 5, the session half: `wait` parks the task and ends the
attempt, instead of a worker sleeping with the whole context in hand."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run


class TheWaitTool(unittest.TestCase):
    @run
    async def test_a_duration_parks_the_task(self):
        async with Harness() as h:
            seen = []

            async def _heard(message):
                seen.append(message.payload)

            sub = await h.client("planning").subscribe(topics.TASK_WAITING, _heard)
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_000.0)
            session = Session(task_id="t1", kind="research", mode="execute", profile=profiles.RESEARCH)
            ok, text, _ = await runner._wait(session, {"args": {"argument": "10m"}})  # noqa: SLF001
            await asyncio.sleep(0.02)      # the bus delivers on its own task
            await sub.unsubscribe()
        self.assertTrue(ok)
        self.assertTrue(session.waiting)
        self.assertEqual(seen[0]["until"], 1_600.0)
        self.assertIn("waiting for 10m", text)

    @run
    async def test_an_event_wait_names_the_topic(self):
        async with Harness() as h:
            seen = []

            async def _heard(message):
                seen.append(message.payload)

            sub = await h.client("planning").subscribe(topics.TASK_WAITING, _heard)
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_000.0)
            session = Session(task_id="t2", kind="research", mode="execute", profile=profiles.RESEARCH)
            ok, _text, _ = await runner._wait(  # noqa: SLF001
                session, {"args": {"argument": "until world.home.situation_changed"}})
            await asyncio.sleep(0.02)      # the bus delivers on its own task
            await sub.unsubscribe()
        self.assertTrue(ok)
        self.assertEqual(seen[0]["event"], "world.home.situation_changed")
        self.assertNotIn("until", seen[0], "an event wait has no deadline of its own")

    @run
    async def test_nonsense_is_refused_and_a_chat_turn_may_not_wait(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_000.0)
            task = Session(task_id="t3", kind="research", mode="execute", profile=profiles.RESEARCH)
            ok, text, _ = await runner._wait(task, {"args": {"argument": "for a bit"}})  # noqa: SLF001
            self.assertFalse(ok)
            self.assertIn("say how long", text)
            self.assertFalse(task.waiting)

            chat = Session(task_id="c1", kind="chat", mode="execute", profile=profiles.CHAT)
            ok, text, _ = await runner._wait(chat, {"args": {"argument": "10m"}})  # noqa: SLF001
            self.assertFalse(ok)
            self.assertIn("answered now", text)

    @run
    async def test_it_is_offered_to_a_task_and_not_to_a_chat(self):
        from simorgh.orchestration.session import WAIT

        self.assertIn(WAIT, profiles.RESEARCH.tools + (WAIT,))
        self.assertNotIn(WAIT, profiles.CHAT.tools)


if __name__ == "__main__":
    unittest.main()


class StandingIntents(unittest.TestCase):
    """Stage 7 item 9: "tell me when the TV turns off" is a wait on the
    event, not a model checking in a loop -- a loop costs a call every
    time round and misses whatever happens between two of them."""

    def test_the_prompt_names_the_events_a_task_may_wait_for(self):
        from simorgh.orchestration import scaffolds

        offered = tuple(profiles.RESEARCH.tools) + ("wait",)
        text = scaffolds.render(profiles.RESEARCH, offered=offered, task="tell me when the TV turns off")
        self.assertIn("world.home.situation_changed", text)
        self.assertIn("instead of checking in a loop", text)

    def test_a_task_without_wait_is_not_told_about_them(self):
        from simorgh.orchestration import scaffolds

        text = scaffolds.render(profiles.CHAT, offered=tuple(profiles.CHAT.tools), task="hello")
        self.assertNotIn("world.home.situation_changed", text)

    def test_every_waitable_event_is_a_real_topic(self):
        from simorgh.contracts import topics
        from simorgh.orchestration.scaffolds import WAITABLE_EVENTS

        known = {value for name, value in vars(topics).items() if name.isupper() and isinstance(value, str)}
        for name, _what in WAITABLE_EVENTS:
            with self.subTest(event=name):
                self.assertIn(name, known, "a task waiting for a topic nobody publishes waits for ever")
