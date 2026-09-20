"""Stage 6 item 3: a turn a person is having in the house knows what the
house is doing -- and says "not looked lately" rather than reporting a
stale reading as the state now."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler, WORLD_NOW_HEADER

from .harness import Harness, run


class TheWorldNowBlock(unittest.TestCase):
    @run
    async def test_the_fresh_house_reaches_the_prompt(self):
        async with Harness() as h:
            world = h.client("worldmodel")

            async def _facet(message):
                if message.payload.get("what") != "home":
                    return
                await world.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                    "ok": True, "facet": "home", "as_of": 0.0,
                    "entities": [{"key": "tv.family_room", "state": "playing", "age_s": 120.0, "stale": False},
                                 {"key": "camera.pool", "state": "person", "age_s": 30.0, "stale": False},
                                 {"key": "light.garage", "state": "on", "age_s": 99999.0, "stale": True}],
                    "presence": {"Ira": {"living room": 0.82}, "Saeed": {"unknown": 1.0}},
                    "situation": {"tv_playing": True, "child_alone": True, "quiet_hours": False}})

            sub = await world.subscribe(topics.WORLD_ENV_QUERY, _facet)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT, user_text="hello")
            messages = await assembler.assemble(session, "chat", user_text="hello")
            await sub.unsubscribe()

        block = next((m["content"] for m in messages if m["content"].startswith(WORLD_NOW_HEADER)), "")
        self.assertIn("tv.family_room: playing", block)
        self.assertIn("Ira: probably in the living room (82%)", block)
        self.assertIn("Saeed: not seen anywhere lately", block)
        self.assertIn("child alone", block)
        self.assertNotIn("light.garage", block, "a stale reading is not the state now")

    @run
    async def test_a_task_session_does_not_pay_for_it(self):
        async with Harness() as h:
            world, asked = h.client("worldmodel"), []

            async def _facet(message):
                asked.append(message.payload.get("what"))
                await world.reply(message, type=topics.WORLD_ENV_QUERY_REPLY,
                                  payload={"ok": True, "facet": message.payload.get("what"), "as_of": 0.0})

            sub = await world.subscribe(topics.WORLD_ENV_QUERY, _facet)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t2", kind="patch", mode="execute", profile=profiles.PATCH, user_text="fix it")
            await assembler.assemble(session, "patch", user_text="fix it")
            await sub.unsubscribe()
        self.assertNotIn("home", asked, "a patch session is not in the room")


if __name__ == "__main__":
    unittest.main()
