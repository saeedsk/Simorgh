"""Stage 17 item 7: observation masking beyond token pressure.

`[orchestration] mask_after_steps` (default 0 = off): a tool result that
many steps old becomes the compaction stub plus a one-line gist made by
code, at any pressure. Never the latest result, never a result of the
pending step, never an error the model has not yet answered;
`recall_result` still returns the full original, and off is
byte-identical."""

import asyncio
import json
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import pressure, profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.config import Config
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run

BIG = "line of a long file\n" * 40  # 800 chars


class _Store:
    """A content-addressed `put`, as the sqlite ledger is."""

    def __init__(self):
        self.blobs = {}

    async def put(self, data: bytes) -> str:
        ref = f"blob:{pressure.digest(data.decode())}"
        self.blobs[ref] = data
        return ref


def _marker(tool: str, body: str) -> dict:
    return {"role": "user", "content": f"Result of {tool}:\n{body}\n\nIf the task is now finished, reply."}


def _steps(n: int, tool: str = "read_file") -> list[dict]:
    messages = [{"role": "user", "content": "task"}]
    for i in range(n):
        messages += [{"role": "assistant", "content": f"{tool.upper()}: x{i}"}, _marker(tool, f"read #{i}\n{BIG}")]
    return messages


def _masked(message: dict) -> bool:
    return str(message.get("content") or "").startswith(pressure.STUB_MARK)


class MaskingRules(unittest.TestCase):
    @run
    async def test_off_changes_nothing(self):
        messages = _steps(5)
        out, made = await pressure.mask_old_results(messages, after_steps=0, put=_Store().put)
        self.assertEqual(out, messages)
        self.assertEqual(made, [])

    @run
    async def test_results_that_old_are_masked_with_a_gist(self):
        store = _Store()
        messages = _steps(4)
        out, made = await pressure.mask_old_results(messages, after_steps=2, put=store.put)
        # Results at indices 2, 4, 6, 8; ages 3, 2, 1, 0.
        self.assertEqual([_masked(m) for m in out[2::2]], [True, True, False, False])
        self.assertEqual(len(made), 2)
        stub = out[2]["content"]
        self.assertIn("recall_result with blob:", stub)
        self.assertTrue(stub.endswith(f"{pressure.GIST_MARK} read #0"), stub)
        self.assertEqual("\n" in stub, False)
        self.assertEqual(store.blobs[made[0][0]].decode(), messages[2]["content"])
        self.assertEqual(made[0][1], "read_file")
        self.assertTrue(messages[2]["content"].startswith("Result of"))  # input not mutated

    @run
    async def test_the_latest_result_is_never_masked(self):
        # A chat transcript: the result, the final answer, the next question.
        messages = [{"role": "user", "content": "q1"},
                    {"role": "assistant", "content": "READ_FILE: x"}, _marker("read_file", BIG),
                    {"role": "assistant", "content": "the answer"}, {"role": "user", "content": "q2"},
                    {"role": "assistant", "content": "hm"}]
        out, made = await pressure.mask_old_results(messages, after_steps=1, put=_Store().put)
        self.assertEqual(made, [])
        self.assertEqual(out, messages)

    @run
    async def test_no_result_of_the_pending_step_is_masked(self):
        # A parallel native step: two results answering one assistant's calls.
        messages = [{"role": "user", "content": "q"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "c1", "tool": "read_file", "args": {}}, {"id": "c2", "tool": "search_code", "args": {}}]},
                    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": BIG},
                    {"role": "tool", "tool_call_id": "c2", "name": "search_code", "content": BIG + "!"},
                    {"role": "user", "content": "take the next step"},
                    {"role": "assistant", "content": "thinking"},
                    {"role": "assistant", "content": "still thinking"}]
        out, made = await pressure.mask_old_results(messages, after_steps=1, put=_Store().put)
        self.assertEqual(made, [])
        self.assertFalse(_masked(out[2]))

    @run
    async def test_an_unanswered_error_is_kept(self):
        error = _marker("read_file", "error: no such file\n" + BIG)
        messages = [{"role": "user", "content": "task"},
                    {"role": "assistant", "content": "READ_FILE: x"}, error,
                    {"role": "assistant", "content": "LIST_DIR: ."}, _marker("list_dir", "error: denied\n" + BIG),
                    {"role": "assistant", "content": "SEARCH_CODE: y"}, _marker("search_code", "error: bad\n" + BIG)]
        failed = {pressure.digest(m["content"]) for m in messages[2::2]}
        out, made = await pressure.mask_old_results(messages, after_steps=1, put=_Store().put, failed=failed)
        self.assertEqual(made, [])
        # Without the failure marks the same history is masked.
        _out, made = await pressure.mask_old_results(messages, after_steps=1, put=_Store().put)
        self.assertEqual(len(made), 2)

    @run
    async def test_an_error_is_masked_once_retried(self):
        error = _marker("read_file", "error: no such file\n" + BIG)
        retry = _marker("read_file", "error: still no such file\n" + BIG)
        messages = [{"role": "user", "content": "task"},
                    {"role": "assistant", "content": "READ_FILE: x"}, error,
                    {"role": "assistant", "content": "READ_FILE: y"}, retry,
                    {"role": "assistant", "content": "READ_FILE: z"}, _marker("read_file", BIG)]
        failed = {pressure.digest(error["content"]), pressure.digest(retry["content"])}
        out, made = await pressure.mask_old_results(messages, after_steps=1, put=_Store().put, failed=failed)
        self.assertTrue(_masked(out[2]))
        self.assertTrue(_masked(out[4]))  # answered by the success after it

    @run
    async def test_an_error_is_masked_once_a_later_step_succeeds(self):
        error = _marker("read_file", "error: no such file\n" + BIG)
        messages = [{"role": "user", "content": "task"},
                    {"role": "assistant", "content": "READ_FILE: x"}, error,
                    {"role": "assistant", "content": "LIST_DIR: ."}, _marker("list_dir", BIG),
                    {"role": "assistant", "content": "LIST_DIR: .."}, _marker("list_dir", BIG + "2")]
        out, made = await pressure.mask_old_results(
            messages, after_steps=1, put=_Store().put, failed={pressure.digest(error["content"])})
        self.assertTrue(_masked(out[2]))

    @run
    async def test_short_results_are_left(self):
        messages = [{"role": "user", "content": "task"}]
        for i in range(4):
            messages += [{"role": "assistant", "content": "X"}, _marker("read_file", f"short {i}")]
        out, made = await pressure.mask_old_results(messages, after_steps=1, put=_Store().put)
        self.assertEqual(made, [])

    @run
    async def test_a_failed_blob_keeps_the_result(self):
        async def put(_data):
            raise OSError("disk")
        messages = _steps(4)
        out, made = await pressure.mask_old_results(messages, after_steps=1, put=put)
        self.assertEqual((out, made), (messages, []))

    @run
    async def test_deterministic_and_stable_across_turns(self):
        messages = _steps(4)
        a, _ = await pressure.mask_old_results(messages, after_steps=2, put=_Store().put)
        b, _ = await pressure.mask_old_results(messages, after_steps=2, put=_Store().put)
        self.assertEqual(json.dumps(a), json.dumps(b))
        # Masked again: nothing new; more steps later: the masked bytes hold.
        again, made = await pressure.mask_old_results(a, after_steps=2, put=_Store().put)
        self.assertEqual((again, made), (a, []))
        later = a + _steps(3)[1:]
        c, _ = await pressure.mask_old_results(later, after_steps=2, put=_Store().put)
        self.assertEqual(json.dumps(c[:len(a)][:5]), json.dumps(a[:5]))


class Gist(unittest.TestCase):
    def test_first_non_empty_line(self):
        self.assertEqual(pressure.gist(_marker("read_file", "\n\n  def  main():\n  pass")), "def main():")
        self.assertEqual(pressure.gist({"role": "tool", "content": "\n hello\nworld"}), "hello")

    def test_rows_for_tabular_output(self):
        table = "name | size\nalpha | 1\nbeta | 2\ngamma | 3"
        self.assertEqual(pressure.gist({"role": "tool", "content": table}), "4 rows: name | size")
        self.assertEqual(pressure.gist({"role": "tool", "content": "a\tb\nc\td\ne\tf"}), "3 rows: a b")
        self.assertEqual(pressure.gist({"role": "tool", "content": "a,b,c\n1,2,3\n4,5,6"}), "3 rows: a,b,c")

    def test_lines_for_a_list(self):
        self.assertEqual(pressure.gist(_marker("list_dir", "- a.py\n- b.py\n- c.py")), "3 lines: - a.py")
        self.assertEqual(pressure.gist({"role": "tool", "content": "1. one\n2. two\n3. three"}), "3 lines: 1. one")

    def test_bounded_and_never_empty(self):
        self.assertLessEqual(len(pressure.gist({"role": "tool", "content": "x" * 1000})), pressure.GIST_CHARS)
        self.assertEqual(pressure.gist({"role": "tool", "content": "  \n "}), "(empty)")


class ConfigKey(unittest.TestCase):
    def test_default_off_and_parsed(self):
        self.assertEqual(Config().mask_after_steps, 0)
        self.assertEqual(Config.from_mapping({"mask_after_steps": 2}).mask_after_steps, 2)
        self.assertEqual(Config.from_mapping({"mask_after_steps": -3}).mask_after_steps, 0)
        bad = Config.from_mapping({"mask_after_steps": "two"})
        self.assertEqual(bad.mask_after_steps, 0)
        self.assertTrue(any("mask_after_steps" in p for p in bad.problems))


class _Execution:
    """Approves every proposal; the first `fail` results fail."""

    def __init__(self, bus, *, fail: int = 0):
        self._bus, self._sub, self.n, self._fail = bus, None, 0, fail

    async def start(self):
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        self.n += 1
        ok = self.n > self._fail
        payload = {"action_id": message.payload["action_id"], "ok": ok, "output_ref": "",
                   "stdout_preview": f"read #{self.n}\n{BIG}", "duration_ms": 1, "side_effects": []}
        if not ok:
            payload.update(stdout_preview="", error=f"failed #{self.n}\n{BIG}", error_kind="transient")
        await self._bus.publish(message.caused(topics.ACTION_RESULT, payload, source="execution"))


class _Cognition:
    """Asks for a read every turn until `turns`, then answers. No pressure."""

    def __init__(self, bus, *, turns: int):
        self._bus, self._turns, self.calls, self._sub = bus, turns, [], None

    async def start(self):
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        self.calls.append(message)
        done = len(self.calls) > self._turns
        n = len(self.calls)
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": "all read" if done else "READ_FILE: notes.txt",
            "tool_calls": [] if done else [{"tool": "read_file", "args": {"path": f"notes{n}.txt"}}],
            "provider": "fake", "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False,
            "compaction": {"layers_applied": [], "tokens_before": 10, "tokens_after": 10,
                           "tokens_limit": 1_000_000}})


class InTheSession(unittest.TestCase):
    async def _run(self, *, turns=5, fail=0, **runner_kw):
        async with Harness() as h:
            cognition = _Cognition(h.client("cognition"), turns=turns)
            execution = _Execution(h.client("guardian"), fail=fail)
            await cognition.start()
            await execution.start()
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            session.budget.max_steps = turns + 5
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, **runner_kw)
            outcome = await asyncio.wait_for(runner.run(session, user_text="read everything"), timeout=60)
            await cognition.stop()
            await execution.stop()
            return session, cognition, runner, outcome

    @run
    async def test_masked_at_no_pressure_and_recalled_in_full(self):
        session, cognition, runner, outcome = await self._run(mask_after_steps=2)
        self.assertEqual(outcome.kind, "completed")
        stubs = [m for m in session.messages if _masked(m)]
        self.assertEqual(len(stubs), 3)  # 5 results; the last two are under 2 steps old
        self.assertIn(pressure.GIST_MARK, stubs[0]["content"])
        self.assertIn(pressure.RECALL_TOOL, cognition.calls[-1].payload["tools"])
        ref = stubs[0]["content"].split(f"call {pressure.RECALL_TOOL} with ", 1)[1].split(" to see", 1)[0]
        ok, text, _ = await runner._recall_result({"tool": pressure.RECALL_TOOL, "args": {"argument": ref}})
        self.assertTrue(ok)
        self.assertTrue(text.startswith("Result of read_file:\nread #1\n"))
        self.assertIn(BIG, text)
        # A think saw each result in full for two steps before it was masked.
        third = cognition.calls[2].payload["messages"]
        self.assertTrue(any("read #1" in str(m.get("content")) and not _masked(m) for m in third))

    @run
    async def test_a_failure_is_marked_by_the_text_the_model_saw(self):
        session, _c, _r, _o = await self._run(turns=3, fail=1)
        failed = [m for m in session.messages if pressure.digest(str(m.get("content"))) in session.failed_results]
        self.assertEqual(len(failed), 1)
        self.assertIn("failed #1", failed[0]["content"])

    @run
    async def test_off_is_byte_identical(self):
        _s, default, _r, _o = await self._run()
        _s, zero, _r, _o = await self._run(mask_after_steps=0)
        sent = [json.dumps(c.payload["messages"], sort_keys=True) for c in default.calls]
        self.assertEqual(len(sent), 6)
        self.assertEqual(sent, [json.dumps(c.payload["messages"], sort_keys=True) for c in zero.calls])
        self.assertFalse(any(pressure.STUB_MARK in s for s in sent))
        self.assertNotIn(pressure.RECALL_TOOL, default.calls[-1].payload["tools"])


if __name__ == "__main__":
    unittest.main()
