"""`voice voices = af_bella` and `voice tts_voice af_bella` pick a voice, and
`voice voices` says how (the creator, 2026-09-19)."""

import asyncio
import unittest
from unittest import mock

from simorgh.interface import dispatch, voiceview


class VoiceShortcuts(unittest.TestCase):
    def _sent(self, args):
        seen = {}

        async def fake(bus, topic, payload, **kw):
            seen.update(payload)
            return None

        with mock.patch.object(dispatch, "_request", fake):
            asyncio.run(dispatch._voice(None, args))
        return seen

    def test_the_ways_people_try_it_all_set_the_voice(self):
        for args in ("voices = af_bella", "tts_voice af_bella", "tts_voice = af_bella", "set tts_voice af_bella"):
            with self.subTest(args=args):
                self.assertEqual(self._sent(args), {"action": "set", "key": "tts_voice", "value": "af_bella"})

    def test_a_bare_setting_asks_for_its_value(self):
        self.assertEqual(self._sent("tts_voice"), {"action": "set", "key": "tts_voice", "value": ""})

    def test_the_list_says_the_command_and_the_current_voice(self):
        text = voiceview.voices({"engine": "styletts2", "voices": ["default", "af_bella"], "current": "af_bella"})
        self.assertIn("voice set tts_voice <name>", text)
        self.assertIn("now: af_bella", text)


class PronounceIsACommand(unittest.TestCase):
    """The creator typed `pronounce IRa as EYE-ra` twice and the model only
    said "EYE-ra." back (2026-09-19)."""

    def test_the_short_forms_are_the_command(self):
        from simorgh.interface.parser import parse

        self.assertEqual(parse("pronounce IRa as EYE-ra").name, "pronounce")
        self.assertEqual(parse("pronounce Ira Eye-raa").name, "pronounce")
        self.assertIsNone(parse("pronounce it slowly for me please").name)

    def test_as_is_dropped(self):
        seen = VoiceShortcuts._sent(self, "pronounce Ira as Eye-raa")
        self.assertEqual(seen, {"action": "pronounce", "name": "Ira", "value": "Eye-raa"})


if __name__ == "__main__":
    unittest.main()


class BenchmarkStart(unittest.TestCase):
    """The creator, 2026-09-19: "/benchmark start" starts testing GAIA level 1."""

    def test_start_fills_in_the_defaults(self):
        from simorgh.interface.benchmarkview import parse_run, with_defaults

        self.assertEqual(parse_run(with_defaults(""))[0], {"suite": "gaia-l1", "limit": 5})
        self.assertEqual(parse_run(with_defaults("10"))[0], {"suite": "gaia-l1", "limit": 10})
        self.assertEqual(parse_run(with_defaults("bfcl"))[0], {"suite": "bfcl", "limit": 5})

    def test_start_sends_a_run(self):
        seen = {}

        async def fake(bus, topic, payload, **kw):
            seen.update(payload)

        with mock.patch.object(dispatch, "_request", fake):
            asyncio.run(dispatch._benchmark(None, "start"))
        self.assertEqual(seen, {"suite": "gaia-l1", "limit": 5})
