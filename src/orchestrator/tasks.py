"""Persistent task/work-item store -- the durable backlog Sim's
self-improvement work lives in, so a plan survives a restart and isn't
just a topic string that vanished the moment 'propose'/'patch' returned.

Event-sourced onto the same MemoryStore everything else uses
(kind=TASK_EVENT_KIND): each change (create, status change) is a new,
append-only record referencing a task_id, and a Task's current state is
folded by replaying its own event history -- the same append-only
discipline every other kind in this codebase already follows (nothing
here is the first thing to mutate history in place). This is what makes
"on restart, find pending tasks and resume" possible at all: the backlog
itself is durable, not held only in a running process's memory.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from src.memory.long_term import MemoryStore

TASK_EVENT_KIND = "task_event"

PENDING = "pending"
IN_PROGRESS = "in_progress"
BLOCKED = "blocked"
DONE = "done"
FAILED = "failed"

TERMINAL_STATUSES = frozenset({DONE, FAILED})

# What pipeline handles a task -- kept as plain strings (not an enum) so
# a persisted record never breaks if this vocabulary grows.
SKILL_TASK = "skill"
PATCH_TASK = "patch"


@dataclass(frozen=True)
class Task:
    id: str
    description: str
    kind: str  # SKILL_TASK | PATCH_TASK
    subject: str | None  # target file path, for a PATCH_TASK
    status: str
    discovered_via: str  # "user" | "scan" | "planner" | "reflection"
    created_at: float
    updated_at: float
    parent_id: str | None = None
    attempts: int = 0
    note: str = ""


class TaskStore:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def add(
        self,
        description: str,
        kind: str,
        subject: str | None = None,
        discovered_via: str = "user",
        parent_id: str | None = None,
    ) -> Task:
        task_id = uuid.uuid4().hex[:12]
        now = time.time()
        self._store.remember(
            TASK_EVENT_KIND,
            description,
            task_id=task_id,
            event="created",
            task_kind=kind,
            subject=subject,
            status=PENDING,
            discovered_via=discovered_via,
            parent_id=parent_id,
        )
        return Task(
            id=task_id,
            description=description,
            kind=kind,
            subject=subject,
            status=PENDING,
            discovered_via=discovered_via,
            created_at=now,
            updated_at=now,
            parent_id=parent_id,
        )

    def update_status(self, task_id: str, status: str, note: str = "", attempt: bool = False) -> None:
        """`attempt=True` also increments the task's attempt counter --
        used for a genuine retry, not e.g. a plain "picked up for work"
        transition, so `attempts` reflects real tries at completing the
        task, useful for deciding when to give up and mark it blocked.
        """
        self._store.remember(
            TASK_EVENT_KIND,
            note or status,
            task_id=task_id,
            event="status_changed",
            status=status,
            note=note,
            attempt=attempt,
        )

    def get(self, task_id: str) -> Task | None:
        events = [r for r in self._store.query(kind=TASK_EVENT_KIND) if r.metadata.get("task_id") == task_id]
        if not events:
            return None
        return _fold(task_id, events)

    def all(self) -> list[Task]:
        by_id: dict[str, list] = {}
        for record in self._store.query(kind=TASK_EVENT_KIND):
            by_id.setdefault(record.metadata.get("task_id"), []).append(record)
        tasks = [_fold(task_id, events) for task_id, events in by_id.items()]
        return sorted(tasks, key=lambda t: t.created_at)

    def pending(self) -> list[Task]:
        return [t for t in self.all() if t.status == PENDING]

    def unfinished(self) -> list[Task]:
        """Everything not DONE or FAILED -- PENDING, IN_PROGRESS, or
        BLOCKED. The direct answer to "on restart, find pending task and
        resume": a task an earlier process left IN_PROGRESS (interrupted
        by a crash or relaunch mid-work) shows up here exactly like one
        that was never started.
        """
        return [t for t in self.all() if t.status not in TERMINAL_STATUSES]


def _fold(task_id: str, events: list) -> Task:
    events = sorted(events, key=lambda r: r.created_at)
    created = events[0]
    meta = created.metadata
    status = meta.get("status", PENDING)
    note = ""
    attempts = 0
    updated_at = created.created_at
    for record in events[1:]:
        rmeta = record.metadata
        if rmeta.get("event") == "status_changed":
            status = rmeta.get("status", status)
            note = rmeta.get("note", note)
            if rmeta.get("attempt"):
                attempts += 1
            updated_at = record.created_at
    return Task(
        id=task_id,
        description=created.content,
        kind=meta.get("task_kind", SKILL_TASK),
        subject=meta.get("subject"),
        status=status,
        discovered_via=meta.get("discovered_via", "user"),
        created_at=created.created_at,
        updated_at=updated_at,
        parent_id=meta.get("parent_id"),
        attempts=attempts,
        note=note,
    )
