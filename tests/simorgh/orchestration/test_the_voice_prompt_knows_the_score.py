"""Asked "what's my score now?", Sim said enrolment had never happened.

Live, 2026-09-21: the creator was enrolled and named by the speaker
book on every turn (0.36, 0.47 on the screen), and the reply said
"Still no number, Saeed -- the enrolment never happened", three turns
running. The voice prompt said "You know their voice" and nothing
else; the score never left Voice.
"""

import unittest

from simorgh.orchestration.scaffolds import who_is_here


class TheScoreIsInThePrompt(unittest.TestCase):
    def test_an_enrolled_speaker_is_said_to_be_enrolled_with_the_number(self):
        text = who_is_here("Saeed", "", "", score="0.47 against a bar of 0.30")
        self.assertIn("Saeed is enrolled", text)
        self.assertIn("0.47 against a bar of 0.30", text)

    def test_no_score_no_claim(self):
        self.assertNotIn("is enrolled", who_is_here("Saeed", "", ""))

    def test_the_field_travels_from_the_percept(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "simorgh"
        self.assertIn('"speaker_score"', (root / "orchestration" / "service.py").read_text())
        self.assertIn('O("speaker_score", Str)', (root / "contracts" / "messages" / "percept.py").read_text())
        self.assertIn("speaker_score=score", (root / "voice" / "session.py").read_text())


if __name__ == "__main__":
    unittest.main()
