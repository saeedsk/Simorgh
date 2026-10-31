"""A `blob:<sha>` that IS the argument verifies, as one Guardian spilled does.

Live 2026-10-30: every `recall_result` -- whose argument is a stored
result's ref, `blob:431dd...` -- was denied "signature mismatch". Guardian
signed the ref as given; Execution took any `blob:<sha>` for one Guardian
had spilled, read the blob back, and hashed its contents instead. Both
versions are Guardian's own record of the proposal; the one the token
signed is the one that runs.
"""

from __future__ import annotations

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from tests.simorgh.execution.test_own_calls_go_through_guardian import _Tool
from tests.simorgh.execution.test_service import _ExecutionServiceTestCase


class ARefArgumentVerifies(_ExecutionServiceTestCase):
    async def _propose(self, action_id: str, args: dict) -> Message | None:
        waiting = self._wait_for(topics.ACTION_RESULT, predicate=lambda p: p.get("action_id") == action_id)
        import asyncio

        result = asyncio.ensure_future(waiting)
        await asyncio.sleep(0)
        await self.bus.publish(Message.new(topics.ACTION_PROPOSED, source="orchestration", payload={
            "action_id": action_id, "tool": "recall_result", "args": args,
            "scope": {"paths": [], "network": False}, "reversibility": "read_only",
            "rationale": "test", "proposed_by": "orchestration", "requester": None,
            "requester_channel": "cli"}))
        return await result

    async def test_a_ref_that_is_the_argument_runs_as_the_ref(self):
        await self._start()
        tool = _Tool("recall_result", reversibility="read_only")
        self.service._registry["recall_result"] = tool  # noqa: SLF001
        await self._guardian(approve=True)
        ref = await self.ledger.put_blob(b"the stored result", content_type="text/plain")
        result = await self._propose("ref-1", {"argument": ref})
        self.assertIsNotNone(result, "no action.result: the token was refused")
        self.assertTrue(result.payload.get("ok"), result.payload)
        self.assertEqual(tool.calls[0][0], {"argument": ref}, "the tool gets the ref it was asked for")
