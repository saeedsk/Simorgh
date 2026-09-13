"""Meeting someone by voice (voice/introduce.py): the name and relation
parsers, the "learn X's voice" request, the state machine against a
real SpeakerBook, and the unknown-voice counter."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.introduce import Introduction, UnknownVoices, learn_request, name_in, relation_in
from simorgh.voice.speakers import SpeakerBook


def _vec(angle: float, dim: int = 8) -> list[float]:
    v = [0.0] * dim
    v[0], v[1] = math.cos(angle), math.sin(angle)
    return v


class ParsersTestCase(unittest.TestCase):
    def test_names(self):
        for text, want in (("My name is Aran.", "Aran"), ("I'm Iris", "Iris"), ("it's ira", "Ira"), ("Soodeh", "Soodeh"),
                           ("this is Saeed speaking", "Saeed"), ("call me Sam", "Sam"), ("skip", ""), ("what do you mean", ""),
                           ("I'm not telling you", "")):
            self.assertEqual(name_in(text), want, text)

    def test_relations(self):
        self.assertEqual(relation_in("I'm Saeed's son."), "Saeed's son")
        self.assertEqual(relation_in("the mother"), "mother")
        self.assertEqual(relation_in("skip"), ""); self.assertEqual(relation_in("no thanks"), ""); self.assertEqual(relation_in(""), "")
        self.assertEqual(relation_in("Okay, do you want to learn my voice?"), "", "a question is not a relation")
        self.assertEqual(relation_in("well I suppose you could say I live here most days"), "", "nor is a sentence")

    def test_learn_requests(self):
        self.assertEqual(learn_request("Sim, learn Aran's voice"), "Aran")
        self.assertEqual(learn_request("please remember Iris's voice"), "Iris")
        self.assertEqual(learn_request("meet Soodeh"), "Soodeh")
        self.assertEqual(learn_request("learn my voice", speaker="Ira"), "Ira")
        self.assertEqual(learn_request("learn my voice"), "?")
        self.assertEqual(learn_request("what time is it"), ""); self.assertEqual(learn_request("learn the piano"), "The" if False else learn_request("learn the piano"))
        self.assertEqual(learn_request("learn the piano"), "")


class IntroductionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(Path(self.tmp.name), threshold=0.5, margin=0.06)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_whole_conversation_enrols_three_takes(self):
        intro = Introduction()
        intro.vectors.append(_vec(0.0))                       # the turn that triggered the question
        step = intro.feed("My name is Aran", _vec(0.02), self.book)
        self.assertIn("Nice to meet you, Aran", step.say); self.assertFalse(step.done)
        step = intro.feed("I'm Saeed's son", _vec(0.04), self.book)
        # three vectors gathered: the trigger, the name, the relation -- all three takes at once
        self.assertTrue(step.done); self.assertIn("know your voice", step.say); self.assertEqual(step.enrolled, "Aran")
        person = self.book.get("Aran")
        self.assertEqual((len(person.embeddings), person.relation), (3, "Saeed's son"))

    def test_a_name_first_then_takes_one_at_a_time(self):
        intro = Introduction(); intro.name = "Iris"; intro.stage = "take"
        step = intro.feed("hello there", _vec(0.0), self.book)
        self.assertIn("2 more", step.say); self.assertFalse(step.done)
        step = intro.feed("the pool is warm", None, self.book)
        self.assertIn("enough voice", step.say)
        step = intro.feed("the pool is warm", _vec(0.05), self.book)
        self.assertIn("one more", step.say)
        step = intro.feed("and the garden lights are on", _vec(0.03), self.book)
        self.assertTrue(step.done); self.assertEqual(len(self.book.get("Iris").embeddings), 3)

    def test_no_name_twice_gives_up_politely(self):
        intro = Introduction()
        self.assertIn("did not catch", intro.feed("what?", _vec(0.0), self.book).say)
        step = intro.feed("why do you ask", _vec(0.0), self.book)
        self.assertTrue(step.done); self.assertIn("another time", step.say); self.assertEqual(self.book.people(), [])

    def test_a_voice_that_sounds_like_someone_enrolled_is_not_merged(self):
        self.book.enroll("Ira", _vec(0.0))
        intro = Introduction(); intro.vectors.append(_vec(0.02))
        intro.feed("I'm Iris", _vec(0.03), self.book)
        step = intro.feed("her twin", _vec(0.01), self.book)
        self.assertTrue(step.done); self.assertIn("sounds like Ira", step.say)
        self.assertIsNone(self.book.get("Iris"))

    def test_unknown_voices_are_counted_by_likeness_within_the_window(self):
        clock = [1000.0]
        unknown = UnknownVoices(threshold=0.55, window_s=600.0, clock=lambda: clock[0])
        self.assertEqual(unknown.note(_vec(0.0)), 1)
        self.assertEqual(unknown.note(_vec(2.0)), 1, "a different voice does not count for the first")
        self.assertEqual(unknown.note(_vec(0.05)), 2, "the first voice again")
        clock[0] += 700.0
        self.assertEqual(unknown.note(_vec(0.05)), 1, "forgotten after the window")
