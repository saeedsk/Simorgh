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
    _restart_jammed = sat.SatelliteLink._restart_jammed
    _expect_run = sat.SatelliteLink._expect_run
    _on_board_log = sat.SatelliteLink._on_board_log

    def __init__(self):
        self.now = 100.0
        self._unjammed_at = -1e9
        self._restarted_at = -1e9
        self._restart_key = 7
        self._wake_heard_at = -1e9
        self._run_started_at = -1e9
        self.pressed = []
        self._client = SimpleNamespace(button_command=self.pressed.append)
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


class ABoardThatRefusesStopIsRestarted(unittest.TestCase):
    """Live 2026-09-27: after the STOP, the board said "Queue full, command
    dropped" and stayed jammed until it was unplugged. Its firmware has a
    Restart button (hidden in HA's UI, there on the API)."""

    def test_command_dropped_presses_restart_once_per_window(self):
        link = _Link()
        line = SimpleNamespace(message=b"[E][speaker_source_media_player:749]: Queue full, command dropped")
        link._on_board_log(line)
        link._on_board_log(line)
        self.assertEqual(link.pressed, [7])
        self.assertIn("voice.satellite_restarted", link.logged)
        link.now += sat.RESTART_JAMMED_EVERY_S + 1
        link._on_board_log(line)
        self.assertEqual(link.pressed, [7, 7])

    def test_no_button_no_press(self):
        link = _Link()
        link._restart_key = None
        link._on_board_log(SimpleNamespace(message=b"Queue full, command dropped"))
        self.assertEqual(link.pressed, [])


class ABoardThatHearsItsWakeWordAndOpensNoRunIsRestarted(unittest.IsolatedAsyncioTestCase):
    """Live 2026-09-27: after an aborted run the board heard "Hey Sim" and
    never opened another -- fourteen minutes deaf until unplugged."""

    WAKE = SimpleNamespace(message=b"[W][api:436]: Home Assistant event 'esphome.wake_word_detected' dropped")

    async def test_no_run_in_time_restarts(self):
        from unittest import mock

        link = _Link()
        with mock.patch.object(sat, "RUN_EXPECTED_S", 0.05):
            link._on_board_log(self.WAKE)
            await asyncio.sleep(0.12)
        self.assertEqual(link.pressed, [7])

    async def test_a_run_that_starts_is_left_alone(self):
        from unittest import mock

        link = _Link()
        with mock.patch.object(sat, "RUN_EXPECTED_S", 0.05):
            link._on_board_log(self.WAKE)
            link._run_started_at = link.now + 0.001       # the run opened
            await asyncio.sleep(0.12)
        self.assertEqual(link.pressed, [])


class ABoardWhoseMicSendsOnlyZerosIsRestarted(unittest.TestCase):
    """Live 2026-09-27: a run of 39 s at peak 0, right after a firmware
    warning; the board then heard nothing at all."""

    def _run(self, peak, seconds):
        return SimpleNamespace(logged=False, vad_ended_at=0, replied=False, follow_up=True,
                               audio_bytes=int(seconds * 32000), first_audio_at=0, started_at=0, peak=peak,
                               states=[], pcm=None)

    def test_pure_silence_restarts(self):
        link = _Link()
        sat.SatelliteLink._log_run(link, self._run(0, 39), "run end")
        self.assertEqual(link.pressed, [7])

    def test_a_quiet_room_does_not(self):
        link = _Link()
        sat.SatelliteLink._log_run(link, self._run(12, 39), "run end")
        sat.SatelliteLink._log_run(link, self._run(0, 1), "run end")
        self.assertEqual(link.pressed, [])


class TheLeadInToneLevel(unittest.TestCase):
    """2026-09-29: the Echo Dot plays the 20 Hz lead-in as a hum the creator
    can hear; its level is a setting."""

    def test_the_level_sets_the_peak(self):
        import array

        quiet = array.array("h", sat._wake_noise(16000, 16000, 300))
        loud = array.array("h", sat._wake_noise(16000, 16000, 900))
        self.assertLessEqual(max(abs(v) for v in quiet), 300)
        self.assertGreater(max(abs(v) for v in loud), 800)

    def test_it_is_a_safe_setting(self):
        from simorgh.contracts.settings import VOICE_SAFE_KEYS
        from simorgh.voice.config import Config

        self.assertIn("satellite_lead_in_level", VOICE_SAFE_KEYS)
        self.assertEqual(Config().satellite_lead_in_level, 900)


class OnlyAHouseLanguageIsSaid(unittest.TestCase):
    def test_icelandic_is_not_passed_on(self):
        fake = SimpleNamespace(_config=SimpleNamespace(stt_languages="en,fa"))
        self.assertEqual(VoiceSession._house_language(fake, "is"), "")
        self.assertEqual(VoiceSession._house_language(fake, "icelandic"), "")
        self.assertEqual(VoiceSession._house_language(fake, "english"), "english")
        self.assertEqual(VoiceSession._house_language(fake, "fa"), "fa")


if __name__ == "__main__":
    unittest.main()
