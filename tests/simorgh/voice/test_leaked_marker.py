"""A tool call written as prose is not a sentence (voice/planner.py).

The creator, live 2026-09-16, testing his cameras: Sim said "CAM_STATE
all" out loud, and a moment later "RING_LIST induction: true". Tool
syntax, through the speakers, as if it were an answer.

`cognition/parser.py::parse_marker` needs the colon --

    "CAM_STATE: all"     -> ("cam_state", "all")   a call
    "CAM_STATE all"      -> (None, "CAM_STATE all")  not a call
    "CAM_STATE\\n\\n\\nall" -> (None, ...)             not a call

-- so without it no call was ever made, and the raw text fell through to
the speaker. Nothing downstream could catch it: Voice never imports the
parser and cannot see the tool names at all. So the test is the SHAPE,
and the underscore is what makes the shape safe. NVDA, USA and OK are
words a listener may hear; CAM_STATE is not one of them.

Anchored at the head, because a marker is how a reply STARTS. An
acronym in the middle of a sentence is ordinary speech and stays.
"""

from __future__ import annotations

import unittest

from simorgh.voice.planner import speakable


class LeakedMarkerTestCase(unittest.TestCase):
    def test_the_two_that_were_said_out_loud(self):
        for said in ("CAM_STATE all", "RING_LIST\ninduction: true"):
            text, omitted = speakable(said)
            self.assertEqual(text, "", f"{said!r} reached the speaker")
            self.assertIn("marker", omitted)

    def test_the_newline_form_too(self):
        """Whisper-transcribed turns showed `CAM_STATE\\n\\n\\nall`; the
        argument on a later line is still the same failed call."""
        text, omitted = speakable("CAM_STATE\n\n\nall")
        self.assertEqual(text, "")
        self.assertIn("marker", omitted)

    def test_a_marker_that_kept_its_colon_is_not_spoken_either(self):
        """It should have been parsed upstream. If it arrives here
        anyway, saying it aloud is still the wrong answer."""
        text, _ = speakable("CAM_STATE: all")
        self.assertEqual(text, "")

    def test_an_acronym_is_still_spoken(self):
        """The rule this must not break: a ticker is a word."""
        for ordinary in ("NVDA is up two percent.", "OK, done.", "USA and UK both."):
            text, omitted = speakable(ordinary)
            self.assertTrue(text, f"{ordinary!r} was swallowed")
            self.assertNotIn("marker", omitted)

    def test_an_underscored_name_mid_sentence_is_still_spoken(self):
        """Anchored at the head on purpose."""
        text, omitted = speakable("The FRONT_DOOR camera saw nothing.")
        self.assertIn("FRONT_DOOR", text)
        self.assertNotIn("marker", omitted)

    def test_an_ordinary_reply_is_untouched(self):
        text, omitted = speakable("Yes, I'm here — go ahead.")
        self.assertEqual(text, "Yes, I'm here — go ahead.")
        self.assertEqual(omitted, ())

    def test_what_was_dropped_is_named(self):
        """`omitted` is the channel that already carries this to the turn
        record, so a silence has a reason attached rather than being a
        mystery."""
        _, omitted = speakable("MEMORY_FORGET 5")
        self.assertEqual(omitted, ("marker",))


if __name__ == "__main__":
    unittest.main()
