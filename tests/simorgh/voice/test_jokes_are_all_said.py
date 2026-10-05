"""Asked for five jokes, Sim says five jokes.

The creator, 2026-10-04: "I'm asking sim to say 5 jokes for kid, it reads
the first one and says the remaining are on screen ... it is a voice
assistant". The default spoken cap was three sentences."""

from __future__ import annotations

import unittest

from simorgh.voice.config import Config
from simorgh.voice.planner import narration_wanted


class JokesAreAllSaid(unittest.TestCase):
    def test_the_default_cap_is_a_wall_not_a_length(self):
        self.assertGreaterEqual(Config().max_spoken_sentences, 20)

    def test_asking_for_jokes_is_asking_to_be_told(self):
        for asked in ("say 5 jokes for kid", "tell the kids a joke", "give me three riddles",
                      "برای بچه‌ها پنج تا جوک بگو", "یه لطیفه بگو"):
            with self.subTest(asked=asked):
                self.assertTrue(narration_wanted(asked))
        self.assertFalse(narration_wanted("what is the weather"))


if __name__ == "__main__":
    unittest.main()
