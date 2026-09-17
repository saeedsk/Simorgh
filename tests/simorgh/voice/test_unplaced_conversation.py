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


def _unplaced_session(now: float = 1_000.0, **settings):
    """A session with just enough around it to run `_unplaced`."""
    published: list = []

    async def _publish(_topic, payload):
        published.append(payload)

    async def _announce(_state):
        return None

    session = object.__new__(VoiceSession)
    session._config = Config(**settings)
    session._talking_with = {}
    session._quiet_on = {}
    session._room = []
    session._now = lambda: now
    session._log = lambda *a, **k: None
    session._announce = _announce
    session._sim_spoke_at = now - 2.0
    session._last_ask_addressed = False
    session.last_identification = None
    session._embedder = object()
    session._speakers = types.SimpleNamespace(has_voices=lambda: True, lean=0.45)
    session._pipeline = types.SimpleNamespace(_publish=_publish)
    session.turns = types.SimpleNamespace(state="listening")
    session.stats = types.SimpleNamespace(turns=0)
    session.published = published
    return session


def _ident(closest: str, score: float):
    from simorgh.voice.speakers import Identification

    return Identification(name="", score=score, runner_up=closest, runner_up_score=score)


class RecognitionFlickersTestCase(unittest.IsolatedAsyncioTestCase):
    """Closing the meeting cascade cost the creator silence mid-sentence
    ("radio silent", live 2026-09-16): his own voice dropped below the
    threshold for one turn and the unplaced rule refused to answer him.

    A voice whose closest match is the person Sim is mid-conversation
    with, scoring at least the book's `lean`, within `exchange_window_s`,
    is that person on a bad frame. All four conditions matter -- the
    second test here is the one that must never go green the wrong way.
    """

    async def test_the_person_sim_is_talking_to_is_still_answered(self):
        session = _unplaced_session()
        session._talking_with["Saeed"] = 1_000.0
        session.last_identification = _ident("Saeed", 0.46)
        self.assertFalse(await session._unplaced(1, "", "so what did you find"),
                         "a flicker mid-conversation is not a stranger")

    async def test_a_colleague_who_merely_resembles_him_is_not(self):
        """The work call. The closest match was still Saeed, but at a
        score nowhere near `lean` -- that is a different person."""
        session = _unplaced_session()
        session._talking_with["Saeed"] = 1_000.0
        session.last_identification = _ident("Saeed", 0.18)
        self.assertTrue(await session._unplaced(1, "", "and what was your last company"),
                        "a stranger who scores 0.18 is a stranger")

    async def test_no_live_conversation_means_no_exception(self):
        session = _unplaced_session()
        session.last_identification = _ident("Saeed", 0.46)   # nobody mid-conversation
        self.assertTrue(await session._unplaced(1, "", "try harder, honey"))

    async def test_the_exception_lasts_seconds_not_the_conversation_window(self):
        """`conversation_window_s` is 180s; this rides on the much
        shorter `exchange_window_s`, so it cannot cover a meeting."""
        session = _unplaced_session()
        session._sim_spoke_at = 1_000.0 - 60.0
        session._talking_with["Saeed"] = 1_000.0
        session.last_identification = _ident("Saeed", 0.46)
        self.assertTrue(await session._unplaced(1, "", "who did that"))

    async def test_it_can_be_switched_off(self):
        session = _unplaced_session(unplaced_follows_conversation=False)
        session._talking_with["Saeed"] = 1_000.0
        session.last_identification = _ident("Saeed", 0.46)
        self.assertTrue(await session._unplaced(1, "", "so what did you find"))

    async def test_a_named_voice_never_reaches_this_rule_at_all(self):
        session = _unplaced_session()
        self.assertFalse(await session._unplaced(1, "Saeed", "hello"),
                         "_unplaced is only about voices with no name")
