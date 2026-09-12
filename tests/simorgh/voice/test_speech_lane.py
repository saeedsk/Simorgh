"""One voice at a time (2026-09-11): the creator heard two Sims speaking
different things in parallel, and Sim transcribed its own reply as the
person. Every speaker takes the pipeline's speech lock; the service's
speak-every-reply path leaves a spoken turn's reply to the session; and
speech from outside the session goes through it, so the turn manager
knows Sim is talking."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.voice.api import Audio
from simorgh.voice.config import Config
from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from simorgh.voice.pipeline import Pipeline
from simorgh.voice.session import VoiceSession
from simorgh.voice.turns import AGENT_SPEAKING, LISTENING

from .test_session import _Bus, _Replies, _Script, _config


class _Half(FakeSynthesiser):
    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        self.spoken.append(text)
        return silence(0.3)


def _pipeline(speaker=None):
    bus = _Bus()
    pipe = Pipeline(bus=bus, clock=None, logger=None, ledger=None, config=Config(barge_in=False),
                    microphone=None, speaker=speaker or FakeSpeaker(realtime=True), recogniser=FakeRecogniser(),
                    synthesiser=_Half(), detector_factory=lambda: None)
    return pipe, bus


class TestOneVoiceAtATime(unittest.IsolatedAsyncioTestCase):
    async def test_two_speak_calls_never_overlap(self) -> None:
        speaker = FakeSpeaker(realtime=True)
        pipe, bus = _pipeline(speaker)
        spans = []

        async def timed(text):
            t0 = asyncio.get_running_loop().time()
            await pipe.speak(text)
            spans.append((t0, asyncio.get_running_loop().time()))

        await asyncio.gather(timed("First reply here."), timed("Second reply here."))
        spans.sort()
        self.assertLessEqual(spans[0][1], spans[1][1])
        # The second's playback started only after the first finished.
        self.assertEqual(len(speaker.played), 2)
        self.assertGreaterEqual(spans[1][1] - spans[0][0], 0.55)

    async def test_a_voice_turns_reply_is_remembered_as_the_sessions_own(self) -> None:
        pipe, bus = _pipeline()

        async def answer():
            await asyncio.sleep(0.01)
            fut = pipe._pending["s-1"]  # noqa: SLF001
            fut.set_result("the answer")

        asyncio.create_task(answer())
        await pipe.ask("hello", session_id="s-1")
        self.assertNotIn("s-1", pipe._pending)  # noqa: SLF001 -- gone the moment the reply lands ...
        self.assertTrue(pipe.is_voice_session("s-1"))  # ... which is why this exists
        self.assertFalse(pipe.is_voice_session("typed-9"))


class TestSpeechThroughTheSession(unittest.IsolatedAsyncioTestCase):
    async def test_say_marks_sim_as_speaking_and_hands_the_floor_back(self) -> None:
        script = _Script((False, 10_000))
        replies = _Replies(["unused"])
        from .test_session import _session
        session, bus, speaker, tts = _session(_config(), script, replies)
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(200):
                if session.state == LISTENING:
                    break
                await asyncio.sleep(0.01)
            seen = []
            session._announce = lambda state: seen.append(state) or asyncio.sleep(0)  # noqa: SLF001
            said = await session.say("This reply was typed, not spoken.")
            self.assertEqual(said, "This reply was typed, not spoken.")
            self.assertIn(AGENT_SPEAKING, seen)
            self.assertEqual(session.state, LISTENING)
            self.assertEqual(session._pipeline.last_said, said)  # noqa: SLF001 -- so an echo of it is recognised
            spoken = bus.of(topics.VOICE_SPOKEN)
            self.assertEqual(spoken[-1]["text"], said)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)


class TestStartTaskFromAChat(unittest.IsolatedAsyncioTestCase):
    async def test_a_chat_may_start_work_a_task_may_not(self) -> None:
        from simorgh.contracts.protocols import ToolContext
        from simorgh.execution.config import Config as ExecConfig
        from simorgh.execution.tools import StartTaskTool
        tool = StartTaskTool(ExecConfig())

        def ctx(kind: str):
            return ToolContext(action_id="a", task_id="t-1", scope={"kind": kind}, constraints={},
                               data_dir=ExecConfig().repo_root, clock=None, logger=None, ledger=None, bus=None)

        refused = await tool.run({"goal": "fix the voice"}, ctx=ctx("patch"))
        self.assertIn("fork bomb", refused.error)
        allowed = await tool.run({"goal": "fix the voice"}, ctx=ctx("chat"))
        self.assertNotIn("fork bomb", allowed.error or "")


if __name__ == "__main__":
    unittest.main()
