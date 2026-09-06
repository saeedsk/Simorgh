"""Ready-task selection and `task.available` emission (spec section 5.2,
5.7), plus the lease-expiry and stalled-scan background loops
(`system.tick.second`). Idempotent: the emission key is
`f"{task.id}:{task.updated_at}"`, which changes exactly when the task
becomes newly available (a fresh claim opportunity) and stays fixed
across repeated idle ticks noticing the same still-available task -- so
a re-emission during the same "generation" is a Ledger-deduped no-op,
while a genuinely new opportunity (after a lease expires or a blocked
retry) always gets a fresh key."""

from __future__ import annotations

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus, Clock

from .model import Task
from .store import TaskStore

DEFAULT_PRIORITY_WEIGHTS = {"human": 3, "reflection": 2, "curiosity": 1}


def select_ready(store: TaskStore, *, priority_weights: dict[str, int], limit: int = 1) -> list[Task]:
    """Highest `priority_weights[origin]` first, then oldest -- spec
    section 12 Q3's default (humans first)."""
    candidates = store.ready(limit=1000)
    candidates.sort(key=lambda t: (-priority_weights.get(t.origin, 0), t.created_at))
    return candidates[:limit]


class Scheduler:
    def __init__(self, store: TaskStore, bus: Bus, clock: Clock, *, source: str,
                 priority_weights: dict[str, int] | None = None, lease_seconds: float = 600.0) -> None:
        self._store = store
        self._bus = bus
        self._clock = clock
        self._source = source
        self._priority_weights = priority_weights or DEFAULT_PRIORITY_WEIGHTS
        self._lease_seconds = lease_seconds
        self.paused = False

    async def dispatch_ready(self) -> None:
        if self.paused:
            return
        for task in select_ready(self._store, priority_weights=self._priority_weights, limit=5):
            message = Message.new(
                topics.TASK_AVAILABLE, source=self._source,
                partition_key=f"task:{task.id}",
                idempotency_key=f"{task.id}:{task.updated_at}",
                payload={"task_id": task.id, "kind": task.kind, "lease_seconds": self._lease_seconds},
            )
            await self._bus.publish(message)

    async def scan_leases(self) -> None:
        now = self._clock.now()
        for task in list(self._store.index.tasks.values()):
            if task.lease is not None and task.lease.until <= now:
                await self._store.expire_lease(task.id)


__all__ = ["DEFAULT_PRIORITY_WEIGHTS", "Scheduler", "select_ready"]
