"""A known voice teaches Sim from the turns it actually gets.

The creator, 2026-09-15: "why is sim not improving its voice recognition
... it should be enabled by default". It was on; the bar was +0.20 above
the threshold, above what his own voice scored in his room (0.55), so the
voice that most needed the practice never gave any."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.speakers import SpeakerBook


def _vec(angle: float, dim: int = 8) -> list[float]:
    v = [0.0] * dim
    v[0], v[1] = math.cos(angle), math.sin(angle)
    return v


class TheRefineBar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(Path(self._tmp.name), threshold=0.5, margin=0.06)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_turn_just_over_the_threshold_teaches(self):
        self.book.enroll("Saeed", _vec(0.0))
        before = len(self.book.get("Saeed").embeddings)
        take = _vec(0.95)                                  # ~0.58 against the enrolment take
        self.assertGreater(self.book.score(take, self.book.get("Saeed")), 0.55)
        self.assertTrue(self.book.refine("Saeed", take), "a confident take is kept")
        self.assertEqual(len(self.book.get("Saeed").embeddings), before + 1)

    def test_the_old_bar_would_have_refused_it(self):
        self.book.enroll("Saeed", _vec(0.0))
        strict = SpeakerBook(Path(self._tmp.name), threshold=0.5, margin=0.06, refine_above=0.2)
        self.assertFalse(strict.refine("Saeed", _vec(0.95)))

    def test_a_take_close_to_someone_else_still_teaches_nobody(self):
        self.book.enroll("Ira", _vec(0.0))
        self.book.enroll("Iris", _vec(0.05))               # twins: very close voices
        before = len(self.book.get("Ira").embeddings)
        self.assertFalse(self.book.refine("Ira", _vec(0.03)))
        self.assertEqual(len(self.book.get("Ira").embeddings), before)

    def test_enrolment_uses_the_household_spelling(self):
        from simorgh.contracts.household import HOUSEHOLD

        book = SpeakerBook(Path(self._tmp.name), household=HOUSEHOLD)
        person, note = book.enroll("saeed", _vec(0.0))
        self.assertEqual(note, "")
        self.assertEqual(person.name, "Saeed")


if __name__ == "__main__":
    unittest.main()
