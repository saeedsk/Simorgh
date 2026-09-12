"""Reading through typos and mishearings (cognition/tidy.py)."""

from __future__ import annotations

import unittest

from simorgh.cognition.tidy import Tidied, accept, dictionary, fix_name, garbled, tidy, unknown_words
from simorgh.contracts import topics

GARBLED = "Sim let sdo somethin gfunnty tday, ther isan even onlne called agencon"
CLEAN = "Sim lets do something funny today, there is an event online called agentcon"


class TestFixName(unittest.TestCase):
    def test_the_recognisers_spellings_of_sim_at_the_start(self) -> None:
        self.assertEqual(fix_name("Seem do something"), "Sim, do something")
        self.assertEqual(fix_name("C do something"), "Sim, do something")
        self.assertEqual(fix_name("hey c, stop"), "hey Sim, stop")
        self.assertEqual(fix_name("Shin, are you there?"), "Sim, are you there?")
        self.assertEqual(fix_name("okay, shin, go on"), "okay, Sim, go on")
        self.assertEqual(fix_name("Hello, Asim."), "Hello, Sim.")  # the creator's screen, 2026-09-12

    def test_english_that_happens_to_contain_those_words_is_left_alone(self) -> None:
        for text in ("They seem happy today", "I can see the file", "the team is here", "sin is a word"):
            self.assertEqual(fix_name(text), text)


class TestGarbled(unittest.TestCase):
    def setUp(self) -> None:
        if not dictionary():
            self.skipTest("no system word list on this machine")

    def test_the_creators_example_is_garbled_and_its_correction_is_not(self) -> None:
        self.assertTrue(garbled(GARBLED))
        self.assertGreaterEqual(len(unknown_words(GARBLED)), 5)
        self.assertFalse(garbled(CLEAN))

    def test_clean_sentences_with_inflections_names_and_code_are_not(self) -> None:
        for text in ("there is an event online called agentcon and we wanted the tests running quickly",
                     "the pool is exhausted so every request waits for a free connection",
                     "run pytest tests/simorgh/voice -q and tell me", "what does SOUL.md say about Simorgh?",
                     "Saeed asked for the Prince of Persia game"):
            self.assertFalse(garbled(text), text)

    def test_a_word_from_the_recent_conversation_is_known(self) -> None:
        self.assertTrue(garbled("the flurb and the zorpish thing"))
        self.assertFalse(garbled("the flurb and the zorpish thing", recent=["we talked about flurb and zorpish"]))


class TestAccept(unittest.TestCase):
    def test_a_rewrite_is_taken_and_an_answer_is_not(self) -> None:
        self.assertEqual(accept(GARBLED, CLEAN), CLEAN)
        self.assertEqual(accept(GARBLED, f'"{CLEAN}"'), CLEAN)
        self.assertIsNone(accept(GARBLED, "Sure! Here is the corrected version:\n\n" + CLEAN))
        self.assertIsNone(accept(GARBLED, ""))
        self.assertIsNone(accept("abc def ghi", "completely other words here"))
        self.assertIsNone(accept("short", "a" * 200))


class _Bus:
    def __init__(self, reply: dict | None = None) -> None:
        self.reply = reply
        self.requests: list = []

    def new(self, topic, payload):
        return (topic, payload)

    async def request(self, message, *, timeout=None):
        self.requests.append(message)
        if self.reply is None:
            raise RuntimeError("no cognition here")

        class _Reply:
            payload = self.reply
        return _Reply()


class TestTidy(unittest.IsolatedAsyncioTestCase):
    async def test_a_clean_line_never_costs_a_call(self) -> None:
        bus = _Bus({"text": "unused"})
        out = await tidy(bus, "what time is it")
        self.assertEqual(out, Tidied(text="what time is it", original="what time is it"))
        self.assertEqual(bus.requests, [])

    async def test_a_mishearing_is_fixed_locally_without_a_call(self) -> None:
        bus = _Bus({"text": "unused"})
        out = await tidy(bus, "Seem do something")
        self.assertEqual(out.text, "Sim, do something")
        self.assertTrue(out.changed)
        self.assertEqual(bus.requests, [])

    async def test_a_garbled_line_is_read_through_by_the_model(self) -> None:
        if not dictionary():
            self.skipTest("no system word list on this machine")
        bus = _Bus({"text": CLEAN, "floor": False})
        out = await tidy(bus, GARBLED, recent=["earlier we discussed agentcon"])
        self.assertEqual(out.text, CLEAN)
        self.assertTrue(out.changed)
        topic, payload = bus.requests[0]
        self.assertEqual(topic, topics.COGNITION_THINK)
        self.assertEqual(payload["purpose"], "chat")
        self.assertLessEqual(payload["budget"]["max_tokens"], 300)
        self.assertIn("agentcon", payload["messages"][0]["content"], "the recent conversation is context")

    async def test_no_provider_or_a_failure_leaves_the_line_as_typed(self) -> None:
        if not dictionary():
            self.skipTest("no system word list on this machine")
        self.assertEqual((await tidy(_Bus({"text": CLEAN, "floor": True}), GARBLED)).text, GARBLED)
        self.assertEqual((await tidy(_Bus(None), GARBLED)).text, GARBLED)
        self.assertEqual((await tidy(None, GARBLED)).text, GARBLED)


if __name__ == "__main__":
    unittest.main()
