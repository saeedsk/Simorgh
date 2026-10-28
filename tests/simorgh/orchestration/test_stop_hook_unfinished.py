"""A chat reply that announces its own next step is sent back to do it.

Live 2026-10-28, asked to unsubscribe from six senders one at a time, Sim
did one and ended its turn: "Temu is done ... Next I'll work through
Michaels, Equifax, Expedia, FOX One and BigFuture, one at a time." Asked
what happened: "the turn got cut off ... I'll start on Michaels now" --
and that turn ended there too. A final answer ends the turn; nothing had
cut either off."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace as N

from simorgh.orchestration import profiles, stophook
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

SAID = ("Temu is done: one-click, HTTP 200. Next I'll work through Michaels, Equifax, Expedia, "
        "FOX One and BigFuture, one at a time.")


def _chat():
    return N(profile=N(scaffold="chat", tools=("mail_unsubscribe", "mail_search")), steps=[])


class TheWords(unittest.TestCase):
    def test_the_live_replies(self):
        self.assertIn("Next I'll work through", stophook.announced_next_step(SAID, _chat()))
        self.assertTrue(stophook.announced_next_step(
            "Only Temu is done. I'll start on Michaels now and go one at a time.", _chat()))

    def test_offers_questions_and_plain_answers_are_left_alone(self):
        for said in ("Want me to retry them one at a time?", "If you want, I'll go through the rest.",
                     "It's late, so I'll keep it short.", "The lights are off.",
                     "Under Armour is done; the other five were done too."):
            self.assertEqual(stophook.announced_next_step(said, _chat()), "", said)

    def test_only_chat_with_tools(self):
        self.assertEqual(stophook.announced_next_step(SAID, N(profile=N(scaffold="task", tools=("x",)), steps=[])), "")
        self.assertEqual(stophook.announced_next_step(SAID, N(profile=N(scaffold="chat", tools=()), steps=[])), "")


async def _turn(h, script):
    cognition = FakeCognition(h.client("cognition"), script=list(script))
    gx = FakeGuardianExecution(h.client("guardian"))
    await cognition.start()
    await gx.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0, assemble_timeout_s=0.05)
    session = Session(task_id="t0", kind="chat", mode="execute", profile=profiles.CHAT, user_text="unsubscribe all")
    await asyncio.wait_for(runner.run(session, user_text="unsubscribe all"), timeout=10)
    await cognition.stop()
    await gx.stop()
    return cognition.calls, session


class InATurn(unittest.TestCase):
    @run
    async def test_the_promise_is_sent_back_and_the_work_goes_on(self):
        script = [{"text": SAID},
                  {"tool_calls": [{"tool": "mail_search", "args": {"query": "Michaels"}}]},
                  {"text": "Michaels is done."}]
        async with Harness() as h:
            calls, session = await _turn(h, script)
        self.assertEqual(len(calls), 3)
        self.assertIn("your turn ends the moment you answer", str(calls[1].payload["messages"][-1]["content"]))
        self.assertEqual(session.unfinished_nudged_at, 0)

    @run
    async def test_saying_it_again_with_nothing_run_is_not_sent_back_twice(self):
        script = [{"text": SAID}, {"text": SAID}, {"text": "never asked"}]
        async with Harness() as h:
            calls, _ = await _turn(h, script)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
