"""`compute_trajectory` reading a scripted `task:<id>` Ledger stream
(trajectory.py)."""

import unittest

from simorgh.contracts.envelope import Event
from simorgh.verification.trajectory import TrajectoryMetrics, compute_trajectory


class _FakeLedger:
    def __init__(self, events: dict[str, list[Event]]) -> None:
        self._events = events
        self.fail = False

    async def read(self, stream, *, from_seq: int = 0, limit=None):
        if self.fail:
            raise OSError("ledger down")
        return self._events.get(stream, [])


def _event(type_, payload, seq) -> Event:
    return Event(stream="task:t1", type=type_, ts=0.0, trace_id="t1", causation_id=None, payload=payload, seq=seq)


class TestComputeTrajectory(unittest.IsolatedAsyncioTestCase):
    async def test_no_task_id_is_unavailable(self):
        result = await compute_trajectory(_FakeLedger({}), None)
        self.assertEqual(result, TrajectoryMetrics(available=False))

    async def test_ledger_failure_degrades_to_unavailable(self):
        ledger = _FakeLedger({})
        ledger.fail = True
        result = await compute_trajectory(ledger, "t1")
        self.assertEqual(result, TrajectoryMetrics(available=False))

    async def test_counts_steps_denials_and_recoveries(self):
        events = [
            _event("task.step", {"ok": True, "summary": "wrote patch"}, 1),
            _event("action.denied", {}, 2),
            _event("action.result", {"ok": False}, 3),
            _event("action.result", {"ok": True}, 4),  # recovers from the prior failure
            _event("task.step", {"ok": True, "summary": "ran tests"}, 5),
        ]
        result = await compute_trajectory(_FakeLedger({"task:t1": events}), "t1")
        self.assertEqual(result.steps, 2)
        self.assertEqual(result.denied_actions, 1)
        self.assertEqual(result.recovered_errors, 1)
        self.assertTrue(result.available)

    async def test_wasted_step_without_action_id_counts_as_wasted(self):
        events = [_event("task.step", {"ok": False, "summary": "s"}, 1)]
        result = await compute_trajectory(_FakeLedger({"task:t1": events}), "t1")
        self.assertEqual(result.wasted, 1)

    async def test_repeated_summary_over_two_counts_as_wasted(self):
        events = [_event("task.step", {"ok": True, "summary": "retry same thing"}, i) for i in range(1, 4)]
        result = await compute_trajectory(_FakeLedger({"task:t1": events}), "t1")
        self.assertEqual(result.wasted, 1)  # one summary seen 3x > 2 -> +1


if __name__ == "__main__":
    unittest.main()
