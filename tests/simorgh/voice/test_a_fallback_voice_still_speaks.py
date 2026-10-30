"""A TTS engine that falls back still speaks, so voice turns on.

Live 2026-10-30, a new Mac without StyleTTS2: `tts = "elevenlabs"` opened
fine over Kokoro, but `_pipeline_ready` counted "fell back to" as a
problem, so `voice.not_enabled` -- and every satellite room, which opens
the same engines, stayed silent too. The note belongs in `voice status`,
not in the reasons to stay off."""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from tests.simorgh.voice.test_session import _Bus


class _Ctx:
    bus = _Bus()
    clock = None
    ledger = None
    config = {}
    secrets = None

    class logger:
        @staticmethod
        def info(*a, **k): pass
        @staticmethod
        def warning(*a, **k): pass
        @staticmethod
        def error(*a, **k): pass
        @staticmethod
        def debug(*a, **k): pass


def _service():
    from simorgh.voice.config import Config
    from simorgh.voice.service import Service

    config = Config(stt="fake", tts="elevenlabs", microphone="fake", speaker="fake", speaker_id="off",
                    stt_partials=False, backchannel=False, enabled=False)
    service = Service(config, microphone=FakeMicrophone(silence(0.03)), speaker=FakeSpeaker(),
                      recogniser=FakeRecogniser())
    service._ctx = _Ctx()  # noqa: SLF001
    return service


class AFallbackVoiceStillSpeaks(unittest.IsolatedAsyncioTestCase):
    async def test_a_fallback_turns_voice_on_and_is_named_in_status(self):
        service = _service()
        why = "styletts2: needs its environment"
        with mock.patch("simorgh.voice.service.open_synthesiser", return_value=(FakeSynthesiser(), why)):
            ok, reason = await service._turn_on()  # noqa: SLF001
        try:
            self.assertTrue(ok, reason)
            self.assertTrue(any("fell back to" in p and why in p for p in service._problems))  # noqa: SLF001
        finally:
            await service._turn_off()  # noqa: SLF001

    async def test_no_engine_at_all_still_keeps_voice_off(self):
        service = _service()
        with mock.patch("simorgh.voice.service.open_synthesiser", return_value=(None, "no tts engine")):
            ok, reason = await service._turn_on()  # noqa: SLF001
        self.assertFalse(ok)
        self.assertIn("no tts engine", reason)


if __name__ == "__main__":
    unittest.main()
