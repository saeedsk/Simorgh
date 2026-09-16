""""Iris said watch them ... you recognised that as my voice, that was a
bad recognition" (the creator, 2026-09-15).

Diarization already split the turn; the session then filed the whole thing
under the last voice and taught that person's profile from audio holding
both of them."""

from __future__ import annotations

import types
import unittest

from simorgh.voice.api import VoiceTurn
from simorgh.voice.session import may_refine


class WhoMayTeach(unittest.TestCase):
    def test_a_turn_two_people_shared_teaches_nobody(self):
        self.assertFalse(may_refine(segments=[{"speaker": "Saeed"}, {"speaker": "Iris"}], probable=False,
                                    refine_on=True, seconds=3.0, min_seconds=0.8, has_vector=True))

    def test_one_voice_confidently_placed_still_teaches(self):
        self.assertTrue(may_refine(segments=[], probable=False, refine_on=True,
                                   seconds=3.0, min_seconds=0.8, has_vector=True))

    def test_a_guess_short_speech_or_no_vector_teaches_nothing(self):
        common = dict(segments=[], refine_on=True, seconds=3.0, min_seconds=0.8, has_vector=True)
        self.assertFalse(may_refine(**{**common, "probable": True}))
        self.assertFalse(may_refine(**{**common, "probable": False, "seconds": 0.5}))
        self.assertFalse(may_refine(**{**common, "probable": False, "has_vector": False}))
        self.assertFalse(may_refine(**{**common, "probable": False, "refine_on": False}))


class TheRecordKeepsBothVoices(unittest.IsolatedAsyncioTestCase):
    class _Ledger:
        def __init__(self) -> None:
            self.events: list = []

        async def append(self, stream, event, **kw):
            self.events.append(event)
            return 1

    async def test_segments_reach_the_ledger(self):
        from simorgh.voice.pipeline import Pipeline

        pipeline = Pipeline.__new__(Pipeline)
        pipeline._config = types.SimpleNamespace(keep_transcripts=True)      # noqa: SLF001
        pipeline._ledger = self._Ledger()                                    # noqa: SLF001
        pipeline._logger = None                                              # noqa: SLF001
        turn = VoiceTurn(
            session_id="turn-1", device="laptop", speaker="Saeed", heard="watch them to surprise them",
            confidence=0.9, said="", heard_at=1.0, answered_at=2.0, engine_stt="fake", engine_tts="fake",
            segments=[{"speaker": "Iris", "text": "watch them"}, {"speaker": "Saeed", "text": "to surprise them"}],
        )
        await pipeline._record(turn)                                         # noqa: SLF001
        payload = pipeline._ledger.events[0].payload                         # noqa: SLF001
        self.assertEqual([s["speaker"] for s in payload["segments"]], ["Iris", "Saeed"])
        self.assertEqual(payload["speaker"], "Saeed", "the one Sim answered is still named")

    async def test_a_single_voice_turn_carries_no_segments(self):
        from simorgh.voice.pipeline import Pipeline

        pipeline = Pipeline.__new__(Pipeline)
        pipeline._config = types.SimpleNamespace(keep_transcripts=True)      # noqa: SLF001
        pipeline._ledger = self._Ledger()                                    # noqa: SLF001
        pipeline._logger = None                                              # noqa: SLF001
        await pipeline._record(VoiceTurn(                                    # noqa: SLF001
            session_id="turn-2", device="laptop", speaker="Saeed", heard="hello", confidence=0.9, said="hi",
            heard_at=1.0, answered_at=2.0, engine_stt="fake", engine_tts="fake"))
        self.assertNotIn("segments", pipeline._ledger.events[0].payload)     # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
