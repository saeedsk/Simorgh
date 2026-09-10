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


#: How long a retry may be held behind never-attempted work before it
#: stops counting as a retry. Far longer than the window the
#: fewest-attempts rule was written for -- the GAIA run's retries were
#: re-claimed within seconds of being requeued, so nothing that fix
#: prevents happens inside half an hour -- and it turns "never" into a
#: bound. See `select_ready`.
STARVATION_GRACE_SECONDS = 1800.0


def select_ready(store: TaskStore, *, priority_weights: dict[str, int], limit: int = 1,
                 now: float | None = None,
                 starvation_grace_seconds: float = STARVATION_GRACE_SECONDS) -> list[Task]:
    """Highest `priority_weights[origin]` first, then fewest attempts,
    then oldest -- spec section 12 Q3's default (humans first).

    `attempts` sits in the middle of that key because oldest-first alone
    starves fresh work. A task that verification blocks comes straight
    back to the queue, and it was created before everything still
    waiting, so it wins the next dispatch -- and the one after that. A
    GAIA run on 2026-09-10 measured it: two tasks were re-claimed nine
    and ten times, took 68% of the run's steps and 71% of its wall
    clock, and four questions were never started at all. They sat on the
    queue for their full 600s timeout and scored zero without the system
    ever reading them.

    Fewest-attempts-first is the whole fix: a retry still runs, and it
    runs after the work that has never had a turn. Within one attempt
    count the order is unchanged, so nothing else about dispatch moves.

    ...except that "after the work that has never had a turn" is not a
    bound when fresh work keeps arriving, and the open question left
    behind was whether it starves a retry in the other direction.
    Measured 2026-09-10 with this exact function, one worker, a retry on
    the queue at t=0:

        arrival probability per service slot   how long the retry waited
        (20 tasks already queued)
        0.50                                   34-50 slots
        0.80                                   68-102 slots
        0.95                                   333-449 slots
        1.00 (saturated)                       NEVER, in 5,000 slots,
                                               every seed

    So yes: below saturation the retry waits for the queue to drain of
    never-attempted work, and at or above saturation it never runs at
    all. A slot is one real task, so the 0.95 row is already hours.

    `now` bounds it. A task that has been waiting longer than
    `starvation_grace_seconds` since it last changed state stops being
    sorted as a retry and competes on age like anything else -- it does
    NOT jump the queue, it just stops being sent to the back of it. With
    `now=None` (a caller that has no clock) the behaviour is exactly the
    old one.
    """
    candidates = store.ready(limit=1000)

    def attempts_key(task: Task) -> int:
        if now is not None and (now - task.updated_at) >= starvation_grace_seconds:
            return 0
        return task.attempts

    candidates.sort(key=lambda t: (-priority_weights.get(t.origin, 0), attempts_key(t), t.created_at))
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
        self._autonomous_paused = False
        #: task id -> the `{id}:{updated_at}` generation last offered.
        #: Bounded by the dispatch limit: see `dispatch_ready`.
        self._last_offer: dict[str, str] = {}

    @property
    def autonomous_paused(self) -> bool:
        return self._autonomous_paused

    @autonomous_paused.setter
    def autonomous_paused(self, value: bool) -> None:
        """Flipping the pause forgets what was offered.

        `dispatch_ready` offers each `{id}:{updated_at}` generation once,
        and a task held back by the pause never got its turn. `auto on`
        has to release the held work immediately rather than wait for
        each task's next transition, so the table is cleared on any
        change either way."""
        if value != self._autonomous_paused:
            self._last_offer.clear()
        self._autonomous_paused = bool(value)

    def _offerable(self, task: Task) -> bool:
        return not (self.autonomous_paused and task.origin in self._autonomous_origins)

    async def dispatch_ready(self) -> None:
        """Offer the ready work, and offer each generation of it ONCE.

        `idempotency_key` makes a repeat offer a no-op for the
        *consumer*; it does not stop the publish, and every publish
        writes a trace stream. Dispatching on the one-second tick (so a
        backlog is not left waiting for an idle tick that never comes)
        therefore re-published the same five offers every second: 350 of
        400 consecutive trace streams on the creator's live ledger were
        `task.available` for the same five task ids, ~5 new files a
        second, on a ledger that has been to 192k files before
        (live-caught 2026-09-10, minutes after the tick dispatch went
        in). The queue was not moving because the provider budget was
        exhausted, which is exactly when a re-offer is most useless and
        most frequent.

        So the key is checked HERE. A task is offered again only when
        something about it changed -- `updated_at` moves on every
        transition, including the lease expiry and the blocked retry
        that are the reasons to re-offer at all -- and the table is
        pruned to what is currently ready, so it cannot grow.
        """
        if self.paused:
            return
        offered: dict[str, str] = {}
        for task in select_ready(self._store, priority_weights=self._priority_weights, limit=5,
                                 now=self._clock.now()):
            if not self._offerable(task):
                continue
            key = f"{task.id}:{task.updated_at}"
            offered[task.id] = key
            if self._last_offer.get(task.id) == key:
                continue
            message = Message.new(
                topics.TASK_AVAILABLE, source=self._source,
                partition_key=f"task:{task.id}",
                idempotency_key=key,
                payload={"task_id": task.id, "kind": task.kind, "lease_seconds": self._lease_seconds},
            )
            await self._bus.publish(message)
        # Only what is ready right now: a task that has been claimed,
        # completed or dropped out of the top of the queue must be
        # offered afresh when it comes back.
        self._last_offer = offered

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


__all__ = ["DEFAULT_PRIORITY_WEIGHTS", "STARVATION_GRACE_SECONDS", "Scheduler", "select_ready"]
