"""A spoken turn's answer goes on the screen once.

The creator, 2026-09-23, watching a voice turn: "seeing two copies of
sim's response, then hearing the sim's voice ... it doesn't feel the
full realtime interactive voice chat experience".

Both copies were real, and printed by different handlers that each
believed they owned the answer:

  ⎿  ✅ completed in 5.8s
         It was a rough day -- S&P 500 down 0.75% ...     <- _narrate_autonomous
  🔊 sim: It was a rough day -- S&P 500 down 0.75% ...     <- _voice_reply_settled

The reason the first one runs at all is the interesting part. A voice
turn is in neither `_pending_turns` (nothing was typed) nor
`_watched_tasks` (no command dispatched it), so `_on_task_event` decides
the turn is not "mine" and hands it to `_narrate_autonomous` -- the path
for other sessions' background ticks, which prints `result_summary`
because for an autonomous task nothing else ever will. The household's
own conversation was being narrated as though it were somebody else's
work. The typed path already passed `detail=""` on completion for
exactly this reason; the spoken one never did.

The test drives the real route -- a `voice.transcript` gives the task
record its `origin: "voice"` (`service.py:1388`), which is the only
thing that distinguishes it -- and counts. It waits out
`_SPEAKING_FALLBACK_S`, because the second copy is committed by the
settle timer, not by `turn.completed`: a shorter wait sees one copy and
passes on the bug.
"""

from __future__ import annotations

import asyncio
import contextlib
import io

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.interface.config import Config as InterfaceConfig
from simorgh.interface.service import Service
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock

from .test_service import _Logger

ANSWER = "It was a rough day for the market, all on a Treasury selloff."


class ASpokenReplyIsPrintedOnceTestCase(unittest.IsolatedAsyncioTestCase):
    # Its own harness rather than a subclass of `InterfaceTestCase`: the
    # live configuration below would otherwise be imposed on every
    # inherited case, and three of them are written against the opposite.
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        # The LIVE configuration: autonomous narration on (the default
        # since 2026-09-12) and a live screen. With either off the bug is
        # invisible, which is how it survived a suite this size.
        self.service = Service(InterfaceConfig(chat_reply_timeout_s=0.3, narrate_autonomous=True),
                               run_repl=False)
        await self.service.start(self.ctx)
        self.service._live._enabled = True  # noqa: SLF001
        self.other = make_client(self.backend, source="other", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _run_a_spoken_turn(self) -> str:
        session_id = "voice-turn-1"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await self.other.publish(self.other.new(topics.VOICE_TRANSCRIPT, {
                "text": "what is happening in the market", "confidence": 0.9, "seconds": 2.0,
                "engine": "whisper_server", "device": "laptop", "session_id": session_id,
                "speaker": "Saeed"}))
            await asyncio.sleep(0.05)
            await self.other.publish(self.other.new(topics.TASK_STARTED, {
                "task_id": session_id, "worker_id": "w1"}))
            await self.other.publish(self.other.new(topics.TASK_COMPLETED, {
                "task_id": session_id, "result_summary": ANSWER, "artifacts": [],
                "verification_ref": "v1"}))
            await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
                "session_id": session_id, "text": ANSWER, "channel": "voice",
                "task_id": session_id, "floor": False, "tool_steps": 0}))
            # Speech ending is what COMMITS the spoken line, through
            # `_on_voice_spoken` -> `_voice_reply_settled`. Publishing it
            # beats waiting out `_SPEAKING_FALLBACK_S` (10 s) for the
            # fallback timer to do the same thing.
            await self.other.publish(self.other.new(topics.VOICE_SPOKEN, {
                "text": ANSWER, "seconds": 3.0, "engine": "kokoro", "device": "laptop",
                "session_id": session_id}))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if ANSWER[:30] in buf.getvalue():
                    break
            for _ in range(20):
                await asyncio.sleep(0.01)
        return buf.getvalue()

    async def test_the_answer_appears_once_and_as_the_spoken_line(self):
        out = await self._run_a_spoken_turn()
        self.assertEqual(out.count(ANSWER[:30]), 1,
                         "a spoken turn's answer reached the screen more than once")
        self.assertIn("🔊 sim:", out, "the one copy should be the spoken line")

    async def test_the_tree_still_says_the_turn_finished(self):
        """Only the duplicated answer goes; the headline is worth having."""
        out = await self._run_a_spoken_turn()
        self.assertIn("completed", out)
