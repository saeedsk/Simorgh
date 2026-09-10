"""`Task`/`Step` data model and the status transition table (spec section 4).

Ported from `src/orchestrator/tasks.py`/`projects.py`, extended with
`mode`, `risk`, `origin`, `depends_on`, `lease`, `scope`, `plan_id`,
`priority` -- the fields the DAG, Plan Mode, and Guardian scope checks
need that v1's flat `Task` never had.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

# Statuses -- v1's five plus PENDING (the DAG "waiting on a dependency"
# state; v1 had no equivalent because it only ever honored creation
# order, never explicit edges).
PENDING = "pending"
AVAILABLE = "available"
CLAIMED = "claimed"
IN_PROGRESS = "in_progress"
PAUSED = "paused"
BLOCKED = "blocked"
COMPLETED = "completed"
FAILED = "failed"

TERMINAL_STATUSES = frozenset({COMPLETED, FAILED})

KINDS = ("chat", "patch", "skill", "research", "project")

#: Note prefix on a child parked because something it depends on failed
#: terminally. Written by `service.py::_propagate_failure` and read by
#: `rollup.py` to tell a child that is merely waiting from one that can
#: never run again -- two sides of one fact, so it lives in one place.
DEPENDENCY_FAILED_NOTE = "dependency_failed:"
MODES = ("plan", "execute")
RISKS = ("low", "medium", "high")
ORIGINS = ("human", "curiosity", "reflection", "research", "project", "planner", "benchmark")


@dataclass(frozen=True)
class Lease:
    worker_id: str
    until: float


@dataclass(frozen=True)
class Scope:
    paths: tuple[str, ...] = ()
    network: bool = False

    def to_payload(self) -> dict:
        return {"paths": list(self.paths), "network": self.network}

    @classmethod
    def from_payload(cls, data: dict | None) -> Optional["Scope"]:
        if not data:
            return None
        return cls(paths=tuple(data.get("paths") or ()), network=bool(data.get("network", False)))


@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    description: str
    subject: str | None = None
    mode: str = "execute"
    risk: str = "low"
    origin: str = "human"
    parent_id: str | None = None
    depends_on: tuple[str, ...] = ()
    status: str = PENDING
    attempts: int = 0
    note: str = ""
    lease: Lease | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    priority: int = 0
    scope: Scope | None = None
    plan_id: str | None = None
    # Steps one attempt may spend, when the task says; else the
    # profile's default (orchestration decides).
    max_steps: int | None = None

    def with_status(self, status: str, *, note: str = "", updated_at: float, attempt: bool = False) -> "Task":
        # A finished task keeps no lease. It used to: completion left the
        # worker's lease in place, `Scheduler.scan_leases` expired it
        # `lease_seconds` later like any other, and `lease_expired` reset
        # the status to `available` -- so every completed task came back
        # to life ten minutes after finishing and was worked again.
        # Live-caught 2026-09-07: one project task carried 16 rounds of
        # claimed -> started -> completed -> lease_expired -> claimed, and
        # 101 real tasks had produced 1,305 claims and 1,218 completions.
        return replace(
            self, status=status, note=note or self.note, updated_at=updated_at,
            attempts=self.attempts + (1 if attempt else 0),
            lease=None if status in TERMINAL_STATUSES else self.lease,
        )


@dataclass(frozen=True)
class Step:
    """One line of a decomposed plan -- port of the (kind, subject, description)
    triples `parse_project_steps` (v1 `projects.py`) returned, now with an
    id, explicit `depends_on`, and a `why` (spec section 5.1's "record of
    why each step is there", the input re-grounding needs)."""

    step_id: str
    kind: str  # patch | skill | research
    description: str
    depends_on: tuple[str, ...] = ()
    why: str = ""
    subject: str | None = None


# --- the legal-transition table (spec section 5.1) -----------------------------

_TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset({AVAILABLE, BLOCKED}),
    AVAILABLE: frozenset({CLAIMED, PAUSED, BLOCKED}),
    # Terminal states are reachable straight from CLAIMED: `task.started`
    # is a separate message, and if recording it is lost the work still
    # really happened. Refusing the completion left the task `claimed`
    # forever -- which is where 109 of the creator's tasks were sitting
    # on 2026-09-07, having genuinely finished. AVAILABLE = lease expired.
    CLAIMED: frozenset({IN_PROGRESS, AVAILABLE, COMPLETED, FAILED, BLOCKED}),
    IN_PROGRESS: frozenset({PAUSED, COMPLETED, FAILED, BLOCKED, AVAILABLE}),  # AVAILABLE = lease expired
    PAUSED: frozenset({AVAILABLE, CLAIMED}),
    BLOCKED: frozenset({AVAILABLE, FAILED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
}


def is_legal_transition(current: str, target: str) -> bool:
    if current == target:
        return True  # duplicate delivery is a no-op, not illegal (spec section 8)
    return target in _TRANSITIONS.get(current, frozenset())


__all__ = [
    "AVAILABLE", "BLOCKED", "CLAIMED", "COMPLETED", "FAILED", "IN_PROGRESS", "KINDS", "MODES",
    "ORIGINS", "PAUSED", "PENDING", "RISKS", "TERMINAL_STATUSES", "Lease", "Scope", "Step", "Task",
    "is_legal_transition",
]
