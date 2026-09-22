"""A full profile is the one a relearn exists for.

Live, 2026-09-21: the creator's profile held twelve takes -- MAX_TAKES
-- at 0.66 agreement with itself, and `voice relearn Saeed` answered
"nothing in 0 kept recording(s)" twice. The loop stopped at the cap
before looking at one recording. Replayed on his book with the newest
300 kept turns, the fixed version swaps four weaker takes for four
better ones: 0.66 -> 0.80.
"""

import math
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.speakers import MAX_TAKES, SpeakerBook, coherence


def _vec(angle: float, dim: int = 8) -> list[float]:
    v = [0.0] * dim
    v[0], v[1] = math.cos(angle), math.sin(angle)
    return v


class AFullProfile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = SpeakerBook(Path(self._tmp.name), threshold=0.5, margin=0.06)
        for angle in (0.0, 0.05, 0.10):
            self.book.enroll("Saeed", _vec(angle))
        person = self.book.get("Saeed")
        # nine learnt takes scattered either side -- the muddle
        person.embeddings.extend(_vec(a) for a in (0.9, -0.9, 0.85, -0.85, 0.8, -0.8, 0.95, -0.95, 0.75))
        self.book._save(person)
        self.assertEqual(len(person.embeddings), MAX_TAKES)

    def test_every_recording_is_looked_at(self):
        _, _, considered, _, _ = self.book.relearn("Saeed", [_vec(0.02)] * 5)
        self.assertEqual(considered, 5)

    def test_better_recordings_replace_weaker_takes(self):
        before = coherence(self.book.get("Saeed").embeddings)
        added, dropped, _, was, after = self.book.relearn("Saeed", [_vec(0.03 + i / 100) for i in range(6)])
        self.assertGreater(added, 0)
        self.assertGreater(dropped, 0)
        self.assertAlmostEqual(was, before)
        self.assertGreater(after, before)
        person = SpeakerBook(Path(self._tmp.name)).get("Saeed")
        self.assertLessEqual(len(person.embeddings), MAX_TAKES)
        self.assertEqual(person.embeddings[:3], [_vec(a) for a in (0.0, 0.05, 0.10)])

    def test_somebody_elses_recordings_change_nothing(self):
        stored = [list(v) for v in self.book.get("Saeed").embeddings]
        added, dropped, considered, before, after = self.book.relearn("Saeed", [_vec(2.5)] * 4)
        self.assertEqual((added, dropped, considered), (0, 0, 4))
        self.assertEqual(before, after)
        self.assertEqual(SpeakerBook(Path(self._tmp.name)).get("Saeed").embeddings, stored)


if __name__ == "__main__":
    unittest.main()
