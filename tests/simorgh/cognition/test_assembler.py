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

    async def test_last_step_hint_block_is_protected_and_appended_last(self):
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}], last_step=True)
        self.assertEqual(result.blocks[-1].name, "final_turn_hint")
        self.assertTrue(result.blocks[-1].protected)

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
        backend = make_backend(BusConfig(backend="memory", request_default_timeout=1.0), clock=self.clock)
        self.bus = make_client(backend, source="cognition", clock=self.clock)
        await self.bus.start()
        self.assembler = PromptAssembler(self.bus, "cognition", request_timeout=1.0, logger=_Logger())

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


class TestUserProfileBlock(unittest.IsolatedAsyncioTestCase):
    """2026-09-08 observer finding: World Model's `user_profile` facet was
    fed by Persona's `persona.user_model.updated` but nothing ever read it
    back -- a user who said "call me Al" got no different a reply than one
    who never had. The assembler now asks for it (chat purpose only,
    mirroring where `voice`/`self_summary` already effectively live) and
    includes known facets above the confidence floor as a protected
    block."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        backend = make_backend(BusConfig(backend="memory", request_default_timeout=1.0), clock=self.clock)
        self.bus = make_client(backend, source="cognition", clock=self.clock)
        await self.bus.start()
        self.assembler = PromptAssembler(self.bus, "cognition", request_timeout=1.0, logger=_Logger())

    async def asyncTearDown(self):
        await self.bus.stop()

    async def test_known_facets_above_the_confidence_floor_become_a_block(self):
        async def _answer(message):
            await self.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                "ok": True, "facet": "user_profile", "as_of": 0.0,
                "facets": {"preferred_name": {"value": "Al", "confidence": 0.7}},
            })

        sub = await self.bus.subscribe(topics.WORLD_ENV_QUERY, _answer)
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        await sub.unsubscribe()

        by_name = {b.name: b for b in result.blocks}
        self.assertIn("user_profile", by_name)
        self.assertTrue(by_name["user_profile"].protected)
        self.assertIn("preferred_name: Al", by_name["user_profile"].text)

    async def test_low_confidence_facets_are_omitted(self):
        async def _answer(message):
            await self.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                "ok": True, "facet": "user_profile", "as_of": 0.0,
                "facets": {"preference": {"value": "dark mode", "confidence": 0.2}},
            })

        sub = await self.bus.subscribe(topics.WORLD_ENV_QUERY, _answer)
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        await sub.unsubscribe()

        names = [b.name for b in result.blocks]
        self.assertNotIn("user_profile", names)

    async def test_no_responder_omits_the_block_not_fatal(self):
        result = await self.assembler.assemble(purpose="chat", messages=[{"role": "user", "content": "hi"}])
        names = [b.name for b in result.blocks]
        self.assertNotIn("user_profile", names)

    async def test_non_chat_purposes_never_request_the_user_profile(self):
        requested = []

        async def _answer(message):
            requested.append(message.payload.get("what"))
            await self.bus.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                "ok": True, "facet": "user_profile", "as_of": 0.0,
                "facets": {"preferred_name": {"value": "Al", "confidence": 0.9}},
            })

        sub = await self.bus.subscribe(topics.WORLD_ENV_QUERY, _answer)
        await self.assembler.assemble(purpose="draft", messages=[])
        await sub.unsubscribe()

        self.assertNotIn("user_profile", requested)


if __name__ == "__main__":
    unittest.main()
