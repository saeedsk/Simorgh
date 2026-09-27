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



class ThePronunciationIsInThePrompt(unittest.TestCase):
    """Asked "how do you pronounce my name?", the model answered "Sah-eed,
    'Sah' then 'eed'" three times, after the prompt told it not to --
    while the voice said the name as set (live, 2026-09-27)."""

    def test_the_setting_is_told(self):
        text = who_is_here("Saeed", "", "", say_as="sa'eed")
        self.assertIn('Your voice says Saeed\'s name as "sa\'eed"', text)
        self.assertIn("voice pronounce Saeed", text)

    def test_nothing_is_claimed_without_one_or_for_an_unsure_voice(self):
        self.assertNotIn("Your voice says", who_is_here("Saeed", "", ""))
        self.assertNotIn("Your voice says", who_is_here("Saeed", "", "", doubt="close to Iris", say_as="x"))

    def test_the_field_travels_from_the_voice_to_the_prompt(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "simorgh"
        self.assertIn('"speaker_say_as"', (root / "orchestration" / "service.py").read_text())
        self.assertIn('O("speaker_say_as", Str)', (root / "contracts" / "messages" / "percept.py").read_text())
        self.assertIn("speaker_say_as=say_as", (root / "voice" / "session.py").read_text())
        self.assertIn('payload["speaker_say_as"]', (root / "voice" / "pipeline.py").read_text())
        self.assertIn("speaker_say_as=speaker_say_as", (root / "orchestration" / "worker.py").read_text())
        self.assertIn('speaker_say_as=getattr(session, "speaker_say_as", "")',
                      (root / "orchestration" / "session.py").read_text())
