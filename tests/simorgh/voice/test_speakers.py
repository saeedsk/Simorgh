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


def _vec(angle: float, dim: int = 8) -> list[float]:
    """Unit vectors on a circle in the first two dimensions: their cosine
    is cos(angle difference), so tests can pick similarities exactly."""
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
        self.assertFalse(between.known); self.assertIn("too close to call", between.reason)

    def test_a_take_that_sounds_like_someone_else_is_refused_with_the_name(self):
        self.book.enroll("Ira", _vec(0.0))
        person, note = self.book.enroll("Iris", _vec(0.05))
        self.assertIn("sounds like Ira", note); self.assertEqual(person.embeddings, [])
        self.assertIsNone(self.book.get("Iris"))
        # and a take nothing like a person's own earlier takes is refused too
        self.book.enroll("Ira", _vec(0.1))
        person, note = self.book.enroll("Ira", _vec(1.7))   # cos 1.7 = -0.13
        self.assertIn("does not sound like Ira", note); self.assertEqual(len(person.embeddings), 2)
        # ...while a take merely far from the mean but near one earlier take is a person's normal range
        self.book.enroll("Ira", _vec(0.9)); self.book.enroll("Ira", _vec(-0.7))
        self.assertEqual(self.book.identify(_vec(0.85)).name, "Ira", "the nearest take decides, not the mean")

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
