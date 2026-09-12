"""The turn manager (voice/turns.py), the frame VAD and the incremental
recogniser: state transitions from events alone, hybrid end of turn,
barge-in, monotonic turn and response ids, stale replies dropped."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.voice.api import Audio, PlaybackState, TranscriptEvent, Utterance, VadEvent
from simorgh.voice.fakes import FakeDetector, FakeRecogniser
from simorgh.voice.stt.streaming import IncrementalRecogniser
from simorgh.voice.turns import (AGENT_SPEAKING, Actions, IDLE, INTERRUPTED, LISTENING, Policy, THINKING,
                                 TurnManager, USER_SPEAKING)
from simorgh.voice.vad import FrameVad, threshold_for


def _speech(ms: int) -> VadEvent:
    return VadEvent("speech", speech_ms=ms)


def _silence(ms: int) -> VadEvent:
    return VadEvent("silence", silence_ms=ms)


def _kinds(actions) -> list[str]:
    return [a.kind for a in actions]


class TestChoppedSpeechIsStillATurn(unittest.TestCase):
    def test_short_runs_add_up_to_a_turn(self) -> None:
        # A quiet speaker's frames come through in 90 ms runs with gaps
        # between; 3 s of them is a sentence, not "too short" (2026-09-11).
        tm = TurnManager(Policy(end_of_turn_silence_ms=600, min_speech_ms=250, frame_ms=30))
        tm.start()
        self.assertEqual(_kinds(tm.handle_vad(VadEvent("speech_start", speech_ms=30))), [Actions.CAPTURE_START])
        for _ in range(12):  # twelve runs of three frames, none 250 ms long
            for ms in (30, 60, 90):
                tm.handle_vad(_speech(ms))
            tm.handle_vad(VadEvent("speech_end", speech_ms=90, silence_ms=30))
            tm.handle_vad(_silence(60))
        actions = tm.handle_vad(_silence(600))
        self.assertEqual(_kinds(actions), [Actions.FINALISE], "chopped speech adds up to a turn")

    def test_a_single_blip_is_still_too_short(self) -> None:
        tm = TurnManager(Policy(end_of_turn_silence_ms=600, min_speech_ms=250, frame_ms=30))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(60))
        actions = tm.handle_vad(_silence(600))
        self.assertEqual(_kinds(actions), [Actions.DISCARD])


class TestTurnManager(unittest.TestCase):
    def _speaking_manager(self) -> TurnManager:
        tm = TurnManager(Policy(end_of_turn_silence_ms=600, min_speech_ms=200, barge_in_speech_ms=300))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(600))
        tm.handle_vad(_silence(600))
        tm.handle_transcript(TranscriptEvent("final", "what time is it", tm.turn_id))
        tm.reply_ready(tm.turn_id)
        tm.handle_playback_state(PlaybackState("started", "r1"))
        return tm

    def test_a_whole_turn_walks_the_states(self) -> None:
        tm = TurnManager(Policy(end_of_turn_silence_ms=600, min_speech_ms=200))
        self.assertEqual(tm.state, IDLE)
        tm.start()
        self.assertEqual(tm.state, LISTENING)
        actions = tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        self.assertEqual(_kinds(actions), [Actions.CAPTURE_START])
        self.assertEqual(tm.state, USER_SPEAKING)
        self.assertEqual(tm.turn_id, 1)
        self.assertEqual(tm.handle_vad(_speech(500)), [])
        self.assertEqual(tm.handle_vad(_silence(300)), [])  # not yet
        actions = tm.handle_vad(_silence(600))
        self.assertEqual(_kinds(actions), [Actions.FINALISE])
        self.assertEqual(tm.handle_vad(_silence(900)), [])  # already finalising
        actions = tm.handle_transcript(TranscriptEvent("final", "hello there", 1))
        self.assertEqual(_kinds(actions), [Actions.ASK])
        self.assertEqual(actions[0].text, "hello there")
        self.assertEqual(tm.state, THINKING)
        actions = tm.reply_ready(1)
        self.assertEqual(_kinds(actions), [Actions.SPEAK])
        self.assertEqual(actions[0].response_id, 1)
        tm.handle_playback_state(PlaybackState("started", "r1"))
        self.assertEqual(tm.state, AGENT_SPEAKING)
        tm.handle_playback_state(PlaybackState("finished", "r1"))
        self.assertEqual(tm.state, LISTENING)

    def test_too_short_is_discarded_not_asked(self) -> None:
        tm = TurnManager(Policy(end_of_turn_silence_ms=600, min_speech_ms=250))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(90))
        actions = tm.handle_vad(_silence(600))
        self.assertEqual(_kinds(actions), [Actions.DISCARD])
        self.assertEqual(tm.state, LISTENING)

    def test_a_finished_sentence_shortens_the_wait(self) -> None:
        tm = TurnManager(Policy(end_of_turn_silence_ms=1000, min_speech_ms=200, semantic_silence_factor=0.5))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(800))
        tm.handle_transcript(TranscriptEvent("partial", "turn the lights off.", tm.turn_id))
        self.assertEqual(tm.handle_vad(_silence(400)), [])
        self.assertEqual(_kinds(tm.handle_vad(_silence(500))), [Actions.FINALISE])
        tm2 = TurnManager(Policy(end_of_turn_silence_ms=1000, min_speech_ms=200, semantic_silence_factor=0.5))
        tm2.start()
        tm2.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm2.handle_vad(_speech(800))
        tm2.handle_transcript(TranscriptEvent("partial", "turn the lights", tm2.turn_id))
        self.assertEqual(tm2.handle_vad(_silence(500)), [])  # mid-thought: the full wait

    def test_a_turn_is_forced_to_end_at_the_ceiling(self) -> None:
        tm = TurnManager(Policy(max_turn_ms=5000, min_speech_ms=200))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        self.assertEqual(tm.handle_vad(_speech(4000)), [])
        self.assertEqual(_kinds(tm.handle_vad(_speech(5010))), [Actions.FINALISE])

    def test_barge_in_stops_playback_cancels_tts_and_starts_a_new_turn(self) -> None:
        tm = self._speaking_manager()
        self.assertEqual(tm.state, AGENT_SPEAKING)
        self.assertEqual(tm.handle_vad(VadEvent("speech_start", speech_ms=30)), [])  # a blip is not a person
        actions = tm.handle_vad(_speech(330))
        self.assertEqual(_kinds(actions), [Actions.STOP_PLAYBACK, Actions.CANCEL_TTS, Actions.CAPTURE_START])
        self.assertEqual(actions[0].response_id, 1)
        self.assertEqual(tm.turn_id, 2)
        self.assertEqual(tm.state, USER_SPEAKING)
        tm.handle_playback_state(PlaybackState("stopped", "r1"))
        self.assertEqual(tm.state, USER_SPEAKING)
        self.assertIn((AGENT_SPEAKING, INTERRUPTED, "barge-in"), tm.transitions)

    def test_no_interruption_when_the_setting_is_off(self) -> None:
        tm = TurnManager(Policy(interrupt_on_user_speech=False, barge_in_speech_ms=100))
        tm.start()
        tm.state = AGENT_SPEAKING
        self.assertEqual(tm.handle_vad(_speech(900)), [])

    def test_a_reply_to_an_old_turn_is_dropped(self) -> None:
        tm = TurnManager(Policy(min_speech_ms=200, end_of_turn_silence_ms=600))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(600))
        tm.handle_vad(_silence(600))
        tm.handle_transcript(TranscriptEvent("final", "first question", 1))
        self.assertEqual(tm.state, THINKING)
        # The person goes on before the answer: a new turn opens. Until it
        # proves real the reply is held; once it is asked, the reply is stale.
        actions = tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        self.assertEqual(_kinds(actions), [Actions.CAPTURE_START])
        self.assertEqual(tm.turn_id, 2)
        self.assertEqual(_kinds(tm.reply_ready(1)), [Actions.HOLD_REPLY])
        tm.handle_vad(_speech(700))
        tm.handle_vad(_silence(600))
        tm.handle_transcript(TranscriptEvent("final", "second question", 2))
        self.assertEqual(_kinds(tm.reply_ready(1)), [Actions.DROP_REPLY])
        self.assertEqual(tm.response_id, 0)

    def test_ids_only_go_up(self) -> None:
        tm = self._speaking_manager()
        first_turn, first_response = tm.turn_id, tm.response_id
        tm.handle_vad(_speech(400))  # barge-in
        tm.handle_playback_state(PlaybackState("stopped", "r1"))
        tm.handle_vad(_silence(700))
        tm.handle_transcript(TranscriptEvent("final", "and another thing", tm.turn_id))
        tm.reply_ready(tm.turn_id)
        self.assertGreater(tm.turn_id, first_turn)
        self.assertGreater(tm.response_id, first_response)

    def test_a_transcript_for_another_turn_is_ignored(self) -> None:
        tm = TurnManager()
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        self.assertEqual(tm.handle_transcript(TranscriptEvent("final", "late", 99)), [])
        self.assertEqual(tm.state, USER_SPEAKING)

    def test_an_empty_final_goes_back_to_listening(self) -> None:
        tm = TurnManager(Policy(min_speech_ms=100, end_of_turn_silence_ms=300))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(300))
        tm.handle_vad(_silence(300))
        self.assertEqual(tm.handle_transcript(TranscriptEvent("final", "   ", tm.turn_id)), [])
        self.assertEqual(tm.state, LISTENING)

    def test_auto_listen_off_returns_to_idle(self) -> None:
        tm = self._speaking_manager()
        tm.auto_listen = False
        tm.handle_playback_state(PlaybackState("finished", "r1"))
        self.assertEqual(tm.state, IDLE)


class TestFrameVad(unittest.TestCase):
    def test_edges_fire_once_and_runs_accumulate(self) -> None:
        vad = FrameVad(FakeDetector(speech_frames=3), frame_ms=30, hangover_frames=0)
        kinds = [vad.process(b"\x00" * 960).kind for _ in range(6)]
        self.assertEqual(kinds, ["speech_start", "speech", "speech", "speech_end", "silence", "silence"])
        ev = vad.process(b"\x00" * 960)
        self.assertEqual(ev.silence_ms, 120)

    def test_hangover_bridges_a_frame_of_quiet_inside_a_word(self) -> None:
        class Flicker:
            name = "flicker"
            pattern = [True, True, False, True, True, False, False, False, False]

            def is_speech(self, frame: bytes) -> bool:
                return self.pattern.pop(0)

        vad = FrameVad(Flicker(), frame_ms=30, hangover_frames=1)
        kinds = [vad.process(b"").kind for _ in range(9)]
        self.assertEqual(kinds[:6], ["speech_start", "speech", "speech", "speech", "speech", "speech"])
        self.assertEqual(kinds[6], "speech_end")

    def test_sensitivity_names_map_to_thresholds(self) -> None:
        self.assertLess(threshold_for("high"), threshold_for("balanced"))
        self.assertLess(threshold_for("balanced"), threshold_for("low"))
        self.assertEqual(threshold_for("nonsense", 0.42), 0.42)


class _GrowingRecogniser(FakeRecogniser):
    """Transcribes "the length of what it was given", so partials differ."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        self.calls += 1
        await asyncio.sleep(0.01)
        words = " ".join("word" for _ in range(max(1, int(audio.seconds * 2))))
        return Utterance(text=words, confidence=0.9, seconds=audio.seconds, engine="fake", language="en")


async def _frames(seconds: float, frame_ms: int = 30):
    """Frames paced in time, as a microphone delivers them (1/15 of
    real time here), so a partial decode can finish between them."""
    frame = b"\x01\x00" * (16_000 * frame_ms // 1000)
    for _ in range(int(seconds * 1000 / frame_ms)):
        await asyncio.sleep(frame_ms / 15000)
        yield frame


class TestIncrementalRecogniser(unittest.IsolatedAsyncioTestCase):
    async def test_partials_then_one_final_that_replaces_them(self) -> None:
        inner = _GrowingRecogniser()
        stt = IncrementalRecogniser(inner, partial_every_ms=500, min_partial_ms=500)
        events = [e async for e in stt.start_stream(_frames(3.0), turn_id=7, language="en")]
        kinds = [e.kind for e in events]
        self.assertGreaterEqual(kinds.count("partial"), 1)
        self.assertEqual(kinds[-1], "final")
        self.assertEqual(kinds.count("final"), 1)
        self.assertTrue(all(e.turn_id == 7 for e in events))
        self.assertGreater(len(events[-1].text), len(events[0].text))
        self.assertAlmostEqual(events[-1].audio_seconds, 3.0, places=1)

    async def test_partials_can_be_switched_off(self) -> None:
        inner = _GrowingRecogniser()
        stt = IncrementalRecogniser(inner, partials=False)
        events = [e async for e in stt.start_stream(_frames(2.0), turn_id=1)]
        self.assertEqual([e.kind for e in events], ["final"])
        self.assertEqual(inner.calls, 1)

    async def test_no_audio_is_an_empty_final(self) -> None:
        stt = IncrementalRecogniser(_GrowingRecogniser())

        async def nothing():
            if False:
                yield b""

        events = [e async for e in stt.start_stream(nothing(), turn_id=3)]
        self.assertEqual([(e.kind, e.text) for e in events], [("final", "")])


if __name__ == "__main__":
    unittest.main()


class TestABlipWhileThinkingDoesNotLoseTheReply(unittest.TestCase):
    """Live, 2026-09-11: "You're not responding" took the model ten
    seconds; two short blips at the microphone meanwhile each opened
    and discarded a turn, the reply was judged stale, and nothing was
    said. A discarded blip must not make the owed reply stale; real
    speech must."""

    def _thinking(self) -> TurnManager:
        tm = TurnManager(Policy(end_of_turn_silence_ms=600, min_speech_ms=250))
        tm.start()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(600))
        tm.handle_vad(_silence(600))
        tm.handle_transcript(TranscriptEvent("final", "are you there", 1))
        self.assertEqual(tm.state, THINKING)
        return tm

    def test_a_blip_is_discarded_and_the_reply_is_still_spoken(self) -> None:
        tm = self._thinking()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))   # a blip
        self.assertEqual(tm.state, USER_SPEAKING)
        actions = tm.handle_vad(_silence(600))
        self.assertEqual(_kinds(actions), [Actions.DISCARD])
        self.assertEqual(tm.state, THINKING)                     # still owed an answer
        self.assertEqual(_kinds(tm.reply_ready(1)), [Actions.SPEAK])

    def test_a_reply_arriving_during_a_blip_is_held_then_spoken(self) -> None:
        tm = self._thinking()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        self.assertEqual(_kinds(tm.reply_ready(1)), [Actions.HOLD_REPLY])
        tm.handle_vad(_silence(600))                              # the blip ends: too short
        self.assertEqual(_kinds(tm.reply_ready(1)), [Actions.SPEAK])

    def test_real_speech_while_thinking_makes_the_reply_stale(self) -> None:
        tm = self._thinking()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(700))
        tm.handle_vad(_silence(600))
        actions = tm.handle_transcript(TranscriptEvent("final", "never mind, something else", tm.turn_id))
        self.assertEqual(_kinds(actions), [Actions.ASK])
        self.assertEqual(_kinds(tm.reply_ready(1)), [Actions.DROP_REPLY])
        self.assertEqual(_kinds(tm.reply_ready(tm.turn_id)), [Actions.SPEAK])

    def test_an_empty_final_during_thinking_keeps_thinking(self) -> None:
        tm = self._thinking()
        tm.handle_vad(VadEvent("speech_start", speech_ms=30))
        tm.handle_vad(_speech(700))
        tm.handle_vad(_silence(600))
        tm.handle_transcript(TranscriptEvent("final", "", tm.turn_id))
        self.assertEqual(tm.state, THINKING)
        self.assertEqual(_kinds(tm.reply_ready(1)), [Actions.SPEAK])
