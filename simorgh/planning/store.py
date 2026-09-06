"""`TaskStore` over the Ledger (spec sections 4, 5.2): `TaskIndex` is the
projection every read (readiness, leases, dedupe) uses; every write goes
through `transition`/`claim`, which append to `task:<id>` and update the
index in the same call so a caller never reads stale state it just wrote.

CAS via `expected_seq` is what makes `claim` exactly-one-claimant even
with multiple Planning instances or concurrent handlers (spec section
5.7) -- the same guarantee v1 never needed because it was single-process
and single-threaded.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from typing import Iterable

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Clock, Ledger
from simorgh.ledger.client import ConflictError

from .model import (
    AVAILABLE,
    BLOCKED,
    CLAIMED,
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    PENDING,
    Lease,
    Scope,
    Task,
    is_legal_transition,
)

TASK_SNAPSHOT_EVERY = 500


@dataclass
class ClaimResult:
    granted: bool
    lease_until: float = 0.0
    task: Task | None = None
    reason: str = ""


class TaskIndex:
    """The in-memory projection: `task_id -> Task`, rebuilt by replaying
    every `task:<id>` stream. The only state kept outside it is derived
    (readiness, dedupe candidates) and always recomputed from here."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.cursors: dict[str, int] = {}

    def apply(self, stream: str, event: Event) -> None:
        task_id = stream.split(":", 1)[1]
        p = event.payload
        if event.type == "created":
            self.tasks[task_id] = Task(
                id=task_id, kind=p["kind"], description=p["description"], subject=p.get("subject"),
                mode=p.get("mode", "execute"), risk=p.get("risk", "low"), origin=p.get("origin", "human"),
                parent_id=p.get("parent_id"), depends_on=tuple(p.get("depends_on") or ()),
                status=p.get("status", PENDING), created_at=event.ts, updated_at=event.ts,
                priority=p.get("priority", 0), scope=Scope.from_payload(p.get("scope")),
                plan_id=p.get("plan_id"),
            )
        elif event.type == "status_changed":
            current = self.tasks.get(task_id)
            if current is not None:
                self.tasks[task_id] = current.with_status(
                    p["status"], note=p.get("note", ""), updated_at=event.ts, attempt=bool(p.get("attempt"))
                )
        elif event.type == "claimed":
            current = self.tasks.get(task_id)
            if current is not None:
                self.tasks[task_id] = replace(
                    current, status=CLAIMED, lease=Lease(p["worker_id"], p["until"]), updated_at=event.ts
                )
        elif event.type == "lease_refreshed":
            current = self.tasks.get(task_id)
            if current is not None and current.lease is not None:
                self.tasks[task_id] = replace(
                    current, lease=Lease(current.lease.worker_id, p["until"]), updated_at=event.ts
                )
        elif event.type == "lease_expired":
            current = self.tasks.get(task_id)
            if current is not None:
                self.tasks[task_id] = replace(current, lease=None, status=AVAILABLE, updated_at=event.ts)
        # "dependency_satisfied"/"dependency_failed"/"regrounded" are
        # informational -- the real transition they cause is always a
        # separate "status_changed"/"created" event, so nothing to apply.
        self.cursors[stream] = event.seq

    def snapshot_state(self) -> dict:
        return {
            "cursors": dict(self.cursors),
            "tasks": {tid: _task_to_dict(t) for tid, t in self.tasks.items()},
        }

    def load_snapshot_state(self, state: dict) -> None:
        self.cursors = dict(state.get("cursors") or {})
        self.tasks = {tid: _task_from_dict(tid, d) for tid, d in (state.get("tasks") or {}).items()}


def _task_to_dict(t: Task) -> dict:
    return {
        "kind": t.kind, "description": t.description, "subject": t.subject, "mode": t.mode, "risk": t.risk,
        "origin": t.origin, "parent_id": t.parent_id, "depends_on": list(t.depends_on), "status": t.status,
        "attempts": t.attempts, "note": t.note,
        "lease": {"worker_id": t.lease.worker_id, "until": t.lease.until} if t.lease else None,
        "created_at": t.created_at, "updated_at": t.updated_at, "priority": t.priority,
        "scope": t.scope.to_payload() if t.scope else None, "plan_id": t.plan_id,
    }


def _task_from_dict(task_id: str, d: dict) -> Task:
    lease = Lease(d["lease"]["worker_id"], d["lease"]["until"]) if d.get("lease") else None
    return Task(
        id=task_id, kind=d["kind"], description=d["description"], subject=d.get("subject"),
        mode=d.get("mode", "execute"), risk=d.get("risk", "low"), origin=d.get("origin", "human"),
        parent_id=d.get("parent_id"), depends_on=tuple(d.get("depends_on") or ()), status=d["status"],
        attempts=d.get("attempts", 0), note=d.get("note", ""), lease=lease,
        created_at=d.get("created_at", 0.0), updated_at=d.get("updated_at", 0.0),
        priority=d.get("priority", 0), scope=Scope.from_payload(d.get("scope")), plan_id=d.get("plan_id"),
    )


class TaskStore:
    """`api.TaskStore` implementation. `leader` gates only the background
    emitter loops (spec section 5.7) -- reads/writes here are always
    safe from multiple instances, since correctness rests on Ledger CAS,
    not on being the only reader."""

    def __init__(self, ledger: Ledger, clock: Clock, *, index_stream: str = "planning:index") -> None:
        self._ledger = ledger
        self._clock = clock
        self._index_stream = index_stream
        self.index = TaskIndex()
        self._events_since_snapshot = 0

    async def rebuild(self) -> None:
        loaded = await self._ledger.load_snapshot(self._index_stream)
        if loaded is not None:
            state, _at_seq = loaded
            self.index.load_snapshot_state(state)
        for stream in await self._ledger.streams("task:"):
            from_seq = self.index.cursors.get(stream, 0)
            for event in await self._ledger.read(stream, from_seq=from_seq):
                self.index.apply(stream, event)

    async def _maybe_snapshot(self) -> None:
        self._events_since_snapshot += 1
        if self._events_since_snapshot < TASK_SNAPSHOT_EVERY:
            return
        self._events_since_snapshot = 0
        await self._ledger.snapshot(self._index_stream, self.index.snapshot_state(), at_seq=0)

    async def create(
        self, *, kind: str, description: str, origin: str, subject: str | None = None,
        parent_id: str | None = None, depends_on: Iterable[str] = (), mode: str = "execute",
        risk: str = "low", scope: Scope | None = None, plan_id: str | None = None,
        priority: int = 0, initial_status: str = PENDING, task_id: str | None = None,
    ) -> Task:
        tid = task_id or uuid.uuid4().hex[:12]
        now = self._clock.now()
        stream = f"task:{tid}"
        payload = {
            "kind": kind, "description": description, "subject": subject, "mode": mode, "risk": risk,
            "origin": origin, "parent_id": parent_id, "depends_on": list(depends_on),
            "status": initial_status, "priority": priority,
            "scope": scope.to_payload() if scope else None, "plan_id": plan_id,
        }
        event = Event(stream=stream, type="created", ts=now, trace_id=tid, causation_id=None, payload=payload)
        seq = await self._ledger.append(stream, event)
        self.index.apply(stream, replace(event, seq=seq))
        await self._maybe_snapshot()
        return self.index.tasks[tid]

    async def get(self, task_id: str) -> Task | None:
        return self.index.tasks.get(task_id)

    async def transition(
        self, task_id: str, status: str, *, note: str = "", attempt: bool = False,
        expected_seq: int | None = None,
    ) -> Task:
        current = self.index.tasks.get(task_id)
        if current is None:
            raise KeyError(task_id)
        if current.status == status:
            return current  # duplicate delivery: a no-op, per spec section 8
        if not is_legal_transition(current.status, status):
            raise ValueError(f"{task_id}: illegal transition {current.status} -> {status}")
        stream = f"task:{task_id}"
        exp = expected_seq if expected_seq is not None else self.index.cursors.get(stream, 0)
        now = self._clock.now()
        event = Event(
            stream=stream, type="status_changed", ts=now, trace_id=task_id, causation_id=None,
            payload={"status": status, "note": note, "attempt": attempt},
        )
        seq = await self._ledger.append(stream, event, expected_seq=exp)
        self.index.apply(stream, replace(event, seq=seq))
        await self._maybe_snapshot()
        return self.index.tasks[task_id]

    async def claim(self, task_id: str, worker_id: str, lease_seconds: float) -> ClaimResult:
        task = self.index.tasks.get(task_id)
        if task is None:
            return ClaimResult(False, reason="unknown_task")
        if task.status != AVAILABLE:
            return ClaimResult(False, reason="not_available")
        stream = f"task:{task_id}"
        now = self._clock.now()
        until = now + lease_seconds
        event = Event(
            stream=stream, type="claimed", ts=now, trace_id=task_id, causation_id=None,
            payload={"worker_id": worker_id, "until": until},
        )
        try:
            seq = await self._ledger.append(stream, event, expected_seq=self.index.cursors.get(stream, 0))
        except ConflictError:
            for fresh in await self._ledger.read(stream, from_seq=self.index.cursors.get(stream, 0)):
                self.index.apply(stream, fresh)
            return ClaimResult(False, reason="leased_to_other")
        self.index.apply(stream, replace(event, seq=seq))
        await self._maybe_snapshot()
        return ClaimResult(True, lease_until=until, task=self.index.tasks[task_id])

    async def refresh_lease(self, task_id: str, lease_seconds: float) -> None:
        task = self.index.tasks.get(task_id)
        if task is None or task.lease is None:
            return
        stream = f"task:{task_id}"
        now = self._clock.now()
        event = Event(
            stream=stream, type="lease_refreshed", ts=now, trace_id=task_id, causation_id=None,
            payload={"until": now + lease_seconds},
        )
        seq = await self._ledger.append(stream, event, expected_seq=self.index.cursors.get(stream, 0))
        self.index.apply(stream, replace(event, seq=seq))

    async def expire_lease(self, task_id: str) -> None:
        stream = f"task:{task_id}"
        now = self._clock.now()
        event = Event(stream=stream, type="lease_expired", ts=now, trace_id=task_id, causation_id=None, payload={})
        seq = await self._ledger.append(stream, event, expected_seq=self.index.cursors.get(stream, 0))
        self.index.apply(stream, replace(event, seq=seq))

    async def record_dependency_event(self, task_id: str, *, satisfied_by: str | None, failed_by: str | None) -> None:
        stream = f"task:{task_id}"
        now = self._clock.now()
        etype = "dependency_satisfied" if satisfied_by else "dependency_failed"
        payload = {"by": satisfied_by or failed_by}
        event = Event(stream=stream, type=etype, ts=now, trace_id=task_id, causation_id=None, payload=payload)
        seq = await self._ledger.append(stream, event, expected_seq=self.index.cursors.get(stream, 0))
        self.index.apply(stream, replace(event, seq=seq))

    async def record_regrounded(self, task_id: str, *, still_valid: bool | None, reason: str) -> None:
        stream = f"task:{task_id}"
        now = self._clock.now()
        event = Event(
            stream=stream, type="regrounded", ts=now, trace_id=task_id, causation_id=None,
            payload={"still_valid": still_valid, "reason": reason},
        )
        seq = await self._ledger.append(stream, event, expected_seq=self.index.cursors.get(stream, 0))
        self.index.apply(stream, replace(event, seq=seq))

    def children(self, parent_id: str) -> list[Task]:
        return [t for t in self.index.tasks.values() if t.parent_id == parent_id]

    def all(self) -> list[Task]:
        return sorted(self.index.tasks.values(), key=lambda t: t.created_at)

    def unfinished(self) -> list[Task]:
        return [t for t in self.all() if t.status not in (COMPLETED, FAILED)]

    def ready(self, *, limit: int = 10) -> list[Task]:
        from . import dag

        out = []
        for t in self.unfinished():
            if t.status == AVAILABLE and dag.is_ready(t, self.index.tasks):
                out.append(t)
            if len(out) >= limit:
                break
        return out

    def descriptions(self) -> list[tuple[str, str]]:
        return [(t.id, t.description) for t in self.index.tasks.values()]


__all__ = ["TASK_SNAPSHOT_EVERY", "ClaimResult", "TaskIndex", "TaskStore"]
