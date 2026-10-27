""""Is this a chat turn?" -- the `cognition.think` purpose, the streamed
reply, and the honest floor that ends a turn nobody answered as
`completed` with a reason -- goes by `Profile.scaffold == "chat"`, not
the agent's name (wave A review, 2026-10-27). Today's two chat agents
(`agents/chat.md`, `agents/voice_chat.md`) behave exactly as before, and
a later agent on the chat scaffold under another name is treated alike.
"""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition
from .harness import Harness, run

COMPANION = replace(profiles.CHAT, name="companion")


async def _think_payload(profile, *, kind="chat"):
    async with Harness() as h:
        cognition = FakeCognition(h.client("cognition"), script=[{"text": "sure"}])
        await cognition.start()
        runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                               assemble_timeout_s=0.05)
        session = Session(task_id="t", kind=kind, mode="execute", profile=profile, user_text="hello")
        await asyncio.wait_for(runner.run(session, user_text="hello"), timeout=10)
        await cognition.stop()
    return cognition.calls[0].payload


async def _unanswered(profile, *, kind="chat"):
    """No Cognition on the bus: the think times out and the floor decides."""
    async with Harness() as h:
        runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                               assemble_timeout_s=0.05, think_timeout_s=0.05)
        session = Session(task_id="t", kind=kind, mode="execute", profile=profile, user_text="hello")
        return await asyncio.wait_for(runner.run(session, user_text="hello"), timeout=10)


class TodaysChatAgents(unittest.TestCase):
    def test_both_are_on_the_chat_scaffold(self):
        self.assertEqual(profiles.CHAT.scaffold, "chat")
        self.assertEqual(profiles.VOICE_CHAT.scaffold, "chat")
        chats = sorted(k for k, p in profiles.AGENTS.items() if p.scaffold == "chat")
        self.assertEqual(chats, ["chat", "voice_chat"])


class ThePurposeAndTheStream(unittest.TestCase):
    @run
    async def test_chat_voice_chat_and_a_renamed_chat_agent_ask_alike(self):
        for profile in (profiles.CHAT, profiles.VOICE_CHAT, COMPANION):
            payload = await _think_payload(profile)
            self.assertEqual(payload["purpose"], "chat", profile.name)
            self.assertTrue(payload.get("stream"), profile.name)

    @run
    async def test_a_task_profile_still_drafts(self):
        payload = await _think_payload(replace(profiles.RESEARCH, verify=False), kind="research")
        self.assertEqual(payload["purpose"], "draft")
        self.assertNotIn("stream", payload)


class TheHonestFloor(unittest.TestCase):
    @run
    async def test_an_unanswered_chat_turn_completes_with_a_reason(self):
        for profile in (profiles.CHAT, profiles.VOICE_CHAT, COMPANION):
            outcome = await _unanswered(profile)
            self.assertEqual(outcome.kind, "completed", profile.name)
            self.assertTrue(outcome.floor, profile.name)
            self.assertTrue(outcome.reason, profile.name)

    @run
    async def test_an_unanswered_task_is_blocked(self):
        outcome = await _unanswered(profiles.RESEARCH, kind="research")
        self.assertEqual(outcome.kind, "blocked")


if __name__ == "__main__":
    unittest.main()
