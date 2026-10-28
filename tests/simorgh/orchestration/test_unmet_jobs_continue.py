"""Stage 19 item 7b(d): running out of steps is not an ending.

Live 2026-10-28, by voice, the six-step cap ended a job on "Say continue
and I'll run the weekly searches". The creator: "You should do it
automatically. You should not ask me. I already asked you." Another turn
ended on "I can start that if you say so", and nothing ever resumed it.

Now a job whose supervisor bar is unmet, when its steps or budget run out
or its reply asks permission to go on, continues as one background crew
member carrying the criteria, what was tried and the refs in hand; the
person hears one line, and the result is delivered later. `ablate =
["continue"]` is the turn as it was."""

from __future__ import annotations

import json
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import stophook, supervisor

from .harness import Harness, run
from .test_code_first import _bar, _call, _chat, _said, _turn

SEARCH = {"tool_calls": [_call("web_search", query="every item of the period")]}
MEETS = json.dumps({"verdict": "meets_bar"})
BELOW = json.dumps({"verdict": "below_bar", "unmet": ["the whole period"], "principle": "Ownership",
                    "feedback": "Only the first page was read.", "next": "fetch the rest"})
FOUND = {"text": "All ten, from every page: alpha 212, beta 190."}


def _collector(h, *types):
    seen: list = []

    async def on(message):
        seen.append(message)

    async def start():
        for t in types:
            await h.client("observer").subscribe(t, on)

    return seen, start


class OutOfStepsGoesOnInTheBackground(unittest.TestCase):
    @run
    async def test_a_spoken_job_that_runs_out_of_steps_continues_and_is_delivered(self):
        searches = [{"tool_calls": [_call("web_search", i, query=f"page {i}")]} for i in range(6)]
        async with Harness() as h:
            seen, start = _collector(h, topics.PERCEPT_TIME_SCHEDULED)
            await start()
            session = _chat("voice-1", channel="voice", speaker="Soodeh", steps=6,
                            text="go through every item of the last 30 days and give me the top 10")
            cognition, outcome, runner = await _turn(
                h, session, {"voice-1": searches, "voice-1-h1": [FOUND]}, bars={"*": _bar("direct")},
                until=lambda: seen)
        self.assertEqual(outcome.kind, "completed")
        self.assertEqual(outcome.result_summary, supervisor.CONTINUES_ACK, "one line, never 'if you say so'")
        self.assertEqual(session.continued_as, "voice-1-h1")
        brief = _said(cognition.calls["voice-1-h1"][0])
        self.assertIn("ran out of steps", brief)
        self.assertIn("Done when: the exact top ten over the whole period", brief)
        self.assertIn("Already tried", brief)
        self.assertIn("web_search [ok]", brief)
        self.assertIn(session.result_refs[-1], brief, "the refs in hand go with it")
        self.assertIn("never ask the person whether to go on", brief)
        self.assertIn("alpha 212", seen[0].payload["label"])
        self.assertEqual(seen[0].payload["person"], "Soodeh")
        self.assertTrue(any("continues in the background as voice-1-h1" in s.summary for s in session.steps))

    @run
    async def test_a_last_answer_below_the_bar_continues_instead_of_going_out(self):
        script = [SEARCH, SEARCH, {"text": "Here are the first twenty I could see."}]
        async with Harness() as h:
            seen, start = _collector(h, topics.UI_NOTICE)
            await start()
            session = _chat(text="the top ten over the whole period", steps=3)
            _, outcome, _ = await _turn(h, session, {"chat-1": script, "chat-1-h1": [FOUND]},
                                        bars={"*": _bar("direct")}, reviews=[BELOW], until=lambda: seen)
        self.assertEqual(outcome.result_summary, supervisor.CONTINUES_ACK)
        self.assertIn("alpha 212", seen[0].payload["text"])

    @run
    async def test_a_met_bar_ends_the_turn_as_it_was(self):
        script = [SEARCH, SEARCH, FOUND]
        async with Harness() as h:
            session = _chat(text="the top ten", steps=3)
            _, outcome, runner = await _turn(h, session, {"chat-1": script}, bars={"*": _bar("direct")},
                                             reviews=[MEETS])
        self.assertEqual(outcome.result_summary, FOUND["text"])
        self.assertEqual(session.continued_as, "")
        self.assertNotIn("chat-1", runner._crews)  # noqa: SLF001

    @run
    async def test_no_bar_means_no_continuation(self):
        searches = [SEARCH] * 3 + [{"text": "What I found."}]
        async with Harness() as h:
            session = _chat(text="x", steps=3)
            _, outcome, _ = await _turn(h, session, {"chat-1": searches}, bars={"*": json.dumps({"criteria": []})})
        self.assertNotEqual(outcome.result_summary, supervisor.CONTINUES_ACK)

    @run
    async def test_ablate_continue_is_the_turn_as_it_was(self):
        searches = [{"tool_calls": [_call("web_search", i, query=f"p{i}")]} for i in range(3)] + [
            {"text": "What I found so far."}]
        async with Harness() as h:
            session = _chat(text="x", steps=3)
            _, outcome, _ = await _turn(h, session, {"chat-1": searches}, bars={"*": _bar("direct")},
                                        ablate=("continue",))
        self.assertEqual(outcome.result_summary, "What I found so far.", "the wrap-up answer, as before")
        self.assertEqual(session.continued_as, "")


class AskingToGoOnIsNotAnAnswer(unittest.TestCase):
    @run
    async def test_asked_once_it_is_sent_back_to_do_it(self):
        script = [SEARCH, {"text": "I have the first page. Say continue and I'll run the weekly searches."},
                  SEARCH, FOUND]
        async with Harness() as h:
            session = _chat(text="the top ten over the whole period")
            cognition, outcome, _ = await _turn(h, session, {"chat-1": script}, bars={"*": _bar("direct")})
        back = str(cognition.calls["chat-1"][2].payload["messages"][-1]["content"])
        self.assertIn("do not ask permission for it", back)
        self.assertEqual(outcome.result_summary, FOUND["text"])

    @run
    async def test_asked_again_with_nothing_run_it_goes_on_in_the_background(self):
        ask = {"text": "I can start that if you say so."}
        async with Harness() as h:
            seen, start = _collector(h, topics.UI_NOTICE)
            await start()
            session = _chat(text="the top ten over the whole period")
            _, outcome, _ = await _turn(h, session, {"chat-1": [SEARCH, ask, ask], "chat-1-h1": [FOUND]},
                                        bars={"*": _bar("direct")}, until=lambda: seen)
        self.assertEqual(outcome.result_summary, supervisor.CONTINUES_ACK)
        self.assertTrue(any("stopped to ask permission" in s.summary for s in session.steps))

    def test_the_asks_are_general(self):
        for text in ("Say continue and I'll run the weekly searches.", "I can start that if you say so.",
                     "Want me to keep going?", "Shall I do the rest?", "Would you like me to finish the list?"):
            self.assertTrue(stophook.asks_to_continue(text), text)
        for text in ("Here are the top ten.", "Done: all six are unsubscribed.", "The kitchen light is off."):
            self.assertEqual(stophook.asks_to_continue(text), "", text)


if __name__ == "__main__":
    unittest.main()
