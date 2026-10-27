"""Core memory blocks in a chat turn (stage 15 item 8).

The recent recall of a chat turn asks Memory for the core blocks
(`core_for`, the speaker). With `[memory] core_blocks` off Memory sends no
`core`, and the turn -- messages and tools -- is exactly what it was. On,
the household's and the speaker's blocks are rendered as a per-turn system
block (never in the cacheable prefix) and the turn is offered
`memory_core_edit`.
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import CORE_MEMORY_HEADER
from simorgh.orchestration.session import CORE_EDIT_TOOL, SessionRunner
from simorgh.orchestration.tools import is_read_only, offered_tools

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run


async def _turn(h, core, *, speaker="", text="what's for dinner"):
    """One chat turn against a Memory that answers every recall, adding
    `core` when it is not None. The think payload and the recalls come back."""
    memory = h.client("memory")
    asked: list[dict] = []

    async def _recall(message):
        asked.append(dict(message.payload))
        payload = {"items": [], "truncated": False}
        if core is not None and "core_for" in message.payload:
            payload["core"] = core
        await memory.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload=payload)

    sub = await memory.subscribe(topics.MEMORY_RETRIEVE, _recall)
    cognition = FakeCognition(h.client("cognition"), script=[{"text": "pasta"}])
    gx = FakeGuardianExecution(h.client("guardian"))
    await cognition.start()
    await gx.start()
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=lambda: 1_790_000_000.0, assemble_timeout_s=2.0)
    session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT, user_text=text, speaker=speaker)
    await asyncio.wait_for(runner.run(session, user_text=text), timeout=10)
    await cognition.stop()
    await gx.stop()
    await sub.unsubscribe()
    return cognition.calls[0].payload, asked


def _text(payload) -> str:
    return "\n".join(str(m.get("content") or "") for m in payload["messages"])


class CoreBlocksInATurn(unittest.TestCase):
    @run
    async def test_off_the_turn_is_what_it_was(self):
        async with Harness() as h:
            payload, asked = await _turn(h, None)
        self.assertEqual(payload["tools"], list(offered_tools(profiles.CHAT.tools)))
        self.assertNotIn(CORE_EDIT_TOOL, payload["tools"])
        self.assertNotIn("core memory", _text(payload))
        # The recent recall asked; only Memory's answer turns anything on.
        self.assertEqual([a.get("core_for") for a in asked if "core_for" in a], [""])

    @run
    async def test_on_with_no_block_offers_the_tool_and_renders_nothing(self):
        async with Harness() as h:
            off, _ = await _turn(h, None)
        async with Harness() as h:
            on, _ = await _turn(h, [])
        self.assertEqual(on["messages"], off["messages"], "no block, no text")
        self.assertEqual(on["tools"], off["tools"] + [CORE_EDIT_TOOL])

    @run
    async def test_the_blocks_are_rendered_for_the_speaker(self):
        core = [{"block": "household", "label": "household", "text": "bins go out Tuesday"},
                {"block": "person:soodeh", "label": "Soodeh", "text": "prefers Farsi; tea, not coffee"}]
        async with Harness() as h:
            payload, asked = await _turn(h, core, speaker="Soodeh")
        self.assertIn("Soodeh", [a.get("core_for") for a in asked])
        system = [m for m in payload["messages"] if m.get("role") == "system"
                  and str(m.get("content") or "").startswith(CORE_MEMORY_HEADER)]
        self.assertEqual(len(system), 1)
        self.assertIn("[household]\nbins go out Tuesday", system[0]["content"])
        self.assertIn("[Soodeh]\nprefers Farsi; tea, not coffee", system[0]["content"])
        # Per-turn, not the cacheable prefix: the prefix is `task_rules`.
        self.assertNotIn("prefers Farsi", str(payload.get("task_rules") or ""))
        self.assertIn(CORE_EDIT_TOOL, payload["tools"])

    def test_the_tool_is_reversible_not_read_only(self):
        from simorgh.orchestration.tools import is_irreversible

        self.assertFalse(is_read_only(CORE_EDIT_TOOL))
        self.assertFalse(is_irreversible(CORE_EDIT_TOOL))


if __name__ == "__main__":
    unittest.main()
