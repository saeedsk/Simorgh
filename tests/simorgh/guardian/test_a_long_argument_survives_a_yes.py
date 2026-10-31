"""A person's "yes" to an action with a long argument verifies at Execution.

Live 2026-10-30: the creator answered "yes" twice to an `apply_skill`
(code=<4606 chars>) and both were denied a moment later, "signature
mismatch". Guardian records a proposal with any argument over the Ledger's
inline threshold spilled to a `blob:` ref, and `_on_prompt_answered`
issued the token over that recorded copy -- a hash of the ref. Execution
reads the body back and hashes the real code, so no long argument could
ever be approved by a person. Over a real Guardian Service on the memory bus.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import security, topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.guardian.config import Config
from simorgh.guardian.service import Service
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock

from .test_daily_human_tools import _Logger

LONG = "x = 1\n" * 1500   # 9000 chars, over the Ledger's 4096 inline threshold


class ALongArgumentSurvivesAYes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.proposer = make_client(backend, source="orchestration", ledger=self.ledger, clock=self.clock)
        self.listener = make_client(backend, source="execution", ledger=self.ledger, clock=self.clock)
        self.person = make_client(backend, source="interface", ledger=self.ledger, clock=self.clock)
        for client in (self.proposer, self.listener, self.person):
            await client.start()
        self.seen: asyncio.Queue = asyncio.Queue()
        for topic in (topics.ACTION_APPROVED, topics.ACTION_DENIED, topics.ACTION_NEEDS_HUMAN):
            await self.listener.subscribe(topic, self._on_outcome)
        bus = make_client(backend, source="guardian", ledger=self.ledger, clock=self.clock)
        await bus.start()
        self.guardian = Service(config=Config(irreversible_requires_human=False))
        await self.guardian.start(Context(
            name="guardian", instance_id="", run_id="test", mode="single", bus=bus, ledger=self.ledger,
            config={}, secrets={"__hmac__": "00" * 32}, clock=self.clock, logger=_Logger(),
            data_dir=Path(self._tmp.name)))

    async def asyncTearDown(self):
        await self.guardian.stop()
        self._tmp.cleanup()

    async def _on_outcome(self, message: Message) -> None:
        await self.seen.put(message)

    async def _next(self) -> Message:
        return await asyncio.wait_for(self.seen.get(), timeout=5.0)

    async def test_the_token_is_over_the_real_argument_not_its_blob_ref(self):
        args = {"feature": LONG}
        # `claude_code_task` asks a person on its first run of the day.
        await self.proposer.publish(Message.new(topics.ACTION_PROPOSED, source="orchestration", payload={
            "action_id": "long-1", "tool": "claude_code_task", "args": args,
            "scope": {"paths": [], "network": True}, "reversibility": "irreversible",
            "rationale": "test", "proposed_by": "orchestration", "requester": None, "requester_channel": "cli"}))
        self.assertEqual((await self._next()).type, topics.ACTION_NEEDS_HUMAN)
        (received,) = [e for e in await self.ledger.read("action:long-1") if e.type == "received"]
        self.assertTrue(received.payload["proposal"]["args"]["feature"].startswith("blob:"),
                        "the premise: the recorded copy holds a ref, not the body")

        await self.person.publish(Message.new(topics.UI_PROMPT_ANSWERED, source="interface",
                                              payload={"prompt_id": "long-1", "answer": "yes"}))
        approved = await self._next()
        self.assertEqual(approved.type, topics.ACTION_APPROVED)
        self.assertEqual(approved.payload["args_sha256"], security.canonical_args_sha256(args))


if __name__ == "__main__":
    unittest.main()
