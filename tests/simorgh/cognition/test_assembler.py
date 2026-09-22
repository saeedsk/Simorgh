"""`PromptAssembler` (docs/blueprint/subsystems/04-cognition.md section
5, "Prompt assembly order"): protected blocks in order, and graceful
omission when `persona.voice`/`self.summary` are unreachable -- Cognition
must work whether or not those subsystems exist yet (principle 4.5's
spirit applied to subsystem absence, not just providers)."""

from __future__ import annotations

import unittest

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.cognition.assembler import CONSTITUTION_SUMMARY, PromptAssembler
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class TestPromptAssemblerNoResponders(unittest.IsolatedAsyncioTestCase):
    """Nobody answers persona.voice/self.summary -- both must be omitted,
    never fatal, and constitution + conversation must still assemble."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        backend = make_backend(BusConfig(backend="memory", request_default_timeout=1.0), clock=self.clock)
        self.bus = make_client(backend, source="cognition", clock=self.clock)
        await self.bus.start()
        self.assembler = PromptAssembler(self.bus, "cognition", request_timeout=0.05, logger=_Logger())

    async def asyncTearDown(self):
        await self.bus.stop()

    async def test_constitution_block_is_always_first_and_protected(self):
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(result.blocks[0].name, "constitution")
        self.assertTrue(result.blocks[0].protected)
        self.assertEqual(result.blocks[0].text, CONSTITUTION_SUMMARY)

    async def test_unreachable_voice_and_summary_are_omitted_not_fatal(self):
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        names = [b.name for b in result.blocks]
        self.assertNotIn("voice", names)
        self.assertNotIn("self_summary", names)
        self.assertIn("conversation", names)

    async def test_conversation_block_is_unprotected(self):
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        conversation = next(b for b in result.blocks if b.name == "conversation")
        self.assertFalse(conversation.protected)

    async def test_last_step_hint_is_a_turn_note_not_a_system_block(self):
        """Stage 4 item 4: per-step words stay out of the cacheable prefix."""
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}], last_step=True)
        self.assertIn("last step", result.turn_note)
        self.assertNotIn("final_turn_hint", [b.name for b in result.blocks])
        few = await self.assembler.assemble(purpose="chat", messages=[], steps_left=2)
        self.assertIn("2 tool call(s) left", few.turn_note)
        plenty = await self.assembler.assemble(purpose="chat", messages=[], steps_left=9)
        self.assertEqual(plenty.turn_note, "")

    async def test_task_rules_block_is_protected_when_given(self):
        result = await self.assembler.assemble(purpose="plan", messages=[], task_rules="never touch main")
        rules = next(b for b in result.blocks if b.name == "task_rules")
        self.assertTrue(rules.protected)
        self.assertEqual(rules.text, "never touch main")


class TestPromptAssemblerWithResponders(unittest.IsolatedAsyncioTestCase):
    """A real (fake, in-test) Persona/World Model answering over the bus
    -- the blocks they provide are included, protected, and in order."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        # The in-memory bus answers at once; the timeout only bounds the
        # blocks nobody answers here, and each of those waited it out (a
        # second apiece, 2-3 s a test).
        backend = make_backend(BusConfig(backend="memory", request_default_timeout=0.05), clock=self.clock)
        self.bus = make_client(backend, source="cognition", clock=self.clock)
        await self.bus.start()
        self.assembler = PromptAssembler(self.bus, "cognition", request_timeout=0.05, logger=_Logger())

        async def _answer_voice(message: Message) -> None:
            await self.bus.reply(message, type=topics.PERSONA_VOICE_REPLY,
                                  payload={"style_block": "speak plainly", "mood_phrase": "steady"})

        async def _answer_summary(message: Message) -> None:
            await self.bus.reply(message, type=topics.SELF_SUMMARY_REPLY,
                                  payload={"text": "I am Simorgh.", "version": 1})

        self._sub_voice = await self.bus.subscribe(topics.PERSONA_VOICE, _answer_voice)
        self._sub_summary = await self.bus.subscribe(topics.SELF_SUMMARY, _answer_summary)

    async def asyncTearDown(self):
        await self._sub_voice.unsubscribe()
        await self._sub_summary.unsubscribe()
        await self.bus.stop()

    async def test_block_order_is_constitution_voice_self_summary_then_conversation(self):
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        names = [b.name for b in result.blocks]
        self.assertEqual(names, ["constitution", "voice", "self_summary", "conversation"])

    async def test_voice_and_self_summary_blocks_are_protected(self):
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        by_name = {b.name: b for b in result.blocks}
        self.assertTrue(by_name["voice"].protected)
        self.assertTrue(by_name["self_summary"].protected)
        self.assertEqual(by_name["voice"].text, "speak plainly")
        self.assertEqual(by_name["self_summary"].text, "I am Simorgh.")


class TestNoHouseholdWideUserProfile(unittest.IsolatedAsyncioTestCase):
    """Stage 6 item 4, 2026-09-22: the assembler used to put ONE
    household-wide profile in every chat prompt as "What you know about
    the user" -- so the nickname Ira asked for was what Sim called her
    father. A `cognition.think` does not say who is speaking, so the
    assembler cannot pick the right person's preferences and must show
    nobody's; Orchestration's per-turn context renders the speaker's.

    Pinned the strong way: even with World Model answering a profile
    that holds Ira's preference, a chat prompt (say, for a turn by
    Saeed) carries no profile block and asks no `world.env.query`."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        backend = make_backend(BusConfig(backend="memory", request_default_timeout=0.05), clock=self.clock)
        self.bus = make_client(backend, source="cognition", clock=self.clock)
        await self.bus.start()
        self.assembler = PromptAssembler(self.bus, "cognition", request_timeout=0.05, logger=_Logger())

    async def asyncTearDown(self):
        await self.bus.stop()

    async def test_a_chat_prompt_shows_nobodys_preferences(self):
        asked = []

        async def _answer(message):
            asked.append(message.payload)
            await self.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                "ok": True, "facet": "user_profile", "as_of": 0.0, "person": "Ira",
                "facets": {"preferred_name": {"value": "Ira-bear", "confidence": 0.7}},
                "text": "What Ira (who is speaking) has told you about themselves: preferred_name: Ira-bear",
            })

        sub = await self.bus.subscribe(topics.WORLD_ENV_QUERY, _answer)
        result = await self.assembler.assemble(
            purpose="chat", messages=[{"role": "user", "content": "Saeed here -- what's for dinner?"}])
        await sub.unsubscribe()

        self.assertNotIn("user_profile", [b.name for b in result.blocks])
        self.assertFalse(any("Ira-bear" in b.text for b in result.blocks))
        self.assertEqual(asked, [], "the assembler must not ask for a profile it cannot attribute")


if __name__ == "__main__":
    unittest.main()
