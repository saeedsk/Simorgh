"""The dispatch window is five OFFERABLE tasks, not the first five ready.

Live, 2026-09-22: nine of Sim's own tasks (two `project`, the rest
`reflection`) sat ready with `auto off`, so none could be offered. Every
SWE-bench case -- `origin="benchmark"`, exempt from the hold -- ranked
sixth behind them, was never offered to a worker, and was cancelled 30
minutes later by its own timeout. The whole run scored nothing.
"""

import unittest

from simorgh.planning.scheduler import Scheduler


class _Task:
    def __init__(self, id, origin, created_at):
        self.id, self.origin, self.created_at = id, origin, created_at
        self.kind, self.status, self.attempts, self.updated_at, self.priority = "patch", "available", 0, created_at, 0


class _Store:
    def __init__(self, tasks):
        self._tasks = tasks

    def ready(self, *, limit=10):
        return self._tasks[:limit]


class _Bus:
    source = "planning"

    def __init__(self):
        self.published = []

    async def publish(self, message):
        self.published.append(message)

    def new(self, *a, **k):  # pragma: no cover -- Scheduler uses Message.new
        raise AssertionError


class _Clock:
    def now(self):
        return 1_000_000.0


class TheWindow(unittest.IsolatedAsyncioTestCase):
    async def test_a_held_queue_does_not_hide_the_work_that_may_run(self):
        held = [_Task(f"auto-{i}", "reflection", 1000.0 + i) for i in range(5)]
        held += [_Task("proj", "project", 999.0)]
        runnable = _Task("bench", "benchmark", 2000.0)
        bus = _Bus()
        scheduler = Scheduler(_Store(held + [runnable]), bus, _Clock(), source="planning",
                              priority_weights={"project": 3, "benchmark": 2, "reflection": 2},
                              autonomous_origins=("curiosity", "reflection", "research", "project", "assistant"))
        scheduler.autonomous_paused = True
        await scheduler.dispatch_ready()
        offered = [m.payload["task_id"] for m in bus.published]
        self.assertEqual(offered, ["bench"], "the benchmark case must be offered past the held queue")


if __name__ == "__main__":
    unittest.main()
