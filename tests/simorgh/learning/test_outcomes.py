import unittest

from simorgh.contracts.envelope import Event, Message
from simorgh.ledger.factory import make_ledger
from simorgh.learning.competence import CompetenceTable
from simorgh.learning.config import Config
from simorgh.learning.outcomes import OutcomeRecorder


async def _make_ledger():
    ledger = make_ledger({"backend": "memory"})
    await ledger.start()
    return ledger


class TestOutcomeRecorder(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = await _make_ledger()
        self.competence = CompetenceTable()
        self.published: list[tuple[str, dict]] = []

        async def publish(type_, payload):
            self.published.append((type_, payload))

        self.recorder = OutcomeRecorder(ledger=self.ledger, competence=self.competence,
                                         config=Config(), publish=publish)

    async def _seed_task(self, task_id, kind="patch", subject="src/memory/x.py"):
        await self.ledger.append(f"task:{task_id}", Event(
            stream=f"task:{task_id}", type="created", ts=1.0, trace_id=task_id, causation_id=None,
            payload={"kind": kind, "subject": subject},
        ))

    async def test_completed_task_is_recorded_as_a_success(self):
        await self._seed_task("t1")
        msg = Message.new("task.completed", source="orchestration",
                          payload={"task_id": "t1", "result_summary": "ok", "artifacts": [],
                                    "verification_ref": None})
        await self.recorder.on_task_completed(msg)

        self.assertEqual(self.competence.success_rate("patch:src/memory"), (1 + 1) / (1 + 2))
        types = [t for t, _ in self.published]
        self.assertIn("learn.outcome.recorded", types)
        self.assertIn("learn.competence.updated", types)
        recorded = dict(self.published)["learn.outcome.recorded"]
        self.assertTrue(recorded["succeeded"])
        self.assertEqual(recorded["task_type"], "patch:src/memory")

    async def test_failed_task_is_recorded_as_a_failure(self):
        await self._seed_task("t2")
        msg = Message.new("task.failed", source="orchestration",
                          payload={"task_id": "t2", "reason": "boom", "terminal": True, "attempts": 3})
        await self.recorder.on_task_failed(msg)

        self.assertLess(self.competence.success_rate("patch:src/memory"), 0.5)

    async def test_blocked_task_uses_partial_negative_weight(self):
        await self._seed_task("t3")
        msg = Message.new("task.blocked", source="orchestration",
                          payload={"task_id": "t3", "reason": "waiting"})
        await self.recorder.on_task_blocked(msg)

        stats = self.competence.get("patch:src/memory")
        self.assertEqual(stats.n, 1)
        self.assertEqual(stats.successes_w, 0.0)

    async def test_task_type_falls_back_to_unknown_when_task_stream_is_missing(self):
        msg = Message.new("task.completed", source="orchestration",
                          payload={"task_id": "no-such-task", "result_summary": "ok", "artifacts": [],
                                    "verification_ref": None})
        await self.recorder.on_task_completed(msg)

        self.assertEqual(self.competence.samples("unknown"), 1)

    async def test_chat_task_with_no_subject_uses_bare_kind_as_task_type(self):
        await self._seed_task("t4", kind="chat", subject=None)
        msg = Message.new("task.completed", source="orchestration",
                          payload={"task_id": "t4", "result_summary": "ok", "artifacts": [],
                                    "verification_ref": None})
        await self.recorder.on_task_completed(msg)

        self.assertEqual(self.competence.samples("chat"), 1)

    async def test_verify_result_is_cached_and_joined_by_verification_ref(self):
        await self._seed_task("t5")
        self.recorder.cache_verify_result({
            "verification_id": "v1", "task_id": "t5", "verdict": "pass",
            "checklist": [], "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0},
            "mechanical": {},
        })
        msg = Message.new("task.completed", source="orchestration",
                          payload={"task_id": "t5", "result_summary": "ok", "artifacts": [],
                                    "verification_ref": "v1"})
        await self.recorder.on_task_completed(msg)

        recorded = dict(self.published)["learn.outcome.recorded"]
        self.assertEqual(recorded["verdict"], "pass")

    async def test_strategy_is_read_from_the_pipelines_own_stream(self):
        await self._seed_task("t6")
        await self.ledger.append("learn:patch:t6", Event(
            stream="learn:patch:t6", type="started", ts=1.0, trace_id="t6", causation_id=None,
            payload={"strategy": "claude_code_cli:patch:search_replace"},
        ))
        msg = Message.new("task.completed", source="orchestration",
                          payload={"task_id": "t6", "result_summary": "ok", "artifacts": [],
                                    "verification_ref": None})
        await self.recorder.on_task_completed(msg)

        recorded = dict(self.published)["learn.outcome.recorded"]
        self.assertEqual(recorded["strategy"], "claude_code_cli:patch:search_replace")

    async def test_duplicate_completion_is_not_double_counted(self):
        await self._seed_task("t7")
        msg = Message.new("task.completed", source="orchestration",
                          payload={"task_id": "t7", "result_summary": "ok", "artifacts": [],
                                    "verification_ref": None})
        await self.recorder.on_task_completed(msg)
        await self.recorder.on_task_completed(msg)  # redelivery (at-least-once)

        self.assertEqual(self.competence.samples("patch:src/memory"), 1)


if __name__ == "__main__":
    unittest.main()


class TheRecordedCostIsTheRealCostTestCase(TestOutcomeRecorder):
    """`cost_usd` and `duration_s` were hardcoded 0.0 at all three call
    sites, and both are REQUIRED fields of `learn.outcome.recorded`.

    So `CompetenceTable.cost_sum` and `dur_sum` could only ever be zero,
    and Learning's whole picture of what work costs was a fabricated
    number. An observer watched a real patch task spend $0.000589 over
    1.56 seconds and be recorded as $0.0 over 0.0s (2026-09-10).

    Nothing was missing: the recorder already read this same stream for
    the kind and the subject, with `limit=1`.
    """

    async def _seed_run(self, task_id: str) -> None:
        stream = f"task:{task_id}"
        await self.ledger.append(stream, Event(
            stream=stream, type="created", ts=100.0, trace_id=task_id, causation_id=None,
            payload={"kind": "patch", "subject": "simorgh/x.py"}))
        for n, cost in enumerate((0.000475, 0.000114), start=1):
            await self.ledger.append(stream, Event(
                stream=stream, type="task.step", ts=100.0 + n, trace_id=task_id, causation_id=None,
                payload={"task_id": task_id, "step_no": n, "ok": True, "cost_usd": cost}))
        await self.ledger.append(stream, Event(
            stream=stream, type="task.completed", ts=101.56, trace_id=task_id, causation_id=None,
            payload={"task_id": task_id, "result_summary": "done"}))

    async def _record(self, task_id: str) -> dict:
        await self.recorder.on_task_completed(Message.new(
            "task.completed", source="orchestration",
            payload={"task_id": task_id, "result_summary": "ok", "artifacts": [],
                     "verification_ref": None}))
        return dict(self.published)["learn.outcome.recorded"]

    async def test_the_cost_is_the_sum_of_what_the_steps_spent(self):
        await self._seed_run("c1")
        self.assertAlmostEqual((await self._record("c1"))["cost_usd"], 0.000589, places=6)

    async def test_the_duration_is_measured_from_created_to_finished(self):
        await self._seed_run("c2")
        self.assertAlmostEqual((await self._record("c2"))["duration_s"], 1.56, places=2)

    async def test_a_task_with_no_steps_records_zero_honestly(self):
        """Zero is the right answer when nothing was spent -- what was
        wrong was zero when something was."""
        await self._seed_task("c3")
        self.assertEqual((await self._record("c3"))["cost_usd"], 0.0)


class EachTurnOfAReusedSessionIsItsOwnOutcomeTestCase(TestOutcomeRecorder):
    """A chat turn's `task_id` IS its `session_id` (`Worker.run_percept_chat`
    takes `task_id=session_id`), and `POST /api/chat` documents sending
    "the same id every time" for a continuous conversation -- so every
    turn of such a conversation appends to ONE `task:<session_id>`
    stream.

    Both halves of `_task_facts` then read the whole conversation as if
    it were one run. An observer drove two real turns through a booted
    Kernel on session `sess-abc` (2026-09-10): turn 2 really cost
    $0.000629 in 0.49s and was published as $0.001256 over 2.943s (turn
    1 + turn 2, plus the idle time between them), and the ledger held
    ONE `learn:outcomes` record -- key `sess-abc:completed` -- because
    every turn's idempotency key is the same string, so turn 2 was
    dropped and `CompetenceTable` never saw it.
    """

    async def _seed_turn(self, task_id: str, *, at: float, cost: float, took: float) -> None:
        stream = f"task:{task_id}"
        await self.ledger.append(stream, Event(
            stream=stream, type="task.started", ts=at, trace_id=task_id, causation_id=None,
            payload={"task_id": task_id, "kind": "chat"}))
        await self.ledger.append(stream, Event(
            stream=stream, type="task.step", ts=at + took / 2, trace_id=task_id, causation_id=None,
            payload={"task_id": task_id, "step_no": 1, "ok": True, "cost_usd": cost}))
        await self.ledger.append(stream, Event(
            stream=stream, type="task.completed", ts=at + took, trace_id=task_id, causation_id=None,
            payload={"task_id": task_id, "result_summary": "ok"}))

    async def _complete(self, task_id: str) -> dict:
        await self.recorder.on_task_completed(Message.new(
            "task.completed", source="orchestration",
            payload={"task_id": task_id, "result_summary": "ok", "artifacts": [],
                     "verification_ref": None}))
        return dict(self.published)["learn.outcome.recorded"]

    async def test_the_second_turn_is_costed_as_itself_not_the_conversation(self):
        await self._seed_turn("sess-abc", at=100.0, cost=0.000627, took=0.485)
        await self._complete("sess-abc")
        await self._seed_turn("sess-abc", at=103.0, cost=0.000629, took=0.49)
        second = await self._complete("sess-abc")
        self.assertAlmostEqual(second["cost_usd"], 0.000629, places=6)
        self.assertAlmostEqual(second["duration_s"], 0.49, places=2)

    async def test_the_second_turn_is_recorded_at_all(self):
        await self._seed_turn("sess-abc", at=100.0, cost=0.000627, took=0.485)
        await self._complete("sess-abc")
        await self._seed_turn("sess-abc", at=103.0, cost=0.000629, took=0.49)
        await self._complete("sess-abc")
        stored = await self.ledger.read("learn:outcomes", limit=None)
        self.assertEqual(len(stored), 2, "every turn is an outcome; one key for all of them drops the rest")
        self.assertEqual(self.competence.samples("chat"), 2)

    async def test_a_redelivered_completion_is_still_only_one_outcome(self):
        await self._seed_turn("sess-abc", at=100.0, cost=0.000627, took=0.485)
        await self._complete("sess-abc")
        await self._complete("sess-abc")
        stored = await self.ledger.read("learn:outcomes", limit=None)
        self.assertEqual(len(stored), 1, "the same finished run must never be counted twice")
