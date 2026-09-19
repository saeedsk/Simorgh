"""One typed turn is one trace, percept to turn.completed (stage 1 item 2).

Before, a chat session used its conversation id as the trace of every
message it sent, so each turn of a conversation shared one trace, and the
context requests Cognition made while assembling a prompt minted fresh
traces of their own: "why was that turn slow" had no single answer.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel

_WATCHED = (topics.PERCEPT_TEXT_RECEIVED, topics.COGNITION_THINK, topics.PERSONA_VOICE,
            topics.SELF_SUMMARY, topics.TURN_COMPLETED)


class OneTurnIsOneTrace(unittest.IsolatedAsyncioTestCase):
    async def test_two_turns_are_two_traces_each_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp}}, None), secrets=EnvSecretStore({}))
            await kernel.boot()
            try:
                interface = kernel._supervisor.services["interface"].service  # noqa: SLF001
                interface._out = lambda *_: None  # noqa: SLF001
                seen: list[tuple[str, str]] = []

                def _see(message):
                    seen.append((message.type, message.trace_id))
                    return asyncio.sleep(0)

                subs = [await kernel.bus.subscribe(t, _see) for t in _WATCHED]
                traces = []
                for line in ("hello there", "and how are you"):
                    before = len(seen)
                    await interface._handle_line(line)  # noqa: SLF001
                    for _ in range(200):
                        if any(t == topics.TURN_COMPLETED for t, _ in seen[before:]):
                            break
                        await asyncio.sleep(0.05)
                    turn = seen[before:]
                    kinds = {t for t, _ in turn}
                    self.assertIn(topics.PERCEPT_TEXT_RECEIVED, kinds)
                    self.assertIn(topics.COGNITION_THINK, kinds)
                    self.assertIn(topics.TURN_COMPLETED, kinds)
                    ids = {tr for _, tr in turn}
                    self.assertEqual(len(ids), 1, turn)
                    traces.append(ids.pop())
                self.assertNotEqual(traces[0], traces[1])
                for sub in subs:
                    await sub.unsubscribe()
                # Stage 1 item 3: the turn's messages are spans in the
                # telemetry store, parented by causation, and the ledger
                # holds no `trace:` stream at all.
                spans = await kernel.telemetry.query(traces[1])
                names = {s["name"] for s in spans}
                self.assertIn(topics.PERCEPT_TEXT_RECEIVED, names)
                self.assertIn(topics.TURN_COMPLETED, names)
                # Stage 1 item 4: the provider call is a timed span under
                # the think message that asked for it.
                calls = [s for s in spans if s["name"] == "cognition.provider_call"]
                self.assertEqual(len(calls), 1, spans)
                think = [s for s in spans if s["name"] == topics.COGNITION_THINK]
                self.assertEqual(calls[0]["parent_id"], think[0]["span_id"])
                self.assertEqual(calls[0]["attrs"]["purpose"], "chat")
                self.assertGreaterEqual(calls[0]["end"], calls[0]["start"])
                ids = {s["span_id"] for s in spans}
                self.assertTrue(any(s["parent_id"] in ids for s in spans), spans)
                streams = Path(tmp) / "ledger" / "streams"
                self.assertEqual([p.name for p in streams.glob("trace%3A*")], [])
                # And a reader outside the process sees them (`simorgh trace`).
                await kernel.telemetry.flush()
                from simorgh.telemetry.store import read_trace
                self.assertEqual({s["span_id"] for s in read_trace(Path(tmp) / "telemetry.sqlite", traces[1])}, ids)
            finally:
                await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()


class AnActionIsTimedInItsTrace(unittest.IsolatedAsyncioTestCase):
    async def test_decide_and_run_are_spans_under_the_proposal(self):
        from simorgh.contracts.envelope import Message
        from simorgh.orchestration.tools import to_action_payload

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docs").mkdir()
            (Path(tmp) / "docs" / "note.txt").write_text("hello")
            kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp}, "execution": {"repo_root": tmp}}, None),
                            secrets=EnvSecretStore({}))
            await kernel.boot()
            try:
                done = asyncio.get_running_loop().create_future()

                async def _on_result(message):
                    if not done.done():
                        done.set_result(message)

                sub = await kernel.bus.subscribe(topics.ACTION_RESULT, _on_result)
                payload = to_action_payload(action_id="a1", task_id="t-trace", call={"tool": "read_file",
                                            "args": {"path": "docs/note.txt"}}, rationale="test", proposed_by="orchestration",
                                            kind="chat")
                proposal = Message.new(topics.ACTION_PROPOSED, source="orchestration", payload=payload,
                                       trace_id="trace-action-1")
                await kernel.bus.publish(proposal)
                result = await asyncio.wait_for(done, timeout=20)
                self.assertTrue(result.payload.get("ok"), result.payload)
                await sub.unsubscribe()
                spans = await kernel.telemetry.query("trace-action-1")
                by_name = {s["name"]: s for s in spans}
                self.assertIn("guardian.decide", by_name, spans)
                self.assertIn("execution.tool", by_name, spans)
                self.assertEqual(by_name["guardian.decide"]["parent_id"], proposal.id)
                self.assertEqual(by_name["guardian.decide"]["attrs"]["verdict"], "approved")
                self.assertEqual(by_name["execution.tool"]["attrs"]["tool"], "read_file")
                self.assertTrue(by_name["execution.tool"]["attrs"]["ok"])
            finally:
                await kernel.shutdown()
