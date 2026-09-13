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

    def test_a_voice_that_sounds_like_someone_enrolled_is_asked_once_then_believed(self):
        self.book.enroll("Ira", _vec(0.0))
        intro = Introduction(); intro.vectors.append(_vec(0.02))
        intro.feed("I'm Iris", _vec(0.03), self.book)
        step = intro.feed("her twin", _vec(0.01), self.book)
        self.assertFalse(step.done); self.assertIn("That sounded like Ira. Once more, Iris?", step.say)
        self.assertIsNone(self.book.get("Iris"))
        step = intro.feed("it is me, Iris", _vec(0.02), self.book)   # she insists: her word counts
        self.assertEqual(step.enrolled, "Iris"); self.assertTrue(step.done)
        self.assertEqual(len(self.book.get("Iris").embeddings), 3)

    def test_unknown_voices_are_counted_by_likeness_within_the_window(self):
        clock = [1000.0]
        unknown = UnknownVoices(threshold=0.55, window_s=600.0, clock=lambda: clock[0])
        self.assertEqual(unknown.note(_vec(0.0)), 1)
        self.assertEqual(unknown.note(_vec(2.0)), 1, "a different voice does not count for the first")
        self.assertEqual(unknown.note(_vec(0.05)), 2, "the first voice again")
        clock[0] += 700.0
        self.assertEqual(unknown.note(_vec(0.05)), 1, "forgotten after the window")


class GuessTestCase(unittest.TestCase):
    """A voice that nearly matches someone enrolled is asked "is that
    you?" (the creator, 2026-09-13: "you know me")."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(Path(self.tmp.name), threshold=0.5, margin=0.06)
        self.book.enroll("Saeed", _vec(0.0))

    def tearDown(self):
        self.tmp.cleanup()

    def _intro(self):
        intro = Introduction(stage="confirm", guess="Saeed")
        intro.vectors.append(_vec(1.0))      # the turn that triggered the question, far from the take on file
        return intro

    def test_yes_keeps_the_turn_as_a_take_for_that_person(self):
        intro = self._intro()
        step = intro.feed("Yes, it's me.", _vec(1.1), self.book)
        self.assertIn("Good, Saeed", step.say); self.assertEqual(step.enrolled, "Saeed")
        self.assertGreaterEqual(len(self.book.get("Saeed").embeddings), 3, "the trigger and the yes are takes, on their word")

    def test_no_asks_for_the_name(self):
        intro = self._intro()
        step = intro.feed("No.", _vec(1.0), self.book)
        self.assertIn("who is this", step.say); self.assertEqual(intro.stage, "ask_name")
        step = intro.feed("My name is Aran", _vec(1.0), self.book)
        self.assertIn("Nice to meet you, Aran", step.say)

    def test_a_name_in_the_answer_wins_over_the_guess(self):
        intro = self._intro()
        step = intro.feed("No, I'm Soodeh", _vec(1.0), self.book)
        self.assertIn("Nice to meet you, Soodeh", step.say)

    def test_two_unclear_answers_and_it_lets_go(self):
        intro = self._intro()
        step = intro.feed("what time is it", _vec(1.0), self.book)
        self.assertIn("Yes or no", step.say); self.assertFalse(step.done)
        step = intro.feed("the pool is warm", _vec(1.0), self.book)
        self.assertTrue(step.done)


class HouseholdTestCase(unittest.TestCase):
    """The family is known by name before any voice (contracts/household.py)."""

    def setUp(self):
        from simorgh.contracts.household import HOUSEHOLD
        self.tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(Path(self.tmp.name), threshold=0.5, margin=0.06, household=HOUSEHOLD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_book_opens_with_the_family_named_and_pronounced_but_voiceless(self):
        names = sorted(p.name for p in self.book.people())
        self.assertEqual(names, ["Aran", "Ira", "Iris", "Saeed", "Soodeh"])
        aran = self.book.get("Aran")
        self.assertEqual((aran.relation, aran.say_as, len(aran.embeddings)), ("", "ɑːˈɹɑːn", 0),
                         "a name and its sound are given; a relation is learnt")
        self.assertEqual(self.book.get("Saeed").relation, "Sim's creator")
        self.assertEqual(self.book.identify(_vec(0.0)).reason, "nobody is enrolled", "a name is not a voice")

    def test_a_family_member_whose_relation_is_known_is_not_asked_it_again(self):
        intro = Introduction()
        step = intro.feed("My name is Saeed", _vec(0.0), self.book)
        self.assertIn("Hello, Saeed!", step.say)
        self.assertNotIn("related", step.say)
        self.assertEqual(intro.relation, "Sim's creator")

    def test_a_family_member_with_no_relation_yet_is_asked_and_may_skip(self):
        intro = Introduction()
        step = intro.feed("My name is Iris", _vec(0.0), self.book)
        self.assertIn("related", step.say)
        step = intro.feed("skip", _vec(0.01), self.book)
        self.assertEqual(self.book.get("Iris").relation, "", "optional, learnt later")
        self.assertEqual(intro.relation, "")

    def test_what_the_household_wrote_about_a_person_is_kept(self):
        saeed = self.book.get("Saeed")
        saeed.relation = "the boss"
        self.book._save(saeed)  # noqa: SLF001
        from simorgh.contracts.household import HOUSEHOLD
        again = SpeakerBook(Path(self.tmp.name), threshold=0.5, margin=0.06, household=HOUSEHOLD)
        self.assertEqual(again.get("Saeed").relation, "the boss")


class ScaffoldTestCase(unittest.TestCase):
    def test_the_model_is_told_the_household_and_how_to_be_with_a_child(self):
        from simorgh.orchestration.scaffolds import who_is_here
        text = who_is_here("Ira", "", "")
        for name in ("Saeed", "Soodeh", "Aran", "Ira", "Iris"):
            self.assertIn(name, text)
        self.assertIn("part of this family", text)
        self.assertIn("Ira (girl, 9)", text, "described by the roster when no relation was learnt")
        self.assertIn("who is 9", text)
        self.assertIn("Plain words", text)
        self.assertIn("learn it as you talk", text)
        grown = who_is_here("Soodeh", "Saeed's wife", "")
        self.assertIn("Soodeh (Saeed's wife)", grown, "a learnt relation wins over the roster")
        self.assertNotIn("Plain words", grown)
        unknown = who_is_here("", "", "")
        self.assertIn("do not know this voice", unknown); self.assertIn("Iris", unknown)
