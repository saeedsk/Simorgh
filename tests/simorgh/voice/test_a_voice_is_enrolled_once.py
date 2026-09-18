"""The audio a take was made from is kept, so nobody enrols twice.

The creator, 2026-09-17: "my family memebers are tired of enrolling their
voice to sim multiple time, for future enrolling, record their voice and
keep them as sample in sim folder for future refences, retraining, etc".

An embedding is welded to the model that made it -- speakers.py says so:
"takes made with another model do not compare" -- so replacing the
embedder has meant asking five people to say sentences into a laptop
again. Audio does not expire that way.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.speakers import SPEAKER_MODEL, SpeakerBook


class TakesAreKept(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = SpeakerBook(folder=Path(self.tmp.name), household=())

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_audio_and_what_was_said_are_filed_together(self):
        pcm = b"\x01\x00" * 16000          # one second
        path = self.book.keep_take("Ira", pcm, text="a whole sentence", seconds=1.0)
        self.assertTrue(path, "a take that was accepted is filed")
        wav = Path(path)
        self.assertTrue(wav.is_file())
        self.assertEqual(wav.parent.name, "Ira", "filed under the person, not in a heap")
        side = json.loads(wav.with_suffix(".json").read_text())
        self.assertEqual(side["text"], "a whole sentence")
        self.assertEqual(side["name"], "Ira")
        self.assertEqual(side["source"], "enroll")
        self.assertEqual(side["model"], SPEAKER_MODEL,
                         "which embedder made it: without this a re-embed cannot tell them apart")

    def test_a_take_that_cannot_be_filed_is_not_a_failed_enrolment(self):
        book = SpeakerBook(folder=Path(self.tmp.name) / "nested" / "\0bad", household=())
        self.assertEqual(book.keep_take("Ira", b"\x01\x00" * 16000), "",
                         "the voice is still enrolled; only the recording is lost")

    def test_nothing_is_filed_for_no_name_or_no_audio(self):
        self.assertEqual(self.book.keep_take("", b"\x01\x00" * 100), "")
        self.assertEqual(self.book.keep_take("Ira", b""), "")
        self.assertEqual(list(Path(self.tmp.name).glob("*/*.wav")), [])

    def test_the_household_spelling_wins_so_one_person_is_one_folder(self):
        book = SpeakerBook(folder=Path(self.tmp.name), household=(type("P", (), {"name": "Saeed"})(),))
        book.keep_take("saeed", b"\x01\x00" * 16000)
        self.assertTrue((Path(self.tmp.name) / "Saeed").is_dir(),
                        "`voice enroll saeed` must not make a second folder")


class TheTurnsAudioSurvivesIdentification(unittest.TestCase):
    def test_identify_keeps_a_copy_for_the_enrolment_paths(self):
        # `_identify` pops the frames, and both enrolment paths run after it
        # and are handed only the embedding -- so the copy is the whole wire.
        import inspect

        from simorgh.voice.session import VoiceSession

        self.assertIn("_last_pcm = bytes(pcm)", inspect.getsource(VoiceSession._identify))
        for path in (VoiceSession._enroll_take, VoiceSession._introduce_step):
            self.assertIn("keep_take", inspect.getsource(path),
                          f"{path.__name__} files the take it just accepted")


if __name__ == "__main__":
    unittest.main()
