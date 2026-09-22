"""Learning must not take a profile apart.

The creator re-enrolled Ira, Iris and himself on 2026-09-21. Hours
later, measured off his own book:

    Ira     3 takes   coherence 0.92
    Iris    3 takes   coherence 0.83
    Saeed  12 takes   coherence 0.59   <-- back where it started

His three enrolment takes agree at 0.80. The nine learnt on top of
them agree at 0.51 to 0.76 -- every one over the `REFINE_AGREE` bar
of 0.5 -- and together they drag him to 0.59.

`REFINE_AGREE` compares a take to the profile AS IT IS, so as the
profile widens a worse take clears the same bar, which widens it
further. That is the ratchet its own comment warns about, and the
flat bar cannot stop it. A take must also leave the profile agreeing
with itself.

The opposite mistake is on record too (2026-09-15): the bar sat above
what his voice scored in his room, so the voice that most needed the
practice never gave any. Hence the guard only applies once there are
enough takes for "agrees with itself" to mean anything.
"""

import math
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.speakers import MUDDLED_BELOW, SpeakerBook, coherence


def _vec(angle: float, dim: int = 8) -> list[float]:
    v = [0.0] * dim
    v[0], v[1] = math.cos(angle), math.sin(angle)
    return v


class _Book(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = SpeakerBook(Path(self._tmp.name), threshold=0.5, margin=0.06)

    def _tight_profile(self, name="Saeed"):
        """Three takes of one voice, as an enrolment gives."""
        for angle in (0.0, 0.05, 0.10):
            self.book.enroll(name, _vec(angle))
        return self.book.get(name)


class TheGuard(_Book):
    def test_takes_that_disagree_with_EACH_OTHER_are_refused(self):
        """The creator's actual shape, and the one `REFINE_AGREE`
        cannot see: each take agrees with the profile about 0.57 --
        comfortably over the 0.5 bar -- and they are scattered, so
        together they pull it apart. Two takes on opposite sides.
        """
        self._tight_profile()
        self.assertTrue(self.book.refine("Saeed", _vec(0.96)), "the first passes on its own")
        after_one = coherence(self.book.get("Saeed").embeddings)
        self.assertFalse(self.book.refine("Saeed", _vec(-0.96)),
                         "the opposite side of the same spread is what wrecks it")
        self.assertEqual(coherence(self.book.get("Saeed").embeddings), after_one,
                         "and the profile is left as it was")

    def test_a_take_that_keeps_it_together_is_still_learnt(self):
        """The 2026-09-15 requirement: Sim must keep learning from the
        turns it actually gets. 0.7 rad is new enough to teach (under
        the novelty bar) and close enough to belong."""
        self._tight_profile()
        before = len(self.book.get("Saeed").embeddings)
        self.assertTrue(self.book.refine("Saeed", _vec(0.7)))
        self.assertEqual(len(self.book.get("Saeed").embeddings), before + 1)

    def test_a_thin_profile_is_left_to_the_old_bar(self):
        """With one enrolment take, coherence is a single pair and the
        guard would become "never learn below 0.65" -- which is the
        2026-09-15 bug the other way round."""
        self.book.enroll("Solo", _vec(0.0))
        self.assertTrue(self.book.refine("Solo", _vec(0.95)))

    def test_a_muddled_profile_can_still_improve(self):
        """Refusing everything once a profile is damaged would leave
        it damaged for good."""
        for angle in (0.0, 1.1, 2.2):
            self.book.enroll("Mixed", _vec(angle))
        person = self.book.get("Mixed")
        self.assertLess(coherence(person.embeddings), MUDDLED_BELOW)
        before = coherence(person.embeddings)
        self.book.refine("Mixed", _vec(0.05))
        self.assertGreaterEqual(coherence(self.book.get("Mixed").embeddings), before)


class Tidy(_Book):
    def test_it_drops_what_is_pulling_a_profile_apart(self):
        self._tight_profile()
        person = self.book.get("Saeed")
        # Written straight in, the way `refine` used to before the
        # guard existed -- which is how the creator's book got here.
        person.embeddings.extend([_vec(1.6), _vec(-1.6), _vec(2.4)])
        self.book._save(person)
        dropped, before, after = self.book.tidy("Saeed")
        self.assertGreater(dropped, 0)
        self.assertGreater(after, before)

    def test_the_enrolment_takes_are_never_touched(self):
        """They are the ones a person actually sat down and gave."""
        self._tight_profile()
        person = self.book.get("Saeed")
        person.embeddings.extend([_vec(2.0)] * 4)
        self.book._save(person)
        self.book.tidy("Saeed")
        self.assertGreaterEqual(len(self.book.get("Saeed").embeddings), 3)

    def test_a_healthy_profile_is_left_alone_and_says_so(self):
        self._tight_profile("Ira")
        dropped, before, after = self.book.tidy("Ira")
        self.assertEqual(dropped, 0)
        self.assertEqual(before, after, "0.92 -> 0.00 would read as having destroyed it")

    def test_it_is_idempotent(self):
        self._tight_profile()
        person = self.book.get("Saeed")
        person.embeddings.extend([_vec(1.3), _vec(1.4)])
        self.book._save(person)
        self.book.tidy("Saeed")
        self.assertEqual(self.book.tidy("Saeed")[0], 0)

    def test_an_unknown_name_is_not_a_crash(self):
        self.assertEqual(self.book.tidy("Nobody"), (0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
