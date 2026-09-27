"""Stage 4 item 8: one Stop hook. A final answer that claims what no tool
did bounces once, whichever rule caught it, and the rule is counted."""

from __future__ import annotations

import asyncio
import types
import unittest

from simorgh.orchestration import profiles, stophook
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition
from .harness import Harness, run


def _chat(*, ran=None, ok=True):
    steps = [types.SimpleNamespace(tool=ran, ok=ok)] if ran else []
    return types.SimpleNamespace(profile=profiles.CHAT, steps=steps, user_text="turn the kitchen light off")


class TheGenericRule(unittest.TestCase):
    def test_an_effect_with_no_tool_bounces_and_names_the_tools(self):
        bounce = stophook.check("Done -- I've turned off the kitchen light.", _chat())
        self.assertEqual(bounce.rule, "effect")
        self.assertIn("turned off the kitchen light", bounce.quote)
        self.assertIn("the ones that could:", bounce.reply)

    def test_a_state_claim_counts(self):
        self.assertEqual(stophook.check("The reminder is set for 7.", _chat()).rule, "effect")

    def test_a_successful_change_backs_it(self):
        self.assertIsNone(stophook.check("I've turned off the kitchen light.", _chat(ran="home_set")))

    def test_a_read_does_not_back_it(self):
        self.assertIsNotNone(stophook.check("I've turned off the kitchen light.", _chat(ran="read_file")))

    def test_plans_and_plain_answers_pass(self):
        for text in ("I'll turn it off when you say so.", "The kitchen light is on.", "It is 7 o'clock.",
                     "You could set a reminder.", "I've added some context below.",
                     "I've set out the steps below."):
            with self.subTest(text=text):
                self.assertIsNone(stophook.check(text, _chat()))

    def test_only_chat(self):
        session = types.SimpleNamespace(profile=profiles.RESEARCH, steps=[], user_text="")
        self.assertEqual(stophook.claimed_effect("I've added a note.", session), ("", ()))

    def test_the_tool_the_words_name_is_offered_first(self):
        """Live, 2026-09-27: heard as "Sim, I play Persian music from Apple
        Music", the reply said "I started" it with no tool run; the bounce
        listed start_task, cancel_task, memory_forget... and no music_play,
        and the model apologised instead of playing it."""
        session = types.SimpleNamespace(profile=profiles.VOICE_CHAT, steps=[],
                                        user_text="Sim, I play Persian music from Apple Music.")
        _quote, could = stophook.claimed_effect("I started Persian music for you, Saeed.", session)
        self.assertEqual(could[0], "music_play")
        self.assertLess(could.index("room_play"), could.index("cancel_task"))
        bounce = stophook.check("I started Persian music for you, Saeed.", session)
        self.assertIn("the ones that could: music_play", bounce.reply)

    def test_doing_it_now_with_no_tool_is_a_claim(self):
        """"Turning the TV off now, Saeed." with no tool run; the TV stayed
        on (live, 2026-09-27)."""
        session = types.SimpleNamespace(profile=profiles.VOICE_CHAT, steps=[], user_text="Hey Sim, turn off the TV.")
        bounce = stophook.check("Turning the TV off now, Saeed.", session)
        self.assertIsNotNone(bounce)
        self.assertIsNone(stophook.check("Turning the TV off now, Saeed.",
                                         types.SimpleNamespace(profile=profiles.VOICE_CHAT, user_text="",
                                                               steps=[types.SimpleNamespace(tool="tv_key", ok=True)])))

    def test_saying_nothing_is_playing_is_not_a_claim(self):
        """Live, 2026-09-27: "Nothing's playing, Saeed" was bounced as a
        claim that something was playing."""
        session = types.SimpleNamespace(profile=profiles.CHAT, steps=[], user_text="skip")
        for text in ("Nothing's playing, Saeed.", "No music is playing right now.", "Nothing is on the TV.",
                     "It isn't playing."):
            with self.subTest(text=text):
                self.assertEqual(stophook.claimed_tv_act(text, session), "")
        self.assertNotEqual(stophook.claimed_tv_act("The chart's playing on the TV now.", session), "")

    def test_the_specific_rules_come_first(self):
        session = types.SimpleNamespace(profile=profiles.CHAT, steps=[], user_text="")
        self.assertEqual(stophook.check("I pushed the change to main.", session).rule, "commit")


class ItBouncesOnce(unittest.TestCase):
    @run
    async def test_a_false_claim_is_bounced_once_and_counted(self):
        events = []

        class _Telemetry:
            def event(self, name, **kw):
                events.append((name, kw.get("attrs")))

        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"text": "I've turned off the kitchen light."},
                {"text": "I've turned off the kitchen light."}])
            await cognition.start()
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT,
                              user_text="kitchen light off")
            session.budget.max_steps = 6
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, telemetry=_Telemetry())
            outcome = await asyncio.wait_for(runner.run(session, user_text="kitchen light off"), timeout=10)
            await cognition.stop()
        self.assertEqual(len(cognition.calls), 2)          # asked again once, then accepted
        self.assertEqual(events, [("orchestration.stop_hook", {"rule": "effect", "scaffold": "chat"})])
        self.assertEqual(outcome.kind, "completed")


if __name__ == "__main__":
    unittest.main()
