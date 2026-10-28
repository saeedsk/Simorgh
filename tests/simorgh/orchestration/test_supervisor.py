"""Sim's supervisor: sets the bar for a job and holds the answer to it
(`[orchestration] supervisor`, `supervisor.py`).

Live 2026-10-28: one sender of six unsubscribed per turn, each turn ended
on "Next I'll work through the rest"; the "top five promo senders of the
month" counted from the newest twenty; "I sent the other five" when the
tool got one. The creator asked for a supervisor that applies Amazon's
Leadership Principles and that Sim must obey."""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace as N

from simorgh.contracts import topics
from simorgh.orchestration import profiles, supervisor
from simorgh.orchestration.api import Session
from simorgh.orchestration.config import Config
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeGuardianExecution
from .harness import Harness, run

BAR = json.dumps({"criteria": [
    {"done_when": "Michaels, Equifax and Expedia are each unsubscribed",
     "measured_by": "an HTTP 2xx per sender from mail_unsubscribe"}]})


class _Cognition:
    """Sim's thinks from `script`; the supervisor's (no tools, its own
    prompt) from `bar` then `reviews`."""

    def __init__(self, bus, script, reviews, bar=BAR):
        self._bus, self._script, self._reviews, self._bar = bus, list(script), list(reviews), bar
        self.sim, self.supervisor = [], []

    async def start(self):
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        said = str(message.payload["messages"][-1].get("content"))
        if said.startswith(supervisor.CRITERIA_PROMPT[:70]):
            self.supervisor.append(message)
            step = {"text": self._bar}
        elif said.startswith(supervisor.REVIEW_PROMPT[:70]):
            self.supervisor.append(message)
            step = {"text": self._reviews.pop(0) if self._reviews else json.dumps({"verdict": "meets_bar"})}
        else:
            self.sim.append(message)
            step = self._script[min(len(self.sim) - 1, len(self._script) - 1)]
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": step.get("text", ""), "tool_calls": step.get("tool_calls", []), "provider": "fake",
            "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False})


async def _turn(h, script, reviews, *, on=True, bar=BAR):
    cognition = _Cognition(h.client("cognition"), script, reviews, bar)
    gx = FakeGuardianExecution(h.client("guardian"))
    await cognition.start()
    await gx.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0,
                           assemble_timeout_s=0.05, supervisor=on)
    session = Session(task_id="t0", kind="chat", mode="execute", profile=profiles.CHAT,
                      user_text="unsubscribe me from Michaels, Equifax and Expedia")
    await asyncio.wait_for(runner.run(session, user_text=session.user_text), timeout=15)
    await cognition.stop()
    await gx.stop()
    return cognition, session


UNSUB = {"tool_calls": [{"tool": "mail_unsubscribe", "args": {"messages": "[g:INBOX:1]"}}]}
BELOW = json.dumps({"verdict": "below_bar", "unmet": ["Equifax and Expedia are not unsubscribed"],
                    "principle": "Ownership", "feedback": "Two of three senders are left.",
                    "next": "Unsubscribe Equifax and Expedia in one call"})


class TheBarIsSetAndHeld(unittest.TestCase):
    @run
    async def test_below_the_bar_the_answer_is_held_and_the_order_followed(self):
        script = [UNSUB, {"text": "Michaels is done."}, UNSUB, {"text": "All three are done."}]
        async with Harness() as h:
            cognition, session = await _turn(h, script, [BELOW, json.dumps({"verdict": "meets_bar"})])
        self.assertEqual(len(cognition.sim), 4)
        said = " ".join(str(m.get("content")) for m in cognition.sim[1].payload["messages"])
        self.assertIn("Your supervisor set the bar", said)
        self.assertIn("Michaels, Equifax and Expedia are each unsubscribed", said)
        order = str(cognition.sim[2].payload["messages"][-1]["content"])
        self.assertIn("BELOW THE BAR (Ownership)", order)
        self.assertIn("Do now: Unsubscribe Equifax and Expedia in one call", order)
        self.assertEqual(len(session.acceptance), 1)
        shown = [s.summary for s in session.steps]
        self.assertTrue(any(s.startswith("supervisor's bar:") for s in shown), shown)
        self.assertTrue(any(s.startswith("supervisor: below bar, 0 of 1 met -- Ownership") for s in shown), shown)

    @run
    async def test_words_alone_are_not_reviewed_twice(self):
        script = [UNSUB, {"text": "Michaels is done."}, {"text": "Michaels is done."}]
        async with Harness() as h:
            cognition, _ = await _turn(h, script, [BELOW, BELOW])
        self.assertEqual(len(cognition.sim), 3, "held once; with no tool run since, the answer goes out")

    @run
    async def test_blocked_lets_an_honest_answer_out(self):
        script = [UNSUB, {"text": "Michaels is done; Equifax only offers a page that needs you to sign in."}]
        blocked = json.dumps({"verdict": "blocked", "unmet": ["Equifax"], "feedback": "needs sign-in"})
        async with Harness() as h:
            cognition, _ = await _turn(h, script, [blocked])
        self.assertEqual(len(cognition.sim), 2)

    @run
    async def test_a_question_gets_no_bar(self):
        script = [UNSUB, {"text": "Done."}]
        async with Harness() as h:
            cognition, session = await _turn(h, script, [], bar=json.dumps({"criteria": []}))
        self.assertEqual(session.acceptance, [])
        self.assertEqual(len(cognition.supervisor), 1, "set nothing, so reviewed nothing")

    @run
    async def test_off_is_the_turn_as_it_was(self):
        async with Harness() as h:
            cognition, session = await _turn(h, [UNSUB, {"text": "Done."}], [BELOW], on=False)
        self.assertEqual(cognition.supervisor, [])
        self.assertEqual(len(cognition.sim), 2)


class TheLogic(unittest.TestCase):
    def test_every_principle_is_a_rule_and_a_check(self):
        names = [p[0] for p in supervisor.PRINCIPLES]
        for must in ("Customer Obsession", "Ownership", "Bias for Action", "Insist on the Highest Standards",
                     "Dive Deep", "Earn Trust", "Deliver Results"):
            self.assertIn(must, names)
        for name, rule, check in supervisor.PRINCIPLES:
            self.assertTrue(rule and check.endswith("?"), name)
        self.assertIn("Check:", supervisor.review_prompt(request="r", criteria=["done when: x"], steps=[], answer="a"))

    def test_criteria_parse_and_refuse_prose(self):
        self.assertEqual(supervisor.parse_criteria(BAR), [
            "done when: Michaels, Equifax and Expedia are each unsubscribed -- measured by: an HTTP 2xx per "
            "sender from mail_unsubscribe"])
        self.assertEqual(supervisor.parse_criteria("Sure, here are the criteria: ..."), [])

    def test_a_review_not_in_shape_is_unread(self):
        self.assertEqual(supervisor.parse_review("looks fine to me")["verdict"], "unread")
        self.assertEqual(supervisor.parse_review('{"verdict": "great"}')["verdict"], "unread")
        self.assertEqual(supervisor.parse_review(BELOW)["principle"], "Ownership")

    def test_the_tail_of_a_long_result_reaches_the_review(self):
        listing = "81 message(s) " + "x " * 600 + "Stopped at the limit of 20: older matches were not fetched."
        text = supervisor.trajectory([N(tool="mail_search", ok=True, summary=listing)])
        self.assertIn("Stopped at the limit of 20", text)

    def test_the_switch_is_read_from_the_file(self):
        self.assertFalse(Config.from_mapping({"supervisor": False}).supervisor)
        self.assertTrue(Config().supervisor)


if __name__ == "__main__":
    unittest.main()
