"""Projects on crews (stage 18 item 4, docs/plan/stage-18-agent-crews.md).

With `[planning] project_crews = true`, a project's ready plan nodes are
not offered on the queue for the Worker to take one at a time. Each ready
node is started at once as a member of the crew rooted at the project
(`crew.spawn{context_id: <project id>, handle: <node's task id>,
plan_node: true}`), up to `project_crew_concurrency` per project, and the
node's bookkeeping reads the member's `crew.report`:

- `ok`                        -> `task.completed` (the node's summary);
- `partial` / `blocked`       -> the blocked-retry path, as a Worker's
                                 `task.blocked` would be;
- `failed` / `cancelled`      -> `task.failed{terminal}`: its dependents are
                                 blocked and the project rolls up, so a
                                 failed node never hangs the project.

The rollup, the DAG and the dependents' readiness are unchanged: they read
the node's status, and a node that waits for a dependency is not ready, so
it is not spawned until the dependency completed.

Planning still never runs a task. Orchestration runs the member, with the
node's agent, step cap, acceptance criteria and verifier, as a Worker
would have run the claimed task; Planning claims the node in its own name
(`crew:<project id>`) so no Worker is offered it meanwhile.

When nothing answers the spawn (no Orchestration, or one that refuses),
the node is released and that project goes back to the queue: the work is
never lost to the crew path.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

from .model import CLAIMED, IN_PROGRESS, TERMINAL_STATUSES, Task

#: The worker id a crew-run node is claimed under: `crew:<project id>`.
CLAIMER_PREFIX = "crew:"
#: The agents a node of each task kind runs as (`agents/<name>.md`).
AGENT_FOR_KIND = {"patch": "patch", "skill": "skill", "research": "research"}


def claimer(project_id: str) -> str:
    return f"{CLAIMER_PREFIX}{project_id}"


def outcome_of(report: dict) -> tuple[str, str, str]:
    """`(kind, reason, summary)` for a `crew.report`'s report, where kind is
    `completed`, `blocked` or `failed` -- the three outcomes a Worker
    reports for a claimed task."""
    status = str(report.get("status") or "failed")
    summary = str(report.get("summary") or "").strip()
    first = summary.split("\n", 1)[0].strip()
    if status == "ok":
        return "completed", "", summary
    if status in ("partial", "blocked"):
        # The member's report leads with the session's reason (`step budget
        # exhausted ...`, `verification failed ...`), which is what the
        # retry delay keys on.
        return "blocked", first or f"the crew member reported {status}", summary
    return "failed", first or f"the crew member reported {status}", summary


class ProjectCrews:
    """Which nodes run on crews, which are in flight, and the spawning.

    `brief_for(task)` returns `(brief, acceptance)` for a node; the Service
    owns the plan state it is read from.
    """

    def __init__(self, store, bus, clock, *, source: str, concurrency: int = 4,
                 spawn_timeout_s: float = 5.0, lease_seconds: float = 600.0,
                 brief_for: Callable[[Task], Awaitable[tuple[str, list[str]]]] | None = None,
                 logger=None) -> None:
        self._store = store
        self._bus = bus
        self._clock = clock
        self._source = source
        self.concurrency = max(1, int(concurrency))
        self._spawn_timeout_s = float(spawn_timeout_s)
        self._lease_seconds = float(lease_seconds)
        self._brief_for = brief_for
        self._logger = logger
        #: node task id -> project id, for every member this process started.
        self.inflight: dict[str, str] = {}
        #: Projects whose spawn nobody answered: their nodes use the queue.
        self.fallback: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._kicks: set[asyncio.Task] = set()

    # -- which nodes ---------------------------------------------------------------

    def project_of(self, task: Task) -> str:
        """The project a node belongs to, or "" when it is not a plan node."""
        parent = self._store.index.tasks.get(task.parent_id) if task.parent_id else None
        return parent.id if parent is not None and parent.kind == "project" else ""

    def holds(self, task: Task) -> bool:
        """True when this node runs on a crew, so the queue must not offer
        it and no Worker may claim it."""
        project = self.project_of(task)
        return bool(project) and project not in self.fallback

    def running(self, project_id: str) -> list[str]:
        return [t for t, p in self.inflight.items() if p == project_id]

    # -- spawning ------------------------------------------------------------------

    def kick(self) -> None:
        """Dispatch soon, off the caller's bus handler."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.dispatch())
        self._kicks.add(task)
        task.add_done_callback(self._kicks.discard)

    async def stop(self) -> None:
        for task in list(self._kicks):
            task.cancel()
        self._kicks.clear()

    async def dispatch(self) -> int:
        """Start every ready node of every crew-run project, up to the cap
        per project. Returns how many started."""
        async with self._lock:
            started = 0
            ready = [t for t in self._store.ready(limit=1000) if self.holds(t)]
            for task in sorted(ready, key=lambda t: t.created_at):
                project = self.project_of(task)
                if (task.id in self.inflight or project in self.fallback
                        or len(self.running(project)) >= self.concurrency):
                    # In flight already: its lease lapsed while the member
                    # runs, and its report is still to come.
                    continue
                if await self._start(task, project):
                    started += 1
            return started

    async def _start(self, task: Task, project: str) -> bool:
        claim = await self._store.claim(task.id, claimer(project), self._lease_seconds)
        if not claim.granted:
            return False
        self.inflight[task.id] = project
        brief, acceptance = (await self._brief_for(task)) if self._brief_for else (task.description, [])
        payload = {
            "agent": AGENT_FOR_KIND.get(task.kind, "research"), "brief": brief or task.description,
            "requester": "", "requester_channel": "planning", "report": "end",
            "context_id": project, "handle": task.id, "plan_node": True,
        }
        if task.subject:
            payload["subject"] = task.subject
        if acceptance:
            payload["acceptance"] = list(acceptance)
        if task.max_steps:
            payload["max_steps"] = int(task.max_steps)
        request = Message.new(topics.CREW_SPAWN, source=self._source, payload=payload,
                              partition_key=f"task:{task.id}", trace_id=task.id, clock=self._clock.now)
        try:
            reply = await self._bus.request_or_error(request, timeout=self._spawn_timeout_s)
            refused = reply.payload.get("ok") is False
            why = str((reply.payload.get("error") or {}).get("detail") or "") if refused else ""
        except Exception as exc:  # noqa: BLE001 -- a spawn that cannot be sent is a refused one
            refused, why = True, repr(exc)
        if not refused:
            return True
        # Nobody runs it: give the node back to the queue, and the project
        # with it, rather than leave it claimed by a crew that never started.
        self.inflight.pop(task.id, None)
        self.fallback[project] = why or "nothing answered crew.spawn"
        current = self._store.index.tasks.get(task.id)
        if current is not None and current.status in (CLAIMED, IN_PROGRESS):
            await self._store.expire_lease(task.id)
        if self._logger is not None:
            self._logger.warning("planning.project_crew_fallback", project_id=project, task_id=task.id,
                                 reason=self.fallback[project])
        return False

    async def refresh_leases(self, *, durable: bool) -> None:
        """A member's steps renew its node's lease (`task.step` names the
        node); a single step longer than the lease is renewed here."""
        for task_id in list(self.inflight):
            task = self._store.index.tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATUSES:
                self.inflight.pop(task_id, None)
            elif task.status in (CLAIMED, IN_PROGRESS):
                await self._store.refresh_lease(task_id, self._lease_seconds, durable=durable)

    def take(self, handle: str) -> str:
        """The project of the node `handle` names, forgetting it as in flight;
        "" when this process did not start it."""
        return self.inflight.pop(handle, "")


__all__ = ["AGENT_FOR_KIND", "CLAIMER_PREFIX", "ProjectCrews", "claimer", "outcome_of"]
