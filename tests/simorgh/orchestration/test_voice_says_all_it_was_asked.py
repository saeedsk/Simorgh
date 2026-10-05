"""The VOICE prompt: what a person asked to hear is said whole (2026-10-04)."""

import unittest

from simorgh.orchestration import scaffolds


class VoiceSaysAllItWasAsked(unittest.TestCase):
    def test_five_jokes_are_five_jokes(self):
        prompt = " ".join(scaffolds.VOICE.split())
        self.assertIn("all five jokes", prompt)
        self.assertIn("Never say the rest is on the screen", prompt)


if __name__ == "__main__":
    unittest.main()
