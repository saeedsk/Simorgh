"""A quiet turn says WHICH rule kept it quiet.

The creator, 2026-09-24, mid-conversation: "why sim says not for me in
middle of 15 minutes dense conversation?" The honest answer at the time
was that nothing had kept it. Voice writes a specific `reason` on every
quiet decision -- "the same question again; the answer to turn 12 covers
it", "an unknown voice keeps talking without naming Sim: the TV, a
podcast or the radio", "heard Turkish, not a language of this house",
"Saeed was talking to Iris" -- and this handler printed the same four
words for all of them and dropped the reason on the floor.

The reason then existed for exactly one bus hop. It was not on the
screen, not on the ledger and not in the log, so the question could not
be answered after the fact either, by the household or by anyone reading
the records. Several of those reasons are not "not for me" at all: a
repeat of a question Sim already answered is Sim being tidy, and an
unplaceable voice is Sim being careful.
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


class AQuietTurnSaysWhichRuleTestCase(unittest.IsolatedAsyncioTestCase):
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
        self.service = Service(InterfaceConfig(chat_reply_timeout_s=0.3), run_repl=False)
        await self.service.start(self.ctx)
        self.other = make_client(self.backend, source="other", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _quiet(self, **extra) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await self.other.publish(self.other.new(topics.VOICE_SPOKEN, {
                "text": "", "seconds": 0.0, "engine": "", "device": "laptop",
                "quiet": True, **extra}))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if "🤫" in buf.getvalue():
                    break
        return buf.getvalue()

    async def test_the_reason_reaches_the_screen(self):
        why = "an unknown voice keeps talking without naming Sim: the TV, a podcast or the radio"
        out = await self._quiet(reason=why)
        self.assertIn(why, out)

    async def test_a_tidy_reason_is_not_reported_as_not_for_me(self):
        """"The same question again" is Sim being tidy, not Sim deciding
        it was not spoken to -- printing "not for me" for it was wrong."""
        out = await self._quiet(reason="the same question again; the answer to turn 12 covers it")
        self.assertIn("the same question again", out)
        self.assertNotIn("not for me", out)

    async def test_without_a_reason_it_still_says_something(self):
        """Voice's own `pipeline.py` publishes one quiet with no reason.
        That case keeps the old words rather than printing a bare glyph."""
        out = await self._quiet()
        self.assertIn("not for me", out)

    async def test_a_multiline_reason_stays_on_one_line(self):
        out = await self._quiet(reason="heard Turkish,\n   not a language\tof this house")
        self.assertIn("heard Turkish, not a language of this house", out)
