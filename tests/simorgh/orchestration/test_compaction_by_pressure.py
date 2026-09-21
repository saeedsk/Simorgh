"""Stage 4 item 5: under token pressure, older tool results leave the
transcript for a ledger blob and come back with `recall_result`; the
transcript of a long task stays under the window."""

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import pressure, profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run

BIG = "line of a long file\n" * 100  # 2000 chars


class _Execution:
    """Approves every proposal and returns a long, distinct result."""

    def __init__(self, bus):
        self._bus, self._sub, self.n = bus, None, 0

    async def start(self):
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        self.n += 1
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": True, "output_ref": "",
            "stdout_preview": f"read #{self.n}\n{BIG}", "duration_ms": 1, "side_effects": []},
            source="execution"))


class _MeasuringCognition:
    """Asks for a read every turn until `turns`, then answers; reports the
    real size of what it was sent against a fixed window, as Cognition does."""

    def __init__(self, bus, *, turns: int, window_tokens: int):
        self._bus, self._turns, self._window = bus, turns, window_tokens
        self.calls, self.sizes, self._sub = [], [], None

    async def start(self):
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        self.calls.append(message)
        tokens = sum(len(str(m.get("content") or "")) for m in message.payload["messages"]) // 4
        self.sizes.append(tokens)
        done = len(self.calls) > self._turns
        payload = {
            "text": "all read" if done else "READ_FILE: notes.txt",
            "tool_calls": [] if done else [{"tool": "read_file", "args": {"path": f"notes{len(self.calls)}.txt"}}],
            "provider": "fake", "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False,
            "compaction": {"layers_applied": [], "tokens_before": tokens, "tokens_after": tokens,
                           "tokens_limit": self._window},
        }
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload=payload)


class PressureModule(unittest.TestCase):
    def test_pressure_is_before_over_limit(self):
        self.assertAlmostEqual(pressure.pressure({"compaction": {"tokens_before": 70, "tokens_limit": 100}}), 0.7)
        self.assertEqual(pressure.pressure({}), 0.0)

    @run
    async def test_old_results_are_stubbed_and_the_newest_kept(self):
        store = {}

        async def put(data):
            store[f"blob:{len(store)}"] = data
            return f"blob:{len(store) - 1}"

        messages = [{"role": "user", "content": "task"}]
        for i in range(4):
            messages += [{"role": "assistant", "content": "READ_FILE: x"},
                         {"role": "user", "content": f"Result of read_file:\n{i}{BIG}"}]
        messages.append({"role": "tool", "tool_call_id": "c", "name": "search_code", "content": BIG})
        out, made = await pressure.stub_old_results(messages, keep_recent=1, put=put)
        # `(ref, tool)` per result set aside, not a count: knowing a
        # result exists is not the same as being able to name it, and
        # a refused SEARCH block is told which refs it can recall
        # (`session.recall_hint`, 2026-09-20).
        self.assertEqual(len(made), 4)
        self.assertEqual([ref for ref, _tool in made], ["blob:0", "blob:1", "blob:2", "blob:3"])
        # The marker dialect writes the tool into the result TEXT
        # ("Result of read_file:"), not a `name` field, and that is
        # the dialect every trial that showed this mattered ran in.
        self.assertEqual({tool for _ref, tool in made}, {"read_file"})
        self.assertEqual(out[-1]["content"], BIG)
        self.assertTrue(out[2]["content"].startswith(pressure.STUB_MARK))
        self.assertIn("blob:0", out[2]["content"])
        self.assertEqual(store["blob:0"].decode(), messages[2]["content"])
        self.assertEqual(messages[2]["content"][:10], "Result of ")  # the input is not mutated
        again, made2 = await pressure.stub_old_results(out, keep_recent=1, put=put)
        self.assertEqual(made2, [])


class LongTaskStaysUnderTheWindow(unittest.TestCase):
    async def _run(self, turns, window):
        async with Harness() as h:
            cognition = _MeasuringCognition(h.client("cognition"), turns=turns, window_tokens=window)
            execution = _Execution(h.client("guardian"))
            await cognition.start()
            await execution.start()
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            session.budget.max_steps = turns + 5
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            outcome = await asyncio.wait_for(runner.run(session, user_text="read everything"), timeout=60)
            await cognition.stop()
            await execution.stop()
            return session, cognition, runner, outcome

    @run
    async def test_many_reads_never_outgrow_the_window(self):
        window = 4000
        session, cognition, runner, outcome = await self._run(turns=40, window=window)
        self.assertEqual(outcome.kind, "completed")
        # 40 results of ~2000 chars would be ~20k tokens uncompacted.
        self.assertLess(max(cognition.sizes), window)
        stubs = [m for m in session.messages if str(m.get("content") or "").startswith(pressure.STUB_MARK)]
        self.assertGreater(len(stubs), 30)
        # ...and the model is offered the way back.
        self.assertIn(pressure.RECALL_TOOL, cognition.calls[-1].payload["tools"])
        ref = stubs[0]["content"].split(f"call {pressure.RECALL_TOOL} with ", 1)[1].split(" to see", 1)[0]
        ok, text, _ = await runner._recall_result({"tool": pressure.RECALL_TOOL, "args": {"argument": ref}})
        self.assertTrue(ok)
        self.assertIn("read #1", text)

    @run
    async def test_no_pressure_no_stubs(self):
        session, cognition, _, _ = await self._run(turns=3, window=1_000_000)
        self.assertFalse(any(str(m.get("content") or "").startswith(pressure.STUB_MARK) for m in session.messages))
        self.assertNotIn(pressure.RECALL_TOOL, cognition.calls[-1].payload["tools"])


if __name__ == "__main__":
    unittest.main()
