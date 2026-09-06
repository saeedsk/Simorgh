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
MODES = ("plan", "execute")
RISKS = ("low", "medium", "high")
ORIGINS = ("human", "curiosity", "reflection", "research", "project", "planner")


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

    def with_status(self, status: str, *, note: str = "", updated_at: float, attempt: bool = False) -> "Task":
        return replace(
            self, status=status, note=note or self.note, updated_at=updated_at,
            attempts=self.attempts + (1 if attempt else 0),
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
    CLAIMED: frozenset({IN_PROGRESS, AVAILABLE}),  # AVAILABLE = lease expired before task.started
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
