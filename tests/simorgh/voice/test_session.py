"""The spoken conversation end to end with fakes (voice/session.py):
ten consecutive turns, barge-in, a stale reply dropped, self-echo not
answered, and the diagnostics that come out of it."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.voice.api import Audio, SAMPLE_RATE, SAMPLE_WIDTH
from simorgh.voice.config import Config
from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from simorgh.voice.pipeline import Pipeline
from simorgh.voice.session import VoiceSession
from simorgh.voice.turns import AGENT_SPEAKING, LISTENING, THINKING, USER_SPEAKING

FRAME = SAMPLE_RATE * 30 // 1000 * SAMPLE_WIDTH


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    def new(self, topic: str, payload: dict):
        return (topic, payload)

    async def publish(self, message) -> None:
        self.published.append(message)

    async def subscribe(self, topic, handler, **kw):
        class _Sub:
            async def unsubscribe(self_inner) -> None:
                pass
        return _Sub()

    def of(self, topic: str) -> list[dict]:
        return [p for t, p in self.published if t == topic]


class _Script:
    """A detector that follows a script of (speech?, frames) runs and
    then reports silence forever; `add` appends more runs live."""

    name = "script"

    def __init__(self, *runs: tuple[bool, int]) -> None:
        self.runs = list(runs)
        self.rms_value = 900.0

    def add(self, *runs: tuple[bool, int]) -> None:
        self.runs.extend(runs)

    def is_speech(self, frame: bytes) -> bool:
        while self.runs and self.runs[0][1] <= 0:
            self.runs.pop(0)
        if not self.runs:
            return False
        speech, left = self.runs[0]
        self.runs[0] = (speech, left - 1)
        return speech

    def rms(self, frame: bytes) -> float:
        return self.rms_value

    def raise_floor(self, rms: float) -> None:
        pass

    def set_ratio(self, ratio: float) -> None:
        pass


class _Replies:
    def __init__(self, replies: list[str], *, delay: float = 0.0) -> None:
        self.replies = replies
        self.delay = delay
        self.asked: list[str] = []

    async def ask(self, text: str, *, session_id=None, speaker_name: str = "", confidence: float = 1.0) -> str:
        self.asked.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]


def _config(**kw) -> Config:
    base = dict(stt="fake", tts="fake", endpoint_silence_ms=300, min_speech_ms=150, barge_in_speech_ms=300,
                stt_partials=False, backchannel=False, reply_timeout_s=5.0, keep_transcripts=False)
    base.update(kw)
    return Config(**base)


def _session(config: Config, script: _Script, replies: _Replies, *, speaker=None, recogniser=None,
             mic_delay: float = 0.0005):
    bus = _Bus()
    mic = FakeMicrophone(silence(0.03), frame_delay=mic_delay)
    speaker = speaker or FakeSpeaker()
    stt = recogniser or FakeRecogniser("what time is it", 0.95)
    tts = FakeSynthesiser()
    pipeline = Pipeline(bus=bus, clock=None, logger=None, ledger=None, config=config, microphone=mic, speaker=speaker,
                        recogniser=stt, synthesiser=tts, detector_factory=lambda: script)
    pipeline.ask = replies.ask  # type: ignore[method-assign] -- Sim, in one line
    session = VoiceSession(pipeline=pipeline, config=config, microphone=mic, speaker=speaker, recogniser=stt,
                           synthesiser=tts, detector_factory=lambda: script)
    return session, bus, speaker, tts


async def _run_until(session: VoiceSession, predicate, *, timeout: float = 5.0) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(session.run(stop))
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"timed out; state={session.state} turns={session.stats.turns}")
            await asyncio.sleep(0.01)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=3.0)


class TestTenTurns(unittest.IsolatedAsyncioTestCase):
    async def test_ten_consecutive_turns_flow_and_are_measured(self) -> None:
        # 20 frames of speech (600 ms), then 15 of silence (450 ms) -- ten times.
        script = _Script(*[(True, 20), (False, 15)] * 10 + [(False, 10_000)])
        replies = _Replies(["I'll check that now.", "It is three o'clock.", "Yes, that is right."])
        session, bus, speaker, tts = _session(_config(), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 10, timeout=8.0)
        self.assertEqual(session.stats.turns, 10)
        self.assertEqual(len(replies.asked), 10)
        self.assertEqual(session.turns.turn_id, 10)
        self.assertEqual(session.turns.response_id, 10)
        spoken = bus.of(topics.VOICE_SPOKEN)
        self.assertEqual(len(spoken), 10)
        self.assertEqual([p["turn"] for p in spoken], list(range(1, 11)))
        self.assertTrue(all("metrics" in p for p in spoken))
        m = spoken[-1]["metrics"]
        for key in ("stt", "llm", "first_audio", "response", "underruns", "chunks"):
            self.assertIn(key, m)
        # Connectors: sparse, never every turn.
        self.assertLessEqual(sum(1 for p in spoken if p["metrics"]["connector"]), 4)
        # Stopped by the test; before that, every reply handed the floor back.
        self.assertEqual(session.state, "idle")
        self.assertGreaterEqual(sum(1 for _f, to, _w in session.turns.transitions if to == LISTENING), 10)
        self.assertGreaterEqual(len(tts.spoken), 10)

    async def test_partials_are_published_and_the_final_replaces_them(self) -> None:
        class Growing(FakeRecogniser):
            async def transcribe(self, audio: Audio, *, language: str = "") -> object:
                await asyncio.sleep(0.005)
                words = max(1, int(audio.seconds / 0.3))
                from simorgh.voice.api import Utterance
                return Utterance(text=" ".join(["word"] * words), confidence=0.9, seconds=audio.seconds, engine="fake")

        script = _Script((True, 60), (False, 15), (False, 10_000))
        replies = _Replies(["Okay."])
        session, bus, *_ = _session(_config(stt_partials=True, stt_partial_every_ms=300), script, replies,
                                    recogniser=Growing(), mic_delay=0.002)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        transcripts = bus.of(topics.VOICE_TRANSCRIPT)
        partials = [p for p in transcripts if p.get("partial")]
        finals = [p for p in transcripts if not p.get("partial")]
        self.assertGreaterEqual(len(partials), 1)
        self.assertEqual(len(finals), 1)
        self.assertGreaterEqual(len(finals[0]["text"]), len(partials[0]["text"]))


class TestBargeIn(unittest.IsolatedAsyncioTestCase):
    async def test_talking_over_sim_stops_it_promptly_and_starts_the_next_turn(self) -> None:
        class LongSynth(FakeSynthesiser):
            async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
                self.spoken.append(text)
                return silence(3.0)

        speaker = FakeSpeaker(realtime=True)
        script = _Script((True, 20), (False, 15))
        replies = _Replies(["This is a long answer that will take a while to say out loud."])
        session, bus, speaker, tts = _session(_config(), script, replies, speaker=speaker)
        # Swap in the long synthesiser after construction.
        from simorgh.voice.tts.streaming import StreamingSynthesiser
        session._tts = StreamingSynthesiser(LongSynth(), lookahead=1)  # noqa: SLF001
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(500):
                if session.state == AGENT_SPEAKING:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(session.state, AGENT_SPEAKING)
            script.add((True, 40), (False, 15), (False, 10_000))  # a person cuts in for 1.2 s
            t0 = asyncio.get_running_loop().time()
            for _ in range(500):
                if session.stats.interruptions >= 1 and not session._player.playing:  # noqa: SLF001
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(session.stats.interruptions, 1)
            self.assertLess(asyncio.get_running_loop().time() - t0, 2.0)
            self.assertGreaterEqual(speaker.stopped, 1)
            self.assertEqual(session.turns.turn_id, 2)
            self.assertIn(session.state, (USER_SPEAKING, THINKING, AGENT_SPEAKING, LISTENING))
            for _ in range(500):
                if len(replies.asked) >= 2:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(len(replies.asked), 2)  # the interrupting words became the next turn
            spoken = bus.of(topics.VOICE_SPOKEN)
            self.assertTrue(spoken[0]["interrupted"])
            self.assertIn("interruption", spoken[0]["metrics"])
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_no_interruption_when_barge_in_is_off(self) -> None:
        speaker = FakeSpeaker(realtime=True)

        class LongSynth(FakeSynthesiser):
            async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
                return silence(0.6)

        script = _Script((True, 20), (False, 15), (True, 40), (False, 10_000))
        replies = _Replies(["A reply."])
        session, bus, speaker, tts = _session(_config(barge_in=False), script, replies, speaker=speaker)
        from simorgh.voice.tts.streaming import StreamingSynthesiser
        session._tts = StreamingSynthesiser(LongSynth())  # noqa: SLF001
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertEqual(session.stats.interruptions, 0)
        self.assertEqual(speaker.stopped, 0)


class TestStaleAndEcho(unittest.IsolatedAsyncioTestCase):
    async def test_a_reply_to_a_turn_that_is_over_is_never_spoken(self) -> None:
        # Sim is slow; the person speaks again meanwhile. The first reply
        # must be dropped, the second spoken.
        script = _Script((True, 20), (False, 15), (True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["first answer", "second answer"], delay=0.5)
        session, bus, speaker, tts = _session(_config(), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        await asyncio.sleep(0.05)
        spoken = [p for p in bus.of(topics.VOICE_SPOKEN) if not p.get("dropped")]
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0]["turn"], 2)
        self.assertEqual(spoken[0]["response"], 1)
        self.assertNotIn("first answer", " ".join(tts.spoken))
        dropped = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("dropped")]
        self.assertIn(1, [p["turn"] for p in dropped], "the screen is told the first answer was not spoken")
        self.assertIn("later turn", next(p for p in dropped if p["turn"] == 1)["reason"])

    async def test_sims_own_words_coming_back_are_not_a_turn(self) -> None:
        script = _Script((True, 20), (False, 15), (True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["the pool is exhausted so every request waits for a free connection"])
        heard = FakeRecogniser("what is wrong", 0.95)
        session, bus, speaker, tts = _session(_config(), script, replies, recogniser=heard)
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(500):
                if session.stats.turns >= 1:
                    break
                await asyncio.sleep(0.01)
            heard.text = "the pool is exhausted so every request waits for a free connection"  # the echo
            await asyncio.sleep(1.5)
            self.assertEqual(len(replies.asked), 1)
            echoes = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("echo")]
            self.assertEqual(len(echoes), 1)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)


def _in_conversation(built):
    """As if Sim had just spoken: the next words are presumably for it."""
    session = built[0]
    session._sim_spoke_at = session._now()  # noqa: SLF001
    return built


class TestTheBackchannel(unittest.IsolatedAsyncioTestCase):
    """The moment a turn ends Sim says "Aha." / "Let me check." and only
    then thinks; the reply follows and does not open with another
    "Okay,". The creator, 2026-09-11: "sim should not remain silent for
    a long time to process and reply back"."""

    async def test_words_that_may_not_be_for_sim_get_no_sound(self) -> None:
        # No name said and Sim has not spoken for a long while: whoever
        # is talking may be talking to someone else. Silence, then the
        # model's answer if it judges the words were for Sim.
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Twelve."], delay=1.0)
        session, bus, speaker, tts = _session(_config(backchannel=True, backchannel_after_ms=200), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertFalse([p for p in bus.of(topics.VOICE_SPOKEN) if p.get("aside")])
        self.assertEqual(tts.spoken[-1], "Twelve.")

    async def test_a_quiet_verdict_is_not_spoken_and_the_floor_is_handed_back(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["QUIET"], delay=0.1)
        session, bus, speaker, tts = _session(_config(backchannel=True), script, replies)
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(800):
                if any(p.get("quiet") for p in bus.of(topics.VOICE_SPOKEN)):
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            self.assertEqual(session.state, LISTENING)
            self.assertEqual(session.stats.turns, 0)
            self.assertNotIn("QUIET", tts.spoken)
            self.assertEqual(len(replies.asked), 1)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_a_sound_is_made_before_the_answer_and_the_answer_does_not_repeat_it(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Okay, the pool has twelve connections."], delay=1.0)
        session, bus, speaker, tts = _in_conversation(_session(_config(backchannel=True, backchannel_after_ms=200), script, replies))
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        spoken = bus.of(topics.VOICE_SPOKEN)
        self.assertTrue(spoken[0].get("aside"), "the first thing said is the aside")
        ack = spoken[0]["text"]
        from simorgh.voice.backchannel import POOLS
        every = {text for pool in POOLS.values() for texts in pool.values() for text in texts}
        self.assertIn(ack, every, "and it is a backchannel")
        said = tts.spoken  # the synthesiser's warm-up line first, then the aside, then the reply
        self.assertIn(ack, said)
        answer = next(i for i, t in enumerate(said) if "pool has twelve" in t)
        self.assertLess(said.index(ack), answer, said)
        self.assertNotIn("Okay,", said[answer], "the reply's own Okay was dropped -- one was already said")
        self.assertLess(len(replies.asked), 2, "the sound was not a turn")

    async def test_a_quick_answer_gets_no_sound_at_all(self) -> None:
        # The answer is back in 0.1 s; a sound on top of it is a tic.
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Twelve."], delay=0.1)
        session, bus, speaker, tts = _session(_config(backchannel=True, backchannel_after_ms=400), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        await asyncio.sleep(0.6)
        self.assertFalse([p for p in bus.of(topics.VOICE_SPOKEN) if p.get("aside")])

    async def test_two_slow_turns_in_a_row_get_one_sound_not_two(self) -> None:
        script = _Script((True, 20), (False, 15))  # no long silent tail: `add` below must play at once
        replies = _Replies(["Twelve.", "Thirteen."], delay=0.8)
        session, bus, speaker, tts = _in_conversation(_session(_config(backchannel=True, backchannel_after_ms=200,
                                                      backchannel_gap_s=30.0), script, replies))
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(800):
                if session.stats.turns >= 1 and session.state == LISTENING:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(session.stats.turns, 1)
            script.add((True, 20), (False, 15), (False, 10_000))  # the person again, seconds later
            for _ in range(800):
                if session.stats.turns >= 2:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(session.stats.turns, 2)
            self.assertEqual(len([p for p in bus.of(topics.VOICE_SPOKEN) if p.get("aside")]), 1)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_the_sound_comes_before_a_slow_answer_not_after(self) -> None:
        # The answer takes 1.5 s; the sound must be out well before it.
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Twelve."], delay=1.5)
        session, bus, speaker, tts = _in_conversation(_session(_config(backchannel=True, backchannel_after_ms=200), script, replies))
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            t0 = asyncio.get_running_loop().time()
            for _ in range(800):
                if any(p.get("aside") for p in bus.of(topics.VOICE_SPOKEN)):
                    break
                await asyncio.sleep(0.01)
            asides = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("aside")]
            self.assertTrue(asides, "nothing was said")
            self.assertLess(asyncio.get_running_loop().time() - t0, 1.2)
            self.assertNotIn("Twelve.", tts.spoken, "the answer itself was still to come")
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_a_long_think_gets_a_second_sound(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Twelve."], delay=1.2)
        session, bus, speaker, tts = _in_conversation(_session(_config(backchannel=True, backchannel_after_ms=100, still_after_s=0.5,
                                                      backchannel_gap_s=0.0), script, replies))
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        from simorgh.voice.backchannel import STILL
        stills = {text for texts in STILL.values() for text in texts}
        self.assertTrue(any(t in stills for t in tts.spoken), tts.spoken)

    async def test_off_means_silence_until_the_answer(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Twelve."], delay=0.3)
        session, bus, speaker, tts = _session(_config(backchannel=False), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertEqual(tts.spoken[-1], "Twelve.")
        self.assertFalse([p for p in bus.of(topics.VOICE_SPOKEN) if p.get("aside")])


class TestMisheardName(unittest.IsolatedAsyncioTestCase):
    async def test_seem_do_something_reaches_sim_as_sim_and_the_screen_shows_the_reading(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["On it."])
        heard = FakeRecogniser("Seem do something", 0.95)
        session, bus, speaker, tts = _session(_config(), script, replies, recogniser=heard)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertEqual(replies.asked, ["Sim, do something"])
        corrected = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("corrected")]
        self.assertEqual([p["text"] for p in corrected], ["Sim, do something"])


class TestDelivery(unittest.IsolatedAsyncioTestCase):
    """A reply is delivered for the situation (voice/delivery.py): warm
    and slower for a hurt, and the person hears a half-loud "uh-huh"
    when they pause mid-story."""

    async def test_a_hurt_is_answered_slower_and_softer(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["I'm sorry to hear that."])
        heard = FakeRecogniser("my dog died yesterday and I am so tired", 0.95)
        session, bus, speaker, tts = _session(_config(), script, replies, recogniser=heard)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertLess(tts.speeds[-1], 1.0, tts.speeds)
        spoken = [p for p in bus.of(topics.VOICE_SPOKEN) if not p.get("aside")]
        self.assertEqual(spoken[-1]["metrics"]["register"], "warm")

    async def test_a_plain_question_is_answered_at_normal_pace(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Twelve."])
        session, bus, speaker, tts = _session(_config(), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertEqual(tts.speeds[-1], 1.0)

    async def test_a_listener_hums_under_a_long_story(self) -> None:
        # 7.5 s of talk, a breath, more talk: the breath gets a half-loud
        # "uh-huh" under it; the turn goes on and is asked once.
        script = _Script((True, 250), (False, 4), (True, 30), (False, 15), (False, 10_000))
        replies = _Replies(["Go on."])
        session, bus, speaker, tts = _session(_config(backchannel=True, hum=True, hum_after_ms=6000), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        hums = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("register") == "hum"]
        self.assertEqual(len(hums), 1, [p.get("text") for p in bus.of(topics.VOICE_SPOKEN)])
        from simorgh.voice.backchannel import HEARD, POOLS
        self.assertIn(hums[0]["text"], POOLS[HEARD]["en"])
        self.assertEqual(len(replies.asked), 1)

    async def test_no_hum_for_a_short_remark(self) -> None:
        script = _Script((True, 20), (False, 4), (True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["Okay."])
        session, bus, speaker, tts = _session(_config(backchannel=True, hum=True), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertFalse([p for p in bus.of(topics.VOICE_SPOKEN) if p.get("register") == "hum"])


class TestSpokenCommands(unittest.IsolatedAsyncioTestCase):
    """"Stop" and "voice off", said aloud, are obeyed at once and never
    sent to the model (the creator, 2026-09-11: saying "voice off"
    did not stop Sim talking)."""

    async def test_stop_said_over_sim_cuts_playback_and_asks_nothing(self) -> None:
        class LongSynth(FakeSynthesiser):
            async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
                self.spoken.append(text)
                return silence(3.0)

        speaker = FakeSpeaker(realtime=True)
        script = _Script((True, 20), (False, 15))
        replies = _Replies(["A long answer that goes on and on."])
        heard = FakeRecogniser("what time is it", 0.95)
        session, bus, speaker, tts = _session(_config(), script, replies, speaker=speaker, recogniser=heard)
        from simorgh.voice.tts.streaming import StreamingSynthesiser
        session._tts = StreamingSynthesiser(LongSynth(), lookahead=1)  # noqa: SLF001
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(500):
                if session.state == AGENT_SPEAKING:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(session.state, AGENT_SPEAKING)
            heard.text = "Stop talking."
            script.add((True, 40), (False, 15))  # the person cuts in and says it
            for _ in range(500):
                if any(p.get("command") for p in bus.of(topics.VOICE_SPOKEN)):
                    break
                await asyncio.sleep(0.01)
            commands = [p for p in bus.of(topics.VOICE_SPOKEN) if p.get("command")]
            self.assertEqual([p["command"] for p in commands], ["stop"])
            self.assertGreaterEqual(speaker.stopped, 1)
            self.assertFalse(session._player.playing)  # noqa: SLF001
            await asyncio.sleep(0.05)
            self.assertEqual(session.state, LISTENING)
            self.assertEqual(replies.asked, ["what time is it"], "the command never reached the model")
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_voice_off_said_aloud_asks_the_service_to_switch_off(self) -> None:
        script = _Script((True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["never"])
        heard = FakeRecogniser("Voice off.", 0.95)
        session, bus, speaker, tts = _session(_config(), script, replies, recogniser=heard)
        await _run_until(session, lambda: bool(bus.of(topics.VOICE_CONTROL_REQUEST)), timeout=8.0)
        self.assertEqual(bus.of(topics.VOICE_CONTROL_REQUEST)[0]["action"], "off")
        self.assertEqual(replies.asked, [])
        self.assertEqual([p["command"] for p in bus.of(topics.VOICE_SPOKEN) if p.get("command")], ["off"])


class TestBargeInWithTheRealLevelGate(unittest.IsolatedAsyncioTestCase):
    """The scripted detector above says what it is told. These use the
    real level gate (EnergyDetector inside CompositeDetector) with a
    microphone whose frames have real loudness, because that is where
    barge-in broke on 2026-09-11: the gate learnt its bar from every
    frame it heard, the person's included, so nobody could ever be
    louder than the bar and Sim never stopped."""

    async def _speaking_session(self, echo_rms: float, person_rms: float, *, calibrate_ms: int = 300):
        import array
        import math

        from simorgh.voice.vad import CompositeDetector, EnergyDetector

        class Voiced:
            """Silero's stand-in: anything with sound in it is a voice --
            Sim's echo as much as a person."""
            name = "voiced"

            def is_speech(self, frame: bytes) -> bool:
                return EnergyDetector.rms(frame) > 250.0

        class LevelMic(FakeMicrophone):
            """Frames at a real RMS: the person's level while they talk,
            else Sim's echo while the speaker plays, else the room."""

            def __init__(self) -> None:
                super().__init__(silence(0.03), frame_delay=0.0005)
                self.room = 100.0
                self.echo = echo_rms
                self.person = 0.0
                self.playing = False

            @property
            def rms(self) -> float:
                return self.person or (self.echo if self.playing else self.room)

            async def stream(self, *, max_seconds: float = 0.0):
                n = SAMPLE_RATE * 30 // 1000
                while True:
                    await asyncio.sleep(self._delay)
                    amp = self.rms * math.sqrt(2)
                    yield array.array("h", [int(amp * math.sin(i / 3)) for i in range(n)]).tobytes()

        class EchoingSpeaker(FakeSpeaker):
            """While it plays, the microphone hears the echo -- from the
            first frame, as a real room does, not from whenever a test
            polling every 10 ms happens to notice."""

            async def play(self, audio: Audio) -> None:
                mic.playing = True
                try:
                    await super().play(audio)
                finally:
                    mic.playing = False

        class ToneSynth(FakeSynthesiser):
            """A reply with real level, 3 s long, so the reference has an envelope."""

            async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
                self.spoken.append(text)
                n = int(3.0 * SAMPLE_RATE)
                return Audio(array.array("h", [int(8000 * math.sin(i / 3)) for i in range(n)]).tobytes())

        config = _config(barge_in_calibrate_ms=calibrate_ms, barge_in_ratio=2.8)
        bus = _Bus()
        mic = LevelMic()
        speaker = EchoingSpeaker(realtime=True)
        stt = FakeRecogniser("what time is it", 0.95)
        tts = ToneSynth()
        detector = CompositeDetector(Voiced(), EnergyDetector(0.5))
        pipeline = Pipeline(bus=bus, clock=None, logger=None, ledger=None, config=config, microphone=mic,
                            speaker=speaker, recogniser=stt, synthesiser=tts, detector_factory=lambda: detector)
        replies = _Replies(["A long answer, spoken as a three second tone."])
        pipeline.ask = replies.ask  # type: ignore[method-assign]
        session = VoiceSession(pipeline=pipeline, config=config, microphone=mic, speaker=speaker, recogniser=stt,
                               synthesiser=tts, detector_factory=lambda: detector)
        return session, mic, speaker, replies, bus

    async def _until(self, predicate, seconds: float) -> bool:
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return True
            await asyncio.sleep(0.01)
        return predicate()

    async def _drive(self, mic, session, echo_rms: float, person_rms: float, *, person_after_s: float) -> None:
        # A quiet room first, so the gate learns its floor from the room
        # and not from the person's opening word; then the person asks
        # something (loud), then quiet; Sim answers.
        await asyncio.sleep(0.3)
        mic.person = 6000.0
        self.assertTrue(await self._until(lambda: session.state == USER_SPEAKING, 3.0), session.state)
        await asyncio.sleep(0.3)
        mic.person = 0.0
        self.assertTrue(await self._until(lambda: session.state == AGENT_SPEAKING, 5.0), session.state)
        # Sim is speaking and the mic hears its echo (the speaker sees to
        # that); then the person, at `person_rms`, for as long as it takes.
        await asyncio.sleep(person_after_s)
        mic.person = person_rms if person_rms != echo_rms else 0.0

    async def test_a_person_louder_than_sims_echo_stops_sim(self) -> None:
        session, mic, speaker, replies, bus = await self._speaking_session(echo_rms=2000.0, person_rms=9000.0)
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            await self._drive(mic, session, 2000.0, 9000.0, person_after_s=0.6)
            t0 = asyncio.get_running_loop().time()
            stopped = await self._until(lambda: session.stats.interruptions >= 1 and not session._player.playing, 2.5)  # noqa: SLF001
            self.assertTrue(stopped, f"Sim did not stop; state={session.state}")
            self.assertLess(asyncio.get_running_loop().time() - t0, 2.0)
            self.assertGreaterEqual(speaker.stopped, 1)
            mic.person = 0.0
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_sims_own_echo_however_loud_does_not_stop_sim(self) -> None:
        # The echo is 2000 for the whole reply; nobody speaks. Sim must
        # finish all three seconds and go back to listening.
        session, mic, speaker, replies, bus = await self._speaking_session(echo_rms=2000.0, person_rms=2000.0)
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            await self._drive(mic, session, 2000.0, 2000.0, person_after_s=0.2)
            finished = await self._until(lambda: session.stats.turns >= 1, 6.0)
            mic.person = 0.0
            self.assertTrue(finished, session.state)
            self.assertEqual(session.stats.interruptions, 0)
            self.assertEqual(speaker.stopped, 0)
            self.assertEqual(len(replies.asked), 1, "Sim's echo was not a turn")
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_the_person_can_be_quieter_than_the_bar_learnt_from_themselves(self) -> None:
        # The regression itself: the person talks at 5000 -- louder than
        # the echo, quieter than 2.8 x their own level. With a bar learnt
        # from the mic they could never win; from the reference they do.
        session, mic, speaker, replies, bus = await self._speaking_session(echo_rms=1500.0, person_rms=5000.0)
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            await self._drive(mic, session, 1500.0, 5000.0, person_after_s=0.6)
            stopped = await self._until(lambda: session.stats.interruptions >= 1, 2.5)
            mic.person = 0.0
            self.assertTrue(stopped, f"Sim did not stop; state={session.state}")
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)


if __name__ == "__main__":
    unittest.main()


class TestASlowModelAndANoisyRoom(unittest.IsolatedAsyncioTestCase):
    async def test_blips_while_thinking_do_not_lose_the_reply(self) -> None:
        # Speech, then a slow answer; during the wait, two short blips.
        script = _Script((True, 20), (False, 15), (False, 10), (True, 2), (False, 15), (True, 2), (False, 10_000))
        replies = _Replies(["I'm here, and I am replying."], delay=1.0)
        session, bus, speaker, tts = _session(_config(), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        spoken = bus.of(topics.VOICE_SPOKEN)
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0]["turn"], 1)
        self.assertEqual(len(replies.asked), 1)


class TestASupersededAskIsCancelled(unittest.IsolatedAsyncioTestCase):
    async def test_a_new_real_turn_cancels_the_chat_still_running_for_the_old_one(self) -> None:
        # Sim is slow; the person speaks a whole new turn meanwhile.
        script = _Script((True, 20), (False, 15), (True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["first answer", "second answer"], delay=0.6)
        session, bus, speaker, tts = _session(_config(), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        cancels = bus.of(topics.TASK_CANCEL)
        self.assertEqual(len(cancels), 1)
        self.assertIn("new turn", cancels[0]["reason"])
        spoken = [p for p in bus.of(topics.VOICE_SPOKEN) if not p.get("dropped")]
        self.assertEqual([p["turn"] for p in spoken], [2])
