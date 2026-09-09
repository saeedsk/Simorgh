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

from .config import Config
from .model import TERMINAL_STATUSES, Task
from .store import TaskStore

# The real default lives on `Config.priority_weights` -- this used to be
# a second copy of the same dict, and `PlanningService` never actually
# built its `Scheduler` from this one (it always passes
# `self.config.priority_weights`), so editing this constant alone
# changed nothing at runtime. An observer proved it on 2026-09-08:
# adding "benchmark" here left the live weight at 0 (the `.get(...,0)`
# fallback), BELOW curiosity's 1, the opposite of the intended ranking.
# Importing rather than duplicating means there is one number to get
# right.
DEFAULT_PRIORITY_WEIGHTS = Config().priority_weights


def select_ready(store: TaskStore, *, priority_weights: dict[str, int], limit: int = 1) -> list[Task]:
    """Highest `priority_weights[origin]` first, then oldest -- spec
    section 12 Q3's default (humans first)."""
    candidates = store.ready(limit=1000)
    candidates.sort(key=lambda t: (-priority_weights.get(t.origin, 0), t.created_at))
    return candidates[:limit]


class Scheduler:
    def __init__(self, store: TaskStore, bus: Bus, clock: Clock, *, source: str,
                 priority_weights: dict[str, int] | None = None, lease_seconds: float = 600.0,
                 autonomous_origins: tuple[str, ...] = ()) -> None:
        self._store = store
        self._bus = bus
        self._clock = clock
        self._source = source
        self._priority_weights = priority_weights or DEFAULT_PRIORITY_WEIGHTS
        self._lease_seconds = lease_seconds
        self._autonomous_origins = frozenset(autonomous_origins)
        self.paused = False
        # `auto off` is a `scope="autonomous"` pause: the system stays
        # RUNNING, so `paused` above stays False and every consumer that
        # keys off the whole-system state carries on. Live-caught
        # 2026-09-09 -- the creator typed `auto off` and watched
        # curiosity-origin patch tasks keep being offered, claimed and
        # run. Curiosity had stopped GENERATING candidates (it is the one
        # subsystem that reads `autonomous_paused`), but the backlog
        # already in the store kept executing, which is not what anyone
        # means by "off".
        self.autonomous_paused = False

    def _offerable(self, task: Task) -> bool:
        return not (self.autonomous_paused and task.origin in self._autonomous_origins)

    async def dispatch_ready(self) -> None:
        if self.paused:
            return
        for task in select_ready(self._store, priority_weights=self._priority_weights, limit=5):
            if not self._offerable(task):
                continue
            message = Message.new(
                topics.TASK_AVAILABLE, source=self._source,
                partition_key=f"task:{task.id}",
                idempotency_key=f"{task.id}:{task.updated_at}",
                payload={"task_id": task.id, "kind": task.kind, "lease_seconds": self._lease_seconds},
            )
            await self._bus.publish(message)

    async def scan_leases(self) -> None:
        """Return abandoned work to the queue. A lease that outlives its
        task's completion is not abandoned work -- expiring it used to
        reset the task to `available` and hand it straight back to a
        worker, which is how 101 tasks generated 1,305 claims."""
        now = self._clock.now()
        for task in list(self._store.index.tasks.values()):
            if task.status in TERMINAL_STATUSES:
                continue
            if task.lease is not None and task.lease.until <= now:
                await self._store.expire_lease(task.id)


__all__ = ["DEFAULT_PRIORITY_WEIGHTS", "Scheduler", "select_ready"]
