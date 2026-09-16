"""An unplaceable voice is never "mid-conversation" (voice/session.py).

The creator's work call, 2026-09-16: Sim answered one fragment it could
not attribute, then answered his colleagues for the next forty minutes --
introducing itself to the meeting, naming his wife and children, and
describing the house cameras.

`_in_conversation` read `_talking_with[speaker or "someone"]`, and
`_speak_reply` wrote the same key. So answering ONE unplaceable voice
claimed a live conversation with EVERY unplaceable voice for
`conversation_window_s` (180s), and every quiet rule bails the moment
that returns True -- `_continuation` on its first line, `_unplaced` at
its fourth. One mistake turned the guards off for the whole meeting, and
each answer renewed the window.
"""

from __future__ import annotations

import types
import unittest

from simorgh.voice.config import Config
from simorgh.voice.session import VoiceSession


def _session(now: float = 1_000.0, **settings) -> VoiceSession:
    """Only the two fields these rules touch; no audio stack needed."""
    session = object.__new__(VoiceSession)
    session._config = Config(**settings)
    session._talking_with = {}
    session._now = lambda: now
    return session


class AnonymityIsNotAPerson(unittest.TestCase):
    def test_an_unplaced_voice_is_never_mid_conversation(self):
        session = _session()
        session._talking_with["someone"] = 1_000.0   # what the old code wrote
        self.assertFalse(session._in_conversation(""), "no name, no conversation")

    def test_answering_one_stranger_does_not_enrol_the_next(self):
        """The meeting cascade, in two lines."""
        session = _session()
        session._talking_with[""] = 1_000.0          # if an empty key ever got written
        session._talking_with["someone"] = 1_000.0
        self.assertFalse(session._in_conversation(""))

    def test_a_named_person_still_holds_the_conversation(self):
        session = _session()
        session._talking_with["Saeed"] = 1_000.0
        self.assertTrue(session._in_conversation("Saeed"), "a real exchange must survive")

    def test_it_lapses_after_the_window(self):
        session = _session(now=1_000.0 + 181.0, conversation_window_s=180.0)
        session._talking_with["Saeed"] = 1_000.0
        self.assertFalse(session._in_conversation("Saeed"))

    def test_one_persons_conversation_is_not_anothers(self):
        session = _session()
        session._talking_with["Saeed"] = 1_000.0
        self.assertFalse(session._in_conversation("Soodeh"))
        self.assertFalse(session._in_conversation(""))

    def test_the_window_can_be_switched_off(self):
        session = _session(conversation_window_s=0.0)
        session._talking_with["Saeed"] = 1_000.0
        self.assertFalse(session._in_conversation("Saeed"))


class TheWriteSideAgrees(unittest.TestCase):
    def test_the_source_no_longer_keys_on_someone(self):
        """Both halves had the same fallback; fixing one alone would
        leave the other writing a key nothing reads, or reading a key
        nothing writes."""
        from pathlib import Path

        source = Path("simorgh/voice/session.py").read_text()
        self.assertNotIn('_talking_with[speaker or "someone"]', source)
        self.assertNotIn('_talking_with.get(speaker or "someone")', source)


if __name__ == "__main__":
    unittest.main()
