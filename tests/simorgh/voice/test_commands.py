"""Spoken commands (voice/commands.py): "stop", "be quiet", "voice off"
are obeyed on the spot, never sent to the model; ordinary sentences
that contain those words are not commands."""

from __future__ import annotations

import unittest

from simorgh.voice.commands import MUTE, OFF, STOP, spoken_command


class TestSpokenCommand(unittest.TestCase):
    def test_stop_in_its_many_forms(self) -> None:
        for text in ("stop", "Stop.", "Sim, stop talking", "Stop it please.", "Be quiet!", "okay stop", "Shut up.",
                     "enough", "بس کن", "سیم ساکت شو", "Hey Sim, be quiet"):
            self.assertEqual(spoken_command(text), STOP, text)

    def test_off_and_mute(self) -> None:
        for text in ("Voice off.", "turn off the voice", "Sim, voice off", "صدا قطع"):
            self.assertEqual(spoken_command(text), OFF, text)
        for text in ("mute", "Stop listening."):
            self.assertEqual(spoken_command(text), MUTE, text)

    def test_ordinary_talk_is_not_a_command(self) -> None:
        for text in ("please stop the benchmark", "the bus stop is far", "Final answer three.", "",
                     "stop what you are doing and read this file", "is it quiet in there?"):
            self.assertIsNone(spoken_command(text), text)


if __name__ == "__main__":
    unittest.main()
