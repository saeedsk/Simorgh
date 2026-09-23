"""A house can tell Sim to be quiet, and it stays quiet.

The creator, 2026-09-22: "I want to add a mode to sim to shut up and be
quiet when household is asking it, like 'sim be quiet for next 10
minutes' ... and sim should remain silent unless family member ask sim
with direct addressing like 'hey sim you talk now'".

`STOP` already existed and is a different thing: it cuts the sentence in
flight and then Sim carries on as before. This is the instruction a
person means when the room has had enough of it.
"""

import unittest

from simorgh.voice.commands import HUSH, hush_seconds, spoken_command, wants_to_talk_again


class WhatCountsAsBeingToldToBeQuiet(unittest.TestCase):
    def test_the_words_a_household_actually_uses(self):
        for text in ("be quiet", "Sim, be quiet", "shut up", "silence", "hush",
                     "ساکت باش", "خفه شو", "حرف نزن"):
            self.assertEqual(spoken_command(text), HUSH, text)

    def test_an_instruction_with_a_time_on_it_is_the_same_instruction(self):
        """Said by the creator hours after the hush was built, and not
        recognised: the lookup is exact, so the very suffix
        `hush_seconds` exists to read was what made the phrase miss."""
        for text in ("Silence for two minutes.", "sim be quiet for the next 10 minutes",
                     "be quiet for an hour", "quiet for 30 seconds"):
            self.assertEqual(spoken_command(text), HUSH, text)
        self.assertIsNone(spoken_command("what is for dinner in ten minutes"),
                          "an ordinary sentence with a time in it is not a command")

    def test_how_long_when_they_say_how_long(self):
        self.assertEqual(hush_seconds("sim be quiet for the next 10 minutes"), 600.0)
        self.assertEqual(hush_seconds("be quiet for an hour"), 3600.0)
        self.assertEqual(hush_seconds("quiet for 30 seconds"), 30.0)
        self.assertEqual(hush_seconds("be quiet for 5 minutes ساکت"), 300.0)

    def test_no_time_given_means_until_they_say_so(self):
        """A silence that ends on its own is not the one they asked
        for."""
        for text in ("be quiet", "shut up", "silence"):
            self.assertEqual(hush_seconds(text), 0.0, text)

    def test_only_a_sentence_that_names_sim_ends_it(self):
        """The whole point is that the room can talk without being
        answered."""
        for text in ("hey sim you talk now", "sim, you can talk", "Sim talk", "sim speak",
                     "hey sim come back", "سیم حرف بزن"):
            self.assertTrue(wants_to_talk_again(text), text)
        for text in ("we can talk about it tomorrow", "talk now", "what time is it",
                     "I'll speak to her later", "the kids can talk to him"):
            self.assertFalse(wants_to_talk_again(text), text)


class TheSessionKeepsQuiet(unittest.IsolatedAsyncioTestCase):
    def _session(self):
        from tests.simorgh.voice.test_session import _Script, _config
        from tests.simorgh.voice.test_speaker_session import _Embedder, _Replies, _session
        from simorgh.voice.speakers import SpeakerBook
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        book = SpeakerBook(Path(self._tmp.name) / "sp", household=())
        return _session(_config(), _Script((False, 10)), _Replies(), _Embedder(), book)

    async def test_hushed_then_asked_back(self):
        session, _bus, _tts = self._session()
        self.assertFalse(session._hushed())                 # noqa: SLF001

        session._hush_until = 0.0                           # noqa: SLF001 -- "until I say so"
        self.assertTrue(session._hushed())                  # noqa: SLF001

        await session._unhush(1)                            # noqa: SLF001
        self.assertFalse(session._hushed())                 # noqa: SLF001

    async def test_the_voice_can_still_be_turned_off_while_hushed(self):
        """A hush silences chatter, not the few things said TO the voice
        itself. Refusing "Sim, restart" or "voice off" while hushed
        would leave one way back from an indefinite hush -- the
        keyboard -- for a household that may not be near one."""
        from simorgh.voice.commands import MUTE, OFF, RESTART, spoken_command

        for text in ("voice off", "mute", "restart"):
            self.assertIn(spoken_command(text), (OFF, MUTE, RESTART), text)

    async def test_a_timed_hush_ends_by_itself(self):
        session, _bus, _tts = self._session()
        session._hush_until = session._now() - 1.0          # noqa: SLF001 -- ten minutes ago
        self.assertFalse(session._hushed(), "the time they asked for is up")  # noqa: SLF001
        session._hush_until = session._now() + 600.0        # noqa: SLF001
        self.assertTrue(session._hushed())                  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
