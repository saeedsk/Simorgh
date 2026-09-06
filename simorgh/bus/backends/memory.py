"""In-process asyncio backend (docs/blueprint/subsystems/01-bus.md section
5.3) -- the guaranteed floor: zero configuration, zero dependencies,
every test and `--self-check` run on it.

One priority heap per competing group and one per broadcast
subscription; a dispatcher task per subscription pulls the highest
priority ready entry whose partition is unlocked and runs the handler
under an inflight semaphore. Nacks re-queue with a `retry_at`; lease
expiry (a handler that never returns) is bounded by a per-handler
timeout; exhausted retries dead-letter through the client's hook.
Nothing here is durable -- `durable=True` is accepted and ignored with a
debug note, by design (section 8: a process restart loses in-flight
memory-bus messages; `sqlite` exists for the cases where that matters).

Time comes from an injectable clock so tests drive TTL/retry with
`FakeClock`; the dispatcher wakes on every enqueue/ack/nack and on a
small real-time tick so a retry becomes ready without wall-clock sleeps.
"""

from __future__ import annotations

import asyncio
import heapq
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from simorgh.contracts.envelope import Message

from ..api import BusSubscription, DeadLetterHook, Delivery, Handler, SubscriptionSpec
from ..router import Registered, groups_for, route

Clock = Callable[[], float]


@dataclass(order=True)
class _Entry:
    sort_key: tuple  # (-priority, seq)
    message: Message = field(compare=False)
    attempt: int = field(compare=False, default=1)
    retry_at: float = field(compare=False, default=0.0)


@dataclass
class _Lane:
    """One queue: a competing group or a single broadcast subscription."""

    key: str  # group name or subscription id
    group: str | None
    heap: list[_Entry] = field(default_factory=list)
    locked_partitions: set[str] = field(default_factory=set)
    inflight: int = 0
    members: list[Registered] = field(default_factory=list)  # competing consumers (round-robin)
    rr: int = 0
    dedupe: OrderedDict = field(default_factory=OrderedDict)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


class InMemoryBackend:
    name = "memory"

    def __init__(
        self,
        *,
        clock: Clock,
        max_deliveries: int = 5,
        handler_timeout: float = 300.0,
        dedupe_window: int = 5000,
        tick_seconds: float = 0.005,
        on_expired: Callable[[Message], None] | None = None,
        on_handler_error: Callable[[Message, BaseException], None] | None = None,
    ) -> None:
        self._clock = clock
        self._max_deliveries = max_deliveries
        self._handler_timeout = handler_timeout
        self._dedupe_window = dedupe_window
        self._tick = tick_seconds
        self._on_expired = on_expired
        self._on_handler_error = on_handler_error
        self._registered: list[Registered] = []
        self._lanes: dict[str, _Lane] = {}
        self._seq = 0
        self._state = "running"
        self._dead_hook: DeadLetterHook | None = None
        self._ticker: asyncio.Task | None = None
        self._inflight_tasks: set[asyncio.Task] = set()
        self._active: dict[str, Delivery] = {}  # message id -> in-flight delivery
        self._explicit: dict[str, tuple[str, float | None]] = {}  # delivery id -> (ack|nack, retry_after)

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        if self._ticker is None:
            self._ticker = asyncio.create_task(self._tick_loop(), name="bus-memory-ticker")

    async def stop(self) -> None:
        self._state = "stopping"
        for lane in self._lanes.values():
            if lane.task is not None:
                lane.task.cancel()
        if self._ticker is not None:
            self._ticker.cancel()
        for t in list(self._inflight_tasks):
            t.cancel()
        await asyncio.gather(
            *[lane.task for lane in self._lanes.values() if lane.task is not None],
            *([self._ticker] if self._ticker else []),
            *self._inflight_tasks,
            return_exceptions=True,
        )
        self._ticker = None

    def set_state(self, state: str) -> None:
        self._state = state
        self._wake_all()

    def set_dead_letter_hook(self, hook: DeadLetterHook | None) -> None:
        self._dead_hook = hook

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick)
            self._wake_all()

    def _wake_all(self) -> None:
        for lane in self._lanes.values():
            lane.wake.set()

    # -- registration ----------------------------------------------------------
    async def register(self, spec: SubscriptionSpec, handler: Handler) -> BusSubscription:
        reg = Registered(id=str(uuid.uuid4()), spec=spec, handler=handler)
        self._registered.append(reg)
        lane_key = spec.group if spec.group is not None else reg.id
        lane = self._lanes.get(lane_key)
        if lane is None:
            lane = _Lane(key=lane_key, group=spec.group)
            self._lanes[lane_key] = lane
            lane.task = asyncio.create_task(self._dispatch(lane, spec), name=f"bus-memory-{lane_key}")
        lane.members.append(reg)

        async def _unsub() -> None:
            if reg in self._registered:
                self._registered.remove(reg)
            lane.members = [m for m in lane.members if m is not reg]
            if not lane.members and lane.task is not None:
                lane.task.cancel()
                self._lanes.pop(lane_key, None)

        return BusSubscription(pattern=spec.pattern, id=reg.id, _unsubscribe=_unsub)

    # -- enqueue -----------------------------------------------------------------
    async def enqueue(self, message: Message) -> None:
        self._seq += 1
        for reg in route(message, self._registered):
            lane_key = reg.spec.group if reg.spec.group is not None else reg.id
            lane = self._lanes.get(lane_key)
            if lane is None:
                continue
            heapq.heappush(lane.heap, _Entry((-message.priority, self._seq), message))
            lane.wake.set()

    async def depth(self, group: str) -> int:
        lane = self._lanes.get(group)
        return len(lane.heap) if lane else 0

    def inflight(self) -> dict[str, int]:
        return {k: l.inflight for k, l in self._lanes.items() if l.group is not None}

    def groups_for(self, message: Message) -> set[str]:
        return groups_for(message, self._registered)

    # -- dispatch ------------------------------------------------------------------
    def _ready(self, lane: _Lane, now: float) -> _Entry | None:
        """Pop the best entry that is ready: not retry-pending, partition
        unlocked, not paused-out. Entries that are not ready stay."""
        skipped: list[_Entry] = []
        found: _Entry | None = None
        while lane.heap:
            entry = heapq.heappop(lane.heap)
            m = entry.message
            if entry.retry_at > now:
                skipped.append(entry)
                continue
            if self._state == "paused" and lane.group is not None and not m.type.startswith("system."):
                skipped.append(entry)
                continue
            if m.partition_key is not None and m.partition_key in lane.locked_partitions:
                skipped.append(entry)
                continue
            found = entry
            break
        for entry in skipped:
            heapq.heappush(lane.heap, entry)
        return found

    async def _dispatch(self, lane: _Lane, first_spec: SubscriptionSpec) -> None:
        max_inflight = first_spec.max_inflight
        while True:
            await lane.wake.wait()
            lane.wake.clear()
            if self._state == "stopping":
                return
            while lane.inflight < max_inflight:
                now = self._clock()
                entry = self._ready(lane, now)
                if entry is None:
                    break
                m = entry.message
                if m.ttl_seconds is not None and now > m.ts + m.ttl_seconds:
                    if self._on_expired:
                        self._on_expired(m)
                    continue
                if m.id in lane.dedupe:
                    continue  # already acked once; suppress the duplicate
                member = self._pick_member(lane)
                if member is None:
                    heapq.heappush(lane.heap, entry)
                    break
                if m.partition_key is not None:
                    lane.locked_partitions.add(m.partition_key)
                lane.inflight += 1
                delivery = Delivery(
                    message=m, attempt=entry.attempt, lease_until=now + self._handler_timeout,
                    group=lane.group, subscription_id=member.id,
                )
                task = asyncio.create_task(self._run(lane, member, delivery, entry))
                self._inflight_tasks.add(task)
                task.add_done_callback(self._inflight_tasks.discard)

    def _pick_member(self, lane: _Lane) -> Registered | None:
        if not lane.members:
            return None
        member = lane.members[lane.rr % len(lane.members)]
        lane.rr += 1
        return member

    async def _run(self, lane: _Lane, member: Registered, delivery: Delivery, entry: _Entry) -> None:
        m = delivery.message
        timeout = member.spec.max_handler_seconds or self._handler_timeout
        outcome = "ack"
        retry_after: float | None = None
        error: BaseException | None = None
        delivery.delivery_id = f"{lane.key}:{m.id}:{entry.attempt}"
        self._active[m.id] = delivery
        try:
            await asyncio.wait_for(member.handler(m), timeout=timeout)
            explicit = self._explicit.pop(delivery.delivery_id, None)
            if explicit is not None:
                outcome, retry_after = explicit
        except asyncio.CancelledError:
            self._release(lane, m)
            raise
        except BaseException as exc:  # noqa: BLE001 -- a handler must never take the bus down
            error = exc
            outcome = "nack"
            self._explicit.pop(delivery.delivery_id, None)
            if self._on_handler_error:
                self._on_handler_error(m, exc)
        finally:
            lane.inflight -= 1
            if self._active.get(m.id) is delivery:
                del self._active[m.id]
        if outcome == "ack" or lane.group is None:
            # broadcast: a failing handler's delivery is dropped (events are facts; the ledger has them)
            self._remember_acked(lane, m.id)
            self._release(lane, m)
            return
        await self._requeue_or_dead(lane, entry, retry_after, error)
        self._release(lane, m)

    def _release(self, lane: _Lane, m: Message) -> None:
        if m.partition_key is not None:
            lane.locked_partitions.discard(m.partition_key)
        lane.wake.set()

    def _remember_acked(self, lane: _Lane, message_id: str) -> None:
        lane.dedupe[message_id] = True
        while len(lane.dedupe) > self._dedupe_window:
            lane.dedupe.popitem(last=False)

    async def _requeue_or_dead(self, lane: _Lane, entry: _Entry, retry_after: float | None, error: BaseException | None) -> None:
        if entry.attempt >= self._max_deliveries:
            if self._dead_hook is not None:
                delivery = Delivery(message=entry.message, attempt=entry.attempt, lease_until=0.0, group=lane.group)
                await self._dead_hook(delivery, "max_deliveries", repr(error) if error else "nack")
            return
        backoff = retry_after if retry_after is not None else min(60.0, 2.0 ** (entry.attempt - 1))
        entry.attempt += 1
        entry.retry_at = self._clock() + backoff
        heapq.heappush(lane.heap, entry)

    # -- explicit ack/nack from handlers ------------------------------------------------
    def _current_delivery_for(self, message: Message) -> Delivery | None:
        return self._active.get(message.id)

    async def ack(self, delivery: Delivery) -> None:
        self._explicit[delivery.delivery_id] = ("ack", None)

    async def nack(self, delivery: Delivery, *, retry_after: float | None) -> None:
        self._explicit[delivery.delivery_id] = ("nack", retry_after)


__all__ = ["InMemoryBackend"]
