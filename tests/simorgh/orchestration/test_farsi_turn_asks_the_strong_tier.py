"""A Farsi chat turn asks Cognition for the strong tier.

Live, 2026-09-27: the fast chat model (GLM-5.3-Flash) answered clear Farsi
with "it came through garbled", invented lines of Hafez, and promised a fix
it never started. English turns keep the fast model."""

import unittest
from types import SimpleNamespace as N

from simorgh.orchestration.config import Config
from simorgh.orchestration.session import SessionRunner


def _runner(on: bool):
    return N(_farsi_strong=on, _escalate_from_attempt=0)


def _chat(text: str, heard: str = ""):
    return N(profile=N(scaffold="chat"), user_text=text, heard_language=heard, attempt=0, steps=[])


class FarsiTurnAsksTheStrongTier(unittest.TestCase):
    def test_farsi_is_strong(self):
        got = SessionRunner._tier(_runner(True), _chat("Sim, خب درستش کن یه چیز بذار که فارسی بفهمه"))
        self.assertEqual(got.get("tier"), "farsi")

    def test_heard_as_farsi_is_strong_even_in_latin_letters(self):
        self.assertEqual(SessionRunner._tier(_runner(True), _chat("Sim, ha'aretz huvesi", "persian")).get("tier"), "farsi")

    def test_english_keeps_the_fast_model(self):
        self.assertEqual(SessionRunner._tier(_runner(True), _chat("Sim, turn on the kitchen light")), {})

    def test_off_by_setting(self):
        self.assertEqual(SessionRunner._tier(_runner(False), _chat("سلام سیم")), {})

    def test_on_by_default(self):
        self.assertTrue(Config().farsi_strong)


if __name__ == "__main__":
    unittest.main()
