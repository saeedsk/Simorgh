"""Trajectory metrics from the Ledger (docs/blueprint/subsystems/
10-verification.md section 5.4): *how* a result was reached, not just
whether the final artifact looks right -- a result can be correct by
accident after a chain of bad decisions (harness-04, "Evaluate the
trajectory"). Reads `task:<id>` directly; reading the log is not a side
effect. Never fails a verdict alone except via `denied_actions`, which
signals the task kept proposing things it wasn't allowed to do.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrajectoryMetrics:
    steps: int = 0
    wasted: int = 0
    denied_actions: int = 0
    recovered_errors: int = 0
    available: bool = True

    def to_payload(self) -> dict:
        return {
            "steps": self.steps, "wasted": self.wasted,
            "denied_actions": self.denied_actions, "recovered_errors": self.recovered_errors,
            "available": self.available,
        }


async def compute_trajectory(ledger, task_id: str | None) -> TrajectoryMetrics:
    if task_id is None:
        return TrajectoryMetrics(available=False)
    try:
        events = await ledger.read(f"task:{task_id}")
    except Exception:  # noqa: BLE001 -- ledger unavailable is a degradation, not a crash
        return TrajectoryMetrics(available=False)

    steps = [e for e in events if e.type == "task.step"]
    seen_paths: dict[str, int] = {}
    wasted = 0
    denied = 0
    recovered = 0
    last_action_failed = False
    for e in events:
        if e.type == "task.step":
            payload = e.payload or {}
            if payload.get("ok") is False and not payload.get("action_id"):
                wasted += 1
            path = (payload.get("summary") or "")
            if path:
                seen_paths[path] = seen_paths.get(path, 0) + 1
        elif e.type == "action.denied":
            denied += 1
        elif e.type == "action.result":
            ok = (e.payload or {}).get("ok", True)
            if ok and last_action_failed:
                recovered += 1
            last_action_failed = not ok
    wasted += sum(1 for count in seen_paths.values() if count > 2)
    return TrajectoryMetrics(steps=len(steps), wasted=wasted, denied_actions=denied, recovered_errors=recovered)
