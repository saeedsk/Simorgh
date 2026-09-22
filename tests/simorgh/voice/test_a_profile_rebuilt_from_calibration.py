"""`voice calibrate apply`: a profile rebuilt from the calibration set.

Live, 2026-09-22: the creator's profile agreed with itself at 0.83 and
with his own 67 calibration takes at only 0.41, so his turns scored ~0.4.
Rebuilt from the set, held-out takes scored 0.81.
"""

import math
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.speakers import SpeakerBook, coherence


def _vec(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle), 0.0, 0.0]


class ARebuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.book = SpeakerBook(self.folder, threshold=0.5)
        for a in (2.0, 2.05, 2.1):            # a consistent voice from other conditions
            self.book.enroll("Saeed", _vec(a))
        for a in (-1.5, -1.45, -1.4):
            self.book.enroll("Ira", _vec(a))

    def test_the_profile_becomes_the_calibration_voice_and_the_old_one_is_kept(self):
        takes = [(_vec(0.0 + i * 0.01), "en") for i in range(9)] + [(_vec(0.1 + i * 0.01), "fa") for i in range(3)]
        ok, said = self.book.rebuild("Saeed", takes)
        self.assertTrue(ok, said)
        saeed = SpeakerBook(self.folder, threshold=0.5).get("Saeed")
        self.assertGreater(SpeakerBook.score(_vec(0.03), saeed), 0.99)
        self.assertTrue(list(self.folder.glob("Saeed.json.before-*")), "the old profile is kept")
        self.assertIn("en", said)
        self.assertIn("fa", said)

    def test_takes_too_close_to_someone_else_are_refused_unchanged(self):
        before = [list(v) for v in self.book.get("Saeed").embeddings]
        ok, said = self.book.rebuild("Saeed", [(_vec(-1.45 + i * 0.01), "en") for i in range(6)])
        self.assertFalse(ok)
        self.assertIn("Ira", said)
        self.assertEqual(self.book.get("Saeed").embeddings, before)

    def test_takes_that_disagree_with_each_other_are_refused(self):
        scattered = [[1.0, 0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0], [0.6, 0, 0.6, 0.5]]
        ok, said = self.book.rebuild("Saeed", [(v, "en") for v in scattered])
        self.assertFalse(ok)
        self.assertIn("agree with itself", said)

    def test_each_language_is_represented(self):
        takes = [(_vec(i * 0.005), "en") for i in range(40)] + [(_vec(0.05 + i * 0.005), "fa") for i in range(2)]
        ok, said = self.book.rebuild("Saeed", takes)
        self.assertTrue(ok, said)
        self.assertIn("fa", said)


if __name__ == "__main__":
    unittest.main()
