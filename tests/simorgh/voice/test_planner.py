"""The spoken-response planner (voice/planner.py): speakable text,
semantic chunking, sparse contextual connectors, and never a changed
meaning."""

from __future__ import annotations

import unittest

from simorgh.voice.lang import ENGLISH, FARSI
from simorgh.voice.planner import (CONNECTOR_REST_TURNS, Context, SpokenResponsePlanner, choose_connector,
                                   chunk, sentences, speak_numbers, speakable)


class TestSpeakable(unittest.TestCase):
    def test_markdown_is_stripped_not_read(self) -> None:
        text, omitted = speakable("## Result\n**Done.** It *works* now.")
        self.assertEqual(text, "Result Done. It works now.")
        self.assertEqual(omitted, ())

    def test_code_blocks_are_named_not_read(self) -> None:
        text, omitted = speakable("Run this:\n```bash\nrm -rf build && make\n```\nThen retry.")
        self.assertNotIn("rm -rf", text)
        self.assertIn("code sample on screen", text)
        self.assertIn("code", omitted)

    def test_a_long_inline_command_is_for_the_screen_a_short_term_is_spoken(self) -> None:
        text, omitted = speakable("Use `--verbose` with `python -m pytest tests -q -n auto` to see it.")
        self.assertIn("--verbose", text)
        self.assertNotIn("pytest tests -q", text)
        self.assertIn("code", omitted)

    def test_links_and_citations_are_omitted(self) -> None:
        text, omitted = speakable("See [the docs](https://example.com/x) and https://example.org/y [1] (source: web).")
        self.assertNotIn("http", text)
        self.assertNotIn("[1]", text)
        self.assertNotIn("source:", text)
        self.assertIn("the docs", text)
        self.assertIn("link", omitted)
        self.assertIn("citation", omitted)

    def test_tables_are_named_not_read(self) -> None:
        text, omitted = speakable("Here:\n| a | b |\n|---|---|\n| 1 | 2 |\nThat is all.")
        self.assertNotIn("|", text)
        self.assertIn("table on screen", text)
        self.assertIn("table", omitted)

    def test_paths_are_for_the_screen(self) -> None:
        text, omitted = speakable("I put it in simorgh/greeting.py and tests/simorgh/test_greeting.py.")
        self.assertNotIn("greeting.py", text)
        self.assertIn("path", omitted)
        text2, omitted2 = speakable("Support is open 24/7 and/or by mail.")
        self.assertIn("24/7", text2)
        self.assertNotIn("path", omitted2)

    def test_lists_become_a_spoken_enumeration(self) -> None:
        text, _ = speakable("Two options:\n- restart the pool\n- raise the limit\nPick one.")
        self.assertIn("First, restart the pool.", text)
        self.assertIn("Second, raise the limit.", text)

    def test_numbers_stay_intelligible(self) -> None:
        self.assertEqual(speak_numbers("It is 24.5 now"), "It is twenty-four point five now")
        self.assertEqual(speak_numbers("Use 3.14 and 12%"), "Use three point one four and 12 percent")
        self.assertEqual(speak_numbers("version 2.0.1 in 2026"), "version 2.0.1 in 2026")  # not a decimal

    def test_abbreviations_are_spoken(self) -> None:
        text, _ = speakable("Try a cache, e.g. redis, vs. a queue, etc.")
        self.assertEqual(text, "Try a cache, for example redis, versus a queue, and so on")

    def test_meaning_is_never_altered(self) -> None:
        text, _ = speakable("The pool has 12 connections and 3 are free.")
        self.assertEqual(text, "The pool has 12 connections and 3 are free.")


class TestSentencesAndChunks(unittest.TestCase):
    def test_sentences_do_not_split_numbers_abbreviations_or_quotes(self) -> None:
        self.assertEqual(sentences("It hit 24.5 today. Dr. Lee said \"Stop. Wait.\" Then it worked."),
                         ["It hit 24.5 today.", "Dr. Lee said \"Stop. Wait.\"", "Then it worked."])

    def test_persian_sentence_ends(self) -> None:
        self.assertEqual(sentences("سلام. حالت چطوره؟ خوبم."), ["سلام.", "حالت چطوره؟", "خوبم."])

    def test_the_example_from_the_brief(self) -> None:
        chunks = chunk("Okay — the error is coming from the database connection pool. "
                       "I'd first check whether the pool is exhausting its available connections.")
        self.assertEqual([c.text for c in chunks], [
            "Okay — the error is coming from the database connection pool.",
            "I'd first check whether the pool is exhausting its available connections.",
        ])
        self.assertGreater(chunks[0].pause_ms, 0)
        self.assertEqual(chunks[-1].pause_ms, 0)

    def test_a_long_sentence_splits_at_clause_boundaries_never_inside_a_word(self) -> None:
        long = ("When the pool is exhausted, every new request waits for a connection, and the wait shows up "
                "as latency at the edge, which is why the dashboard looked slow before anything actually failed.")
        chunks = chunk(long, max_chars=80)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(" ".join(c.text for c in chunks), long)
        for c in chunks:
            self.assertLessEqual(len(c.text), 110)
            self.assertTrue(c.text.strip())
            self.assertNotRegex(c.text, r"\w-$")  # never cut inside a hyphenated word

    def test_short_fragments_merge_forward(self) -> None:
        chunks = chunk("Yes. It works now, and the tests pass.")
        self.assertEqual([c.text for c in chunks], ["Yes. It works now, and the tests pass."])

    def test_the_first_chunk_is_short_when_a_boundary_allows(self) -> None:
        text = ("I found the problem in the connection pool configuration, and it explains everything you saw "
                "yesterday afternoon on the dashboard when the traffic spiked.")
        chunks = chunk(text, first_chars=70)
        self.assertLessEqual(len(chunks[0].text), 70)
        self.assertEqual(" ".join(c.text for c in chunks), text)

    def test_each_chunk_carries_its_language(self) -> None:
        chunks = chunk("Sure, here it is in Farsi. سلام، حال شما چطور است؟")
        self.assertEqual([c.language for c in chunks], [ENGLISH, FARSI])


class TestConnectors(unittest.TestCase):
    def _ctx(self, **kw) -> Context:
        base = dict(turns_since_connector=5)
        base.update(kw)
        return Context(**base)

    def test_okay_only_when_acknowledging_a_request(self) -> None:
        self.assertEqual(choose_connector("I'll set that up now.", self._ctx(user_text="can you set up a timer")), "okay")
        self.assertEqual(choose_connector("The pool has 12 connections.", self._ctx(user_text="how big is the pool")), "")

    def test_yeah_when_agreeing_right_when_referring_back(self) -> None:
        self.assertEqual(choose_connector("That's right, the cache is stale.", self._ctx()), "yeah")
        self.assertEqual(choose_connector("As you said, the cache is stale, so it needs a flush.", self._ctx()), "right")

    def test_hmm_only_for_real_uncertainty_ah_only_for_recognition(self) -> None:
        self.assertEqual(choose_connector("I'm not fully certain, but here's what I'd check.", self._ctx()), "hmm")
        self.assertEqual(choose_connector("Found it. The retry loop never sleeps.", self._ctx()), "ah")

    def test_never_on_errors_or_urgent_messages(self) -> None:
        self.assertEqual(choose_connector("I'll stop it now.", self._ctx(user_text="please stop", is_error=True)), "")
        self.assertEqual(choose_connector("I'll stop it now.", self._ctx(user_text="please stop", urgent=True)), "")

    def test_never_doubled_when_the_reply_already_leads_with_one(self) -> None:
        self.assertEqual(choose_connector("Okay, I'll do that.", self._ctx(user_text="please do it")), "")
        self.assertEqual(choose_connector("Sure, on it.", self._ctx(user_text="please do it")), "")

    def test_never_two_turns_in_a_row_and_never_the_same_twice_running(self) -> None:
        self.assertEqual(choose_connector("I'll do that.", self._ctx(user_text="please do it", turns_since_connector=0)), "")
        self.assertEqual(choose_connector("I'll do that.", self._ctx(user_text="please do it",
                                                                     turns_since_connector=CONNECTOR_REST_TURNS - 1)), "")
        self.assertEqual(choose_connector("I'll do that.", self._ctx(user_text="please do it", previous_connector="okay")), "")

    def test_no_repeated_filler_across_a_conversation(self) -> None:
        """Ten turns of requests with action replies: the planner must not
        lead every one with "Okay," -- the rate stays sparse."""
        planner = SpokenResponsePlanner()
        since, previous, used = 99, "", 0
        for _ in range(10):
            plan = planner.plan("I'll set that up now.", Context(user_text="please set it up",
                                                                turns_since_connector=since, previous_connector=previous))
            if plan.connector:
                used += 1
                since, previous = 0, "okay"
            else:
                since += 1
        self.assertLessEqual(used, 4)
        self.assertGreaterEqual(used, 1)


class TestThePlan(unittest.TestCase):
    def test_a_connector_opens_the_first_chunk_in_the_reply_language(self) -> None:
        plan = SpokenResponsePlanner().plan("I'll create the project now. What should we call it?",
                                            Context(user_text="can you make a new project", turns_since_connector=5))
        self.assertEqual(plan.connector, "Okay,")
        self.assertTrue(plan.chunks[0].text.startswith("Okay, I'll create"))
        fa = SpokenResponsePlanner().plan("انجام می‌دم. اسمش چی باشه؟",
                                          Context(user_text="لطفا یه پروژه بساز", turns_since_connector=5))
        self.assertEqual(fa.language, FARSI)
        self.assertEqual(fa.connector, "باشه،")

    def test_a_capital_after_the_connector_is_lowered(self) -> None:
        plan = SpokenResponsePlanner().plan("Done. The file is written.",
                                            Context(user_text="please write the file", turns_since_connector=5))
        self.assertTrue(plan.chunks[0].text.startswith("Okay, done."), plan.chunks[0].text)

    def test_long_answers_are_kept_compact_and_say_so(self) -> None:
        text = " ".join(f"Sentence number {i} says something." for i in range(12))
        plan = SpokenResponsePlanner(max_sentences=4).plan(text)
        self.assertIn("more", plan.omitted)
        self.assertIn("more on screen", plan.text)
        self.assertLessEqual(len(sentences(plan.text)), 5)
        urgent = SpokenResponsePlanner(max_sentences=4).plan(text, Context(urgent=True))
        self.assertNotIn("more", urgent.omitted)

    def test_an_empty_reply_is_spoken_honestly(self) -> None:
        plan = SpokenResponsePlanner().plan("")
        self.assertEqual(plan.text, "I have nothing to say to that.")

    def test_connectors_can_be_switched_off(self) -> None:
        plan = SpokenResponsePlanner(connectors=False).plan("I'll do it now.",
                                                            Context(user_text="please do it", turns_since_connector=5))
        self.assertEqual(plan.connector, "")


if __name__ == "__main__":
    unittest.main()


class UnitsAndCurrencyTestCase(unittest.TestCase):
    """Units and money read as a person reads them (the creator,
    2026-09-12: "120ms" was "one twenty em es", "$104.32/bbl" was
    "dollar ... slash be be el")."""

    def test_the_creators_two_examples(self):
        from simorgh.voice.planner import speak_units
        self.assertEqual(speak_units("it took 120ms"), "it took 120 milliseconds")
        self.assertEqual(speak_units("crude is at $104.32/bbl"), "crude is at 104 dollars and 32 cents per barrel")

    def test_singular_plural_money_and_scales(self):
        from simorgh.voice.planner import speak_units
        self.assertEqual(speak_units("1ms then 2 ms"), "1 millisecond then 2 milliseconds")
        self.assertEqual(speak_units("$120"), "120 dollars")
        self.assertEqual(speak_units("$1.00"), "1 dollar")
        self.assertEqual(speak_units("€2.5k/mo"), "2.5 thousand euros per month")
        self.assertEqual(speak_units("£1,250.50"), "1250 pounds and 50 pence")
        self.assertEqual(speak_units("5m 13s"), "5 minutes 13 seconds")
        self.assertEqual(speak_units("14.5k tokens at 2.8x"), "14.5 thousand tokens at 2.8 times")
        self.assertEqual(speak_units("3GB free, 20°C"), "3 gigabytes free, 20 degrees Celsius")

    def test_letters_without_a_number_and_identifiers_are_left_alone(self):
        from simorgh.voice.planner import speak_units
        for text in ("the ms in the name", "GB", "x86", "af_bella", "5ms3"):
            self.assertEqual(speak_units(text), text, text)

    def test_the_whole_planner_says_it_and_then_words_the_decimal(self):
        from simorgh.voice.planner import speakable
        text, _ = speakable("Latency was 120ms and oil closed at $104.32/bbl.")
        self.assertIn("120 milliseconds", text)
        self.assertIn("104 dollars and 32 cents per barrel", text)
