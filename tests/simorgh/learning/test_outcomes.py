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
