"""Two engines behind one door (voice/tts/lanes.py): the request's lane
picks the engine, both share the voice list, the slow lane's pace is
known, warm-up touches both, and the session's rule sends spoken turns
down the quick lane."""

from __future__ import annotations

import unittest

from simorgh.voice.api import Audio, TtsRequest
from simorgh.voice.config import Config
from simorgh.voice.fakes import FakeSynthesiser
from simorgh.voice.tts.lanes import LaneSynthesiser
from simorgh.voice.tts.streaming import StreamingSynthesiser


class _Slow(FakeSynthesiser):
    name = "slowbox"
    nominal_pace = 2.5

    def __init__(self):
        super().__init__()
        self.last_took_s = 0.0
        self.last_seconds = 0.0
        self.closed = False

    def voices(self):
        return ["default", "af_jessica", "grandma"]

    async def synthesise(self, text, *, voice="", speed=1.0, tone=""):
        self.spoken.append(text)
        self.tones.append(tone)
        return Audio(b"\x00\x10" * 4800, 24000)

    async def close(self):
        self.closed = True


class _Quick(FakeSynthesiser):
    name = "quick"


class LaneSynthesiserTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.quick, self.slow = _Quick(), _Slow()
        self.lanes = LaneSynthesiser(self.quick, self.slow, Config(tts_voice="af_jessica", expressive_warm_delay_s=0))

    async def test_the_lane_picks_the_engine_and_the_default_is_quick(self):
        await self.lanes.synthesise("Hi.", voice="af_jessica", tone="bright", lane="fast")
        await self.lanes.synthesise("A story.", voice="af_jessica", tone="calm", lane="expressive")
        await self.lanes.synthesise("Aside.", voice="af_jessica")
        self.assertEqual(self.quick.spoken, ["Hi.", "Aside."])
        self.assertEqual(self.slow.spoken, ["A story."])
        self.assertEqual(self.slow.tones, ["calm"], "the tone reaches the slow engine")
        self.assertEqual(self.lanes.last_engine, "quick")
        self.assertEqual(self.lanes.name, "quick+slowbox")

    def test_voices_are_the_union_and_the_pace_is_the_slow_lanes(self):
        self.assertEqual(self.lanes.voices()[:6], ["fake", "af_bella", "af_heart", "af_jessica", "af_kore", "bf_lily"])
        self.assertIn("grandma", self.lanes.voices())
        self.assertEqual(self.lanes.pace_ratio("fast"), 0.0)
        self.assertEqual(self.lanes.pace_ratio("expressive"), 2.5, "nominal until measured")
        self.slow.last_took_s, self.slow.last_seconds = 6.0, 3.0
        self.assertEqual(self.lanes.pace_ratio("expressive"), 2.0)

    async def test_warmup_speaks_through_both_in_the_configured_voice_and_close_closes_both(self):
        streaming = StreamingSynthesiser(self.lanes)
        seconds = await streaming.warmup()
        self.assertGreaterEqual(seconds, 0.0)
        self.assertEqual(self.quick.spoken, ["Okay."])
        await self.lanes.warm_expressive()
        self.assertEqual(self.slow.spoken, ["Okay."], "the slow lane warms behind the quick one")
        self.assertEqual(await streaming.warmup(), 0.0, "once")
        await streaming.close()
        self.assertTrue(self.slow.closed)

    async def test_the_streaming_wrapper_passes_the_lane_and_holds_for_a_slow_one(self):
        streaming = StreamingSynthesiser(self.lanes, lookahead=1)
        request = TtsRequest(request_id="r", pieces=(("One sentence here.", 0), ("Another one.", 0), ("Last.", 0)),
                             voice="af_jessica", lane="expressive")
        self.assertGreater(streaming.hold_seconds(request), 0.0)
        got = [c async for c in streaming.synthesise_stream(request)]
        self.assertEqual(len(got), 3)
        self.assertEqual(self.slow.spoken, ["One sentence here.", "Another one.", "Last."])
        self.assertEqual(self.quick.spoken, [])
        quick_request = TtsRequest(request_id="q", pieces=(("Hi.", 0),), lane="fast")
        self.assertEqual(streaming.hold_seconds(quick_request), 0.0, "the quick lane never waits")


class LaneRuleTestCase(unittest.TestCase):
    """`VoiceSession._lane_for`, the rule alone."""

    def _rule(self, **cfg):
        from simorgh.voice.session import VoiceSession

        class _S:
            _config = Config(**cfg)
        return lambda text, spoken: VoiceSession._lane_for(_S(), text, spoken_turn=spoken)

    def test_auto_is_quick_for_spoken_and_typed_turns_and_slow_only_for_a_long_answer(self):
        rule = self._rule()
        self.assertEqual(rule("Loud and clear.", True), "fast")
        self.assertEqual(rule("Loud and clear.", False), "fast", "the person is reading it already")
        self.assertEqual(rule("x" * 900, True), "fast", "a long spoken answer stays quick unless expressive_min_chars is set")
        self.assertEqual(self._rule(expressive_min_chars=400)("x" * 400, True), "expressive")

    def test_voice_test_asks_for_the_expressive_lane_on_purpose(self):
        from simorgh.voice.session import VoiceSession

        class _S:
            _config = Config()
        self.assertEqual(VoiceSession._lane_for(_S(), "Hi.", spoken_turn=False, explicit=True), "expressive")
        self.assertEqual(VoiceSession._lane_for(type("C", (), {"_config": Config(expressive_lane="off")})(), "Hi.",
                                                spoken_turn=False, explicit=True), "fast", "off means off")

    def test_always_and_off_override(self):
        self.assertEqual(self._rule(expressive_lane="always")("Hi.", True), "expressive")
        self.assertEqual(self._rule(expressive_lane="off")("x" * 900, False), "fast")
