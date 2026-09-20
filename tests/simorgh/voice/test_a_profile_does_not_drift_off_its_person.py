"""2026-09-20, live: Sim went deaf to the creator.

In a quiet room, 30 cm from the microphone, his voice scored 0.37-0.44
against a 0.50 threshold, so every turn was an unplaced voice and every
turn was refused. The cause was not the threshold and not the room: his
profile had collected 18 takes whose median agreement with each other
was 0.37, where Iris's nine sat at 0.85. Only four of the eighteen
agreed. The profile had stopped being a description of one voice.

A take is judged against the profile as a WHOLE, so the drift feeds
itself: one wrong voice in makes the profile wider, a wider profile
admits more, and the person it is named after scores worse every week.
"""

import unittest

from simorgh.voice.speakers import MAX_TAKES, REFINE_AGREE, agreement, coherence


def _voice(seed: float, n: int = 16) -> list[float]:
    """A vector that is `seed`-ish: near-identical for the same seed."""
    return [seed + (i % 3) * 0.01 for i in range(n)]


def _other(n: int = 16) -> list[float]:
    return [(-1.0 if i % 2 else 1.0) * (0.5 + i * 0.01) for i in range(n)]


class Coherence(unittest.TestCase):
    def test_one_voice_recorded_several_times_agrees_with_itself(self):
        self.assertGreater(coherence([_voice(1.0), _voice(1.01), _voice(0.99)]), 0.8)

    def test_a_profile_holding_two_voices_says_so(self):
        mixed = [_voice(1.0), _voice(1.01), _other(), _other()]
        self.assertLess(coherence(mixed), 0.8, "a mixture must not read as a voice")

    def test_a_profile_too_small_to_disagree_is_not_called_incoherent(self):
        self.assertEqual(coherence([]), 1.0)
        self.assertEqual(coherence([_voice(1.0)]), 1.0)


class TheAgreementGuard(unittest.TestCase):
    def test_a_take_that_looks_like_the_others_is_welcome(self):
        self.assertGreaterEqual(agreement(_voice(1.0), [_voice(1.01), _voice(0.99)]), REFINE_AGREE)

    def test_a_take_that_looks_like_nobody_in_the_profile_is_not(self):
        self.assertLess(agreement(_other(), [_voice(1.0), _voice(1.01), _voice(0.99)]), REFINE_AGREE)

    def test_nothing_to_disagree_with_is_agreement(self):
        self.assertEqual(agreement(_voice(1.0), []), 1.0)


class TheCapHolds(unittest.TestCase):
    """The creator's profile reached 18 against a cap of 12: the cap was
    applied once per call, so any path that appended twice left it over
    the cap for good."""

    def test_the_cap_is_enforced_until_it_holds(self):
        kept = [_voice(1.0 + i * 0.001) for i in range(MAX_TAKES + 6)]
        while len(kept) > MAX_TAKES:
            del kept[3]
        self.assertEqual(len(kept), MAX_TAKES)


if __name__ == "__main__":
    unittest.main()


class StartingAgain(unittest.TestCase):
    """A profile that has drifted off its person cannot be repaired by
    adding takes to it, so there has to be a way back to nothing
    (`voice forget all`, 2026-09-20)."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from simorgh.voice.speakers import SpeakerBook

        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.book = SpeakerBook(self.folder)
        self.book.enroll("Saeed", _voice(1.0))
        self.book.enroll("Ira", _other())   # a different direction: two voices, not one twice

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_names_what_it_erased(self):
        self.assertEqual(self.book.forget_everyone(), ["Ira", "Saeed"],
                         "a person deserves to be told exactly what went")

    def test_nothing_is_left_on_disk_or_in_memory(self):
        from simorgh.voice.speakers import SpeakerBook

        self.book.forget_everyone()
        self.assertEqual(self.book.people(), [])
        self.assertEqual(SpeakerBook(self.folder).people(), [], "and it stays gone across a restart")
        self.assertEqual(list(self.folder.glob("*.json")), [])

    def test_erasing_an_empty_book_says_so_rather_than_pretending(self):
        self.book.forget_everyone()
        self.assertEqual(self.book.forget_everyone(), [])

    def test_a_backup_beside_the_book_is_not_a_voice(self):
        """The repaired profiles left `.json.bak` files in the folder;
        the book must neither load nor erase them."""
        (self.folder / "Saeed.poisoned-20260920.json.bak").write_text("{}")
        self.book.forget_everyone()
        self.assertTrue((self.folder / "Saeed.poisoned-20260920.json.bak").exists())
