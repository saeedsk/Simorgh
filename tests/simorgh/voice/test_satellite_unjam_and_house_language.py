"""Two live finds, 2026-09-27.

The board's media player stopped taking audio ("Queue full, URI dropped")
and every reply after it was silent while Sim took it as played. And a
turn whisper labelled Icelandic was answered in Icelandic."""

import asyncio
import unittest
from types import SimpleNamespace

from simorgh.voice import satellite as sat
from simorgh.voice.session import VoiceSession


class _Link:
    name = "satellite"
    _unjam = sat.SatelliteLink._unjam
    _on_board_log = sat.SatelliteLink._on_board_log

    def __init__(self):
        self.now = 100.0
        self._unjammed_at = -1e9
        self.stops = 0
        self.logged = []

    def _clock(self):
        return self.now

    def _log(self, level, event, **fields):
        # As the real one: it adds `satellite=` itself, and a second one
        # raised inside the board's message handler (live, 2026-09-27).
        if "satellite" in fields:
            raise TypeError("got multiple values for keyword argument 'satellite'")
        self.logged.append(event)

    async def stop_playback(self):
        self.stops += 1


class AJammedBoardIsCleared(unittest.IsolatedAsyncioTestCase):
    async def test_queue_full_stops_the_player_once_per_window(self):
        link = _Link()
        line = SimpleNamespace(message=b"[E][speaker_source_media_player:717]: Queue full, URI dropped")
        link._on_board_log(line)
        link._on_board_log(line)
        await asyncio.sleep(0)
        self.assertEqual(link.stops, 1)
        self.assertIn("voice.satellite_unjammed", link.logged)
        link.now += sat.UNJAM_EVERY_S + 1
        link._on_board_log(line)
        await asyncio.sleep(0)
        self.assertEqual(link.stops, 2)


class OnlyAHouseLanguageIsSaid(unittest.TestCase):
    def test_icelandic_is_not_passed_on(self):
        fake = SimpleNamespace(_config=SimpleNamespace(stt_languages="en,fa"))
        self.assertEqual(VoiceSession._house_language(fake, "is"), "")
        self.assertEqual(VoiceSession._house_language(fake, "icelandic"), "")
        self.assertEqual(VoiceSession._house_language(fake, "english"), "english")
        self.assertEqual(VoiceSession._house_language(fake, "fa"), "fa")


if __name__ == "__main__":
    unittest.main()
