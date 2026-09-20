"""The book of voices (voice/speakers.py): enrolment, the threshold and
margin rules, refusing a take that sounds like someone else,
persistence, and honest scores."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.speakers import SpeakerBook, cosine


def _same_voice(k: int, dim: int = 24) -> list[float]:
    """One voice, recorded again: the same direction as `_vec(0.0)` with
    a different room in it. Pairwise cosine ~0.74 -- new enough to be
    worth keeping, close enough to be the same person."""
    v = [0.0] * dim
    v[0] = 1.0
    v[2 + (k % (dim - 2))] = 0.6
    return v


def _vec(angle: float, dim: int = 24) -> list[float]:
    """Unit vectors on a circle in the first two dimensions: their cosine
    is cos(angle difference), so tests can pick similarities exactly.

    The width is only so a take can also vary in a dimension the angle
    does not touch (`_same_voice`), the way a real 192-d embedding
    varies with the room. Every cosine here still comes from the first
    two dimensions alone, so the numbers in these tests are unchanged."""
    v = [0.0] * dim
    v[0], v[1] = math.cos(angle), math.sin(angle)
    return v


class SpeakerBookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(Path(self.tmp.name), threshold=0.5, margin=0.06, clock=lambda: 1_000.0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_enrolment_then_identification_with_scores(self):
        aria, note = self.book.enroll("Ira", _vec(0.0), relation="daughter, 9")
        self.assertEqual(note, "")
        self.book.enroll("Ira", _vec(0.1))
        saeed, note = self.book.enroll("Saeed", _vec(2.0))
        self.assertEqual(note, "")
        who = self.book.identify(_vec(0.05))
        self.assertEqual(who.name, "Ira"); self.assertGreater(who.score, 0.95); self.assertEqual(who.runner_up, "Saeed")
        who = self.book.identify(_vec(2.1))
        self.assertEqual(who.name, "Saeed")
        self.assertEqual([p.name for p in self.book.people()], ["Ira", "Saeed"])
        self.assertEqual(self.book.get("ira").relation, "daughter, 9")
        self.assertEqual(self.book.scores(_vec(0.0))[0][0], "Ira")

    def test_unknown_under_the_threshold_and_too_close_to_call(self):
        self.book.enroll("Ira", _vec(0.0))
        far = self.book.identify(_vec(1.5))   # cos 1.5 rad = 0.07
        self.assertFalse(far.known); self.assertIn("under the threshold", far.reason); self.assertEqual(far.runner_up, "Ira")
        self.book.enroll("Iris", _vec(0.3))   # cos 0.3 = 0.955 from Ira: refused, it sounds like her
        self.assertEqual([p.name for p in self.book.people()], ["Ira"])
        # two voices that are legitimately distinct, and a test sample between them
        self.book.enroll("Iris", _vec(1.1))   # cos 1.1 = 0.45 from Ira: under threshold+margin, accepted
        between = self.book.identify(_vec(0.55))   # cos 0.55 = 0.85 to both
        # two voices this alike, both over the bar: the nearer one, as a probable (2026-09-13)
        self.assertTrue(between.known); self.assertTrue(between.probable); self.assertIn("probably", between.reason)

    def test_a_take_that_sounds_like_someone_else_is_refused_with_the_name(self):
        self.book.enroll("Ira", _vec(0.0))
        person, note = self.book.enroll("Iris", _vec(0.05))
        self.assertIn("sounds like Ira", note); self.assertEqual(person.embeddings, [])
        self.assertIsNone(self.book.get("Iris"))
        # a take unlike a person's own earlier takes is kept: real voices vary that much across a room
        self.book.enroll("Ira", _vec(0.1))
        person, note = self.book.enroll("Ira", _vec(1.7))   # cos 1.7 = -0.13 to her other takes
        self.assertEqual(note, ""); self.assertEqual(len(person.embeddings), 3)
        self.book.enroll("Ira", _vec(0.9)); self.book.enroll("Ira", _vec(-0.7))
        self.assertEqual(self.book.identify(_vec(0.85)).name, "Ira", "the nearest take decides, not the mean")
        # and when the person insists, even a take that sounds like someone else is theirs
        self.book.enroll("Saeed", _vec(-2.5))
        person, note = self.book.enroll("Iris", _vec(-2.52))
        self.assertIn("sounds like Saeed", note)
        person, note = self.book.enroll("Iris", _vec(-2.52), insist=True)
        self.assertEqual(note, ""); self.assertEqual(len(self.book.get("Iris").embeddings), 1)

    def test_the_book_is_plain_json_and_survives_a_new_instance(self):
        self.book.enroll("Ira", _vec(0.0), relation="daughter")
        self.book.heard("Ira")
        path = Path(self.tmp.name) / "Ira.json"
        data = json.loads(path.read_text())
        self.assertEqual((data["name"], data["relation"], data["heard"], len(data["embeddings"])), ("Ira", "daughter", 1, 1))
        again = SpeakerBook(Path(self.tmp.name))
        self.assertEqual(again.identify(_vec(0.02)).name, "Ira")
        self.assertTrue(again.forget("ira")); self.assertFalse(path.exists()); self.assertFalse(again.forget("ira"))
        self.assertEqual(again.identify(_vec(0.0)).reason, "nobody is enrolled")

    def test_a_name_can_carry_how_to_say_it_before_a_voice(self):
        person = self.book.pronounce("Ira", "Ay-raa", relation="daughter, 9")
        self.assertEqual((person.say_as, person.embeddings, person.relation), ("Ay-raa", [], "daughter, 9"))
        self.book.enroll("Iris", _vec(0.0)); self.book.pronounce("Iris", "Ay-rees")
        self.assertEqual(self.book.pronunciations(), {"Ira": "Ay-raa", "Iris": "Ay-rees"})
        self.assertEqual(SpeakerBook(Path(self.tmp.name)).pronunciations()["Ira"], "Ay-raa")
        from simorgh.voice.planner import SpokenResponsePlanner
        planner = SpokenResponsePlanner(pronunciations=self.book.pronunciations)
        self.assertEqual(planner.pronounced("Ira, Iris is at the pool. iris flowers? Irate."), "Ay-raa, Ay-rees is at the pool. Ay-rees flowers? Irate.")

    def test_cosine(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)


class LeanAndRefineTestCase(unittest.TestCase):
    """Under the threshold, a voice is 'probably' the nearest person or
    unknown -- never a stranger to be enrolled; a confident turn teaches
    the book quietly (the creator, 2026-09-13). Saeed's take is at angle
    0, Soodeh's at 2.5 (cosine -0.8 to Saeed's)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(Path(self.tmp.name), threshold=0.5, margin=0.06, lean=0.3)
        self.book.enroll("Saeed", _vec(0.0))
        self.book.enroll("Soodeh", _vec(2.5))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_voice_between_lean_and_threshold_is_probably_the_nearest(self):
        who = self.book.identify(_vec(1.1))           # 0.45 to Saeed, 0.17 to Soodeh
        self.assertEqual((who.name, who.probable), ("Saeed", True))
        self.assertIn("probably Saeed", who.reason)
        far = self.book.identify(_vec(-1.4))          # 0.17 to Saeed, -0.72 to Soodeh: nobody
        self.assertEqual((far.name, far.probable), ("", False))
        self.assertIn("closest is", far.reason)

    def test_no_lean_when_the_runner_up_is_too_close(self):
        self.book.enroll("Aran", _vec(2.55), insist=True)   # a voice as close to Soodeh's as twins
        who = self.book.identify(_vec(1.35))          # Soodeh 0.41, Aran 0.36: within the margin, so no lean
        self.assertEqual(who.name, "")
        self.assertIn("closest is", who.reason)
        self.assertEqual(self.book.identify(_vec(0.6)).name, "Saeed", "a confident match is untouched")

    def test_lean_off_means_unknown_is_unknown(self):
        book = SpeakerBook(self.book._folder, threshold=0.5, margin=0.06, lean=0.0)  # noqa: SLF001
        self.assertEqual(book.identify(_vec(1.1)).name, "")

    def test_a_confident_turn_becomes_a_take_and_a_near_copy_does_not(self):
        self.assertTrue(self.book.refine("Saeed", _vec(0.6)))      # 0.83: clearly confident, and new
        self.assertEqual(len(self.book.get("Saeed").embeddings), 2)
        self.assertFalse(self.book.refine("Saeed", _vec(0.01)), "a near copy of a take teaches nothing")
        self.assertFalse(self.book.refine("Saeed", _vec(-1.1)), "an unsure take never teaches")
        # 0.66 used to be refused as "confident but not clearly so". The bar was
        # +0.20 above the threshold -- above what a real voice scores in a real
        # room -- so the voices that most needed the practice never gave any
        # (the creator, 2026-09-15). It is +0.05 now; the old bar is still a
        # setting, and the clear-of-everyone-else rule is untouched.
        self.assertTrue(self.book.refine("Saeed", _vec(-0.85)), "0.66 is confident enough to teach")
        strict = SpeakerBook(self.book._folder, threshold=0.5, margin=0.06, refine_above=0.2)  # noqa: SLF001
        self.assertFalse(strict.refine("Saeed", _vec(-0.9)), "the old bar refuses it")
        self.assertFalse(self.book.refine("Nobody", _vec(0.0)))

    def test_a_take_near_someone_elses_voice_teaches_nobody(self):
        self.book.enroll("Aran", _vec(0.7), insist=True)          # a voice 0.76 from Saeed's take
        self.assertFalse(self.book.refine("Saeed", _vec(0.35)), "0.94 to Saeed but 0.94 to Aran too: whose lesson?")
        self.assertFalse(self.book.refine("Aran", _vec(0.35)))

    def test_learnt_takes_are_capped_and_the_enrolment_stays(self):
        from simorgh.voice.speakers import MAX_TAKES
        self.book.forget("Soodeh")                                 # alone in the book: nobody to be too close to
        self.book.enroll("Saeed", _vec(0.05)); self.book.enroll("Saeed", _vec(-0.05))
        first_three = [list(v) for v in self.book.get("Saeed").embeddings]
        # Takes of the SAME voice: each new enough to be worth keeping
        # (under REFINE_NOVELTY) and each still looking like the others
        # (over REFINE_AGREE). `_vec` alone cannot express that -- on a
        # circle, anything novel is far -- so this varies a dimension
        # the way a room and a distance vary a real 192-d embedding.
        #
        # It used to march 0.55 rad around the circle, each take
        # confident against the LAST and every one further from the
        # enrolment than the one before. That is drift, and it is how
        # the creator's profile came to hold 21 takes with a median
        # agreement of 0.37 and stop recognising him (2026-09-20); the
        # case now has its own test below.
        accepted = sum(self.book.refine("Saeed", _same_voice(k)) for k in range(1, 20))
        self.assertGreaterEqual(accepted, MAX_TAKES - 3, "takes of one voice are kept")
        person = self.book.get("Saeed")
        self.assertEqual(len(person.embeddings), MAX_TAKES)
        self.assertEqual(person.embeddings[:3], first_three)

    def test_a_take_that_drifts_off_the_person_is_refused(self):
        """The guard the cap test used to walk straight through: each
        take confident against the last, every one further from the
        enrolment. A profile is a description of one voice, and a take
        that does not look like the takes in it does not belong."""
        self.book.forget("Soodeh")
        self.book.enroll("Saeed", _vec(0.05))
        self.book.enroll("Saeed", _vec(-0.05))
        marched = sum(self.book.refine("Saeed", _vec(0.55 * k)) for k in range(1, 12))
        self.assertLessEqual(marched, 3, "a march around the circle is drift, not practice")
