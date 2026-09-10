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
    #: When the description was too long to live inline in the Ledger,
    #: `description` is a preview and this is the blob holding all of
    #: it. `Worker` reads it back before prompting, so the model sees
    #: the whole brief; a listing shows the preview and says so.
    description_ref: str = ""
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
        #
        # A BLOCKED task keeps no lease either, for the same reason one
        # step further on: nobody is working on it. It is parked waiting
        # for `blocked_retry_delay_seconds`, and `_reconsider_blocked`
        # is the one thing that should bring it back -- counting the
        # attempt and giving up at `max_blocked_retries`. Leaving the
        # dead worker's lease on it let `Scheduler.scan_leases` expire
        # that lease instead, and `lease_expired` sets any non-terminal
        # status straight to `available`: the retry delay, the attempt
        # accounting and the give-up rule were all skipped, and the task
        # went back on the queue at once. Measured 2026-09-10 (60 tasks,
        # 4 workers, every task blocking, 2s leases): 221 claims and 211
        # `lease_expired` events for 60 tasks in 45 seconds, every task
        # re-run up to four times, in a run where the retry delay alone
        # should have allowed none at all.
        keeps_no_lease = status in TERMINAL_STATUSES or status == BLOCKED
        return replace(
            self, status=status, note=note or self.note, updated_at=updated_at,
            attempts=self.attempts + (1 if attempt else 0),
            lease=None if keeps_no_lease else self.lease,
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
    # COMPLETED is reachable from AVAILABLE for the same reason it is
    # reachable from CLAIMED below: the work really happened, and only
    # the bookkeeping lost a race. A worker whose lease expires mid-task
    # (renewals dropped, or one step longer than the whole lease) has
    # its task put back on the queue by `Scheduler.scan_leases` -- and
    # then finishes it and reports `task.completed` against a task that
    # is now `available`. That raised "illegal transition available ->
    # completed" inside the bus handler, where it was swallowed: the
    # finished result was thrown away, the task stayed on the queue, and
    # it was claimed and run again. Measured 2026-09-10 with renewals
    # suppressed (4 tasks, 2 workers, 3s of work under a 1s lease): 5
    # real runs, ZERO completions recorded, one task run three times and
    # one never run at all.
    # FAILED is deliberately NOT added here: a completion that lost this
    # race is real work worth keeping, while a failure that lost it
    # would only kill a task somebody has legitimately re-queued.
    AVAILABLE: frozenset({CLAIMED, PAUSED, BLOCKED, COMPLETED}),
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
