"""A Farsi sentence whisper calls Icelandic is asked again, not deleted.

Measured on the creator's own calibration set, through the real
listening path (2026-09-23): 2 of 16 Farsi takes produced no transcript
at all, every run. The turn opened, the audio was captured, and whisper
came back sure it was ARMENIAN for one and ICELANDIC for the other --
gibberish written in those scripts -- so the "not a language of this
house" filter deleted the utterance. Handed the same bytes with `fa`
named, whisper returns "توبین ها رو نشون بده", which is the sentence.

So the guess is not evidence and must not be the last word. What is
evidence is a reading in a different script: the same audio as Persian
letters rather than Latin ones is a different answer, not the same
mistake relabelled.
"""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass

from simorgh.voice.session import ask_again


@dataclass
class FakeUtterance:
    text: str
    language: str = ""


class FakeRecogniser:
    """Answers per language hint, and remembers what it was asked."""

    def __init__(self, answers: dict[str, str]):
        self.answers = answers
        self.asked: list[str] = []

    async def transcribe(self, audio, *, language: str = ""):
        self.asked.append(language)
        # Whisper keeps reporting its own (wrong) guess even when hinted.
        return FakeUtterance(self.answers.get(language, ""), language="icelandic")


def _again(rec, *, heard: str, languages=("en", "fa"), audio: bytes = b"\x00\x01" * 800) -> str:
    return asyncio.run(ask_again(rec, audio, heard=heard, languages=languages))


class AskingAgain(unittest.TestCase):
    def test_the_farsi_sentence_comes_back(self):
        """The measured case: Latin gibberish discarded, Persian letters
        returned."""
        rec = FakeRecogniser({"fa": "دوربین‌ها رو نشون بده", "en": "The turbine is going to be a little bit."})
        self.assertEqual(_again(rec, heard="Túrbín harú nesun bedir."), "دوربین‌ها رو نشون بده")

    def test_the_english_hint_is_not_even_tried_on_latin_gibberish(self):
        """An `en` retry returns Latin letters either way, so it cannot
        tell a rescued sentence from whisper dressing up noise. Asking
        costs a transcription and buys no evidence."""
        rec = FakeRecogniser({"fa": "دوربین‌ها رو نشون بده", "en": "The turbine is going."})
        _again(rec, heard="Túrbín harú nesun bedir.")
        self.assertEqual(rec.asked, ["fa"])

    def test_armenian_gibberish_is_rescued_too(self):
        """The other lost take. Armenian is neither house script, so
        both hints are fair to try; the Persian one answers."""
        rec = FakeRecogniser({"en": "", "fa": "چارت‌ها رو بذار روی تلویزیون"})
        self.assertEqual(_again(rec, heard="Թյ՞ մ՞մ մի՞մ եղմ"), "چارت‌ها رو بذار روی تلویزیون")

    def test_noise_stays_discarded(self):
        """The filter exists because whisper invents sentences out of
        near-silence. Hinted Farsi, noise comes back as noise -- or as
        nothing -- and nothing is returned to act on."""
        rec = FakeRecogniser({"fa": "", "en": ""})
        self.assertEqual(_again(rec, heard="Túrbín harú nesun bedir."), "")

    def test_an_answer_in_the_wrong_script_is_refused(self):
        """Hinted `fa` and answering in Latin letters is whisper
        ignoring the hint, which is exactly the reading being thrown
        away."""
        rec = FakeRecogniser({"fa": "Turbine is a little bit"})
        self.assertEqual(_again(rec, heard="Túrbín harú nesun bedir."), "")

    def test_a_recogniser_that_cannot_be_asked_changes_nothing(self):
        class Streaming:  # no `transcribe`
            pass

        self.assertEqual(_again(Streaming(), heard="Túrbín"), "")

    def test_no_audio_means_no_second_opinion(self):
        rec = FakeRecogniser({"fa": "دوربین‌ها"})
        self.assertEqual(_again(rec, heard="Túrbín", audio=b""), "")
        self.assertEqual(rec.asked, [])

    def test_a_failing_second_opinion_leaves_the_first_standing(self):
        class Broken:
            async def transcribe(self, audio, *, language: str = ""):
                raise RuntimeError("the server went away")

        self.assertEqual(_again(Broken(), heard="Túrbín"), "")


if __name__ == "__main__":
    unittest.main()
