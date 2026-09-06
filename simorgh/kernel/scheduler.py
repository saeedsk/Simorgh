"""Turns time and human activity into messages (docs/blueprint/
subsystems/03-kernel.md section 5.5). The Kernel does not know or care
whether there is work to do -- it only knows how long it has been idle
and when a durable timer is due; Curiosity/Planning/Guardian decide
everything about *acting* on a tick (section 7: "Ticks are unconditional
and dumb" -- this is the direct fix for v1's `AutonomyController` mixing
timing with policy, which needed three separate retunes,
`docs/EVOLUTION.md` milestones 56/72/80, precisely because the two were
tangled together).

`ActivityClock` is `src/orchestrator/autonomy.py`'s class ported onto
the injectable `Clock` protocol (monotonic in spirit -- see `touch()`)
instead of `time.time()`, so tests control it exactly (`FakeClock`).
`ScheduleView` + `parse_duration` port `src/orchestrator/reminders.py`,
made durable: a v1 reminder was a `threading.Timer` that a restart
simply forgot; here `system.schedule.add` is appended to the Ledger
before anything is armed, so a restart re-arms every outstanding
schedule from exactly where it left off (Flow 7, S4 in the spec).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message, validate
from simorgh.contracts.protocols import Bus, Clock, Ledger, Logger
from simorgh.ledger.api import Projection

SCHEDULE_STREAM = "schedule"

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(raw: str, *, max_seconds: float = 86400.0) -> float | None:
    """Parses "60", "60s", "1m", "2h", "1.5m" into seconds. `None` for
    anything unparseable, non-positive, or over `max_seconds` -- never
    raises (v1 `reminders.parse_duration`, verbatim behavior)."""
    match = _DURATION_RE.match(raw)
    if not match:
        return None
    seconds = float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    if seconds <= 0 or seconds > max_seconds:
        return None
    return seconds


class ActivityClock:
    """Tracks when a human last did something (`touch()`, called on
    `percept.text.received`); `idle_seconds()` is what the Scheduler
    compares against `idle_threshold_s`. Thread-/task-safe by virtue of
    holding only a float updated from the event loop thread."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._last_activity = clock.now()

    def touch(self) -> None:
        self._last_activity = self._clock.now()

    def idle_seconds(self) -> float:
        return self._clock.now() - self._last_activity


@dataclass
class _Schedule:
    schedule_id: str
    label: str
    fire_at: float
    every_seconds: float | None
    payload: dict
    requested_by: str
    cancelled: bool = False


class ScheduleView(Projection):
    """Durable timers, rebuilt from the `schedule` stream (section 4:
    `schedule.added` / `schedule.fired` / `schedule.cancelled`)."""

    stream_prefix = SCHEDULE_STREAM

    def __init__(self) -> None:
        super().__init__()
        self._schedules: dict[str, _Schedule] = {}

    def apply(self, event: Event) -> None:
        if event.type == "schedule.added":
            p = event.payload
            self._schedules[p["schedule_id"]] = _Schedule(
                schedule_id=p["schedule_id"], label=p["label"], fire_at=p["fire_at"],
                every_seconds=p.get("recurrence", {}).get("every_s") if p.get("recurrence") else None,
                payload=p.get("payload") or {}, requested_by=p.get("requested_by", ""),
            )
        elif event.type == "schedule.cancelled":
            sched = self._schedules.get(event.payload["schedule_id"])
            if sched is not None:
                sched.cancelled = True
        elif event.type == "schedule.fired":
            sched = self._schedules.get(event.payload["schedule_id"])
            if sched is not None and sched.every_seconds:
                sched.fire_at = event.payload["next_fire_at"]

    def state(self) -> dict:
        return {
            sid: {
                "label": s.label, "fire_at": s.fire_at, "every_seconds": s.every_seconds,
                "payload": s.payload, "requested_by": s.requested_by, "cancelled": s.cancelled,
            }
            for sid, s in self._schedules.items()
        }

    def load(self, state: dict) -> None:
        self._schedules = {
            sid: _Schedule(schedule_id=sid, **v) for sid, v in state.items()
        }

    def active(self) -> list[_Schedule]:
        return [s for s in self._schedules.values() if not s.cancelled]


class Scheduler:
    """Owns the three tick loops plus durable schedules. Started once the
    system reaches `running`; idle/sleep ticks (and schedule firing) stop
    while the state machine reports `paused`, but the second tick keeps
    running (a heartbeat even while paused -- section 3.1)."""

    def __init__(
        self,
        *,
        bus: Bus,
        ledger: Ledger,
        clock: Clock,
        logger: Logger,
        idle_threshold_s: float,
        idle_tick_cooldown_s: float,
        sleep_every_s: float,
        max_schedule_duration_s: float,
        is_running: "callable[[], bool]",
        source: str = "kernel",
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._clock = clock
        self._logger = logger
        self._idle_threshold_s = idle_threshold_s
        self._idle_tick_cooldown_s = idle_tick_cooldown_s
        self._sleep_every_s = sleep_every_s
        self._max_schedule_duration_s = max_schedule_duration_s
        self._is_running = is_running
        self._source = source
        self.activity = ActivityClock(clock)
        self._view = ScheduleView()
        self._tasks: list[asyncio.Task] = []
        self._armed: dict[str, asyncio.Task] = {}
        self._last_idle_tick: float = 0.0
        self._n = 0
        self._touch_sub = None
        self._schedule_add_sub = None
        self._schedule_cancel_sub = None

    async def start(self) -> None:
        # `materialize`/`rebuild` are `LedgerClient`-specific (not part of
        # the narrower `contracts.Ledger` protocol every subsystem is
        # typed against), but the Kernel always hands out a real
        # `LedgerClient`, so this duck-types fine in practice.
        await self._ledger.materialize(self._view, SCHEDULE_STREAM)  # type: ignore[attr-defined]
        self._touch_sub = await self._bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, self._on_percept)
        self._schedule_add_sub = await self._bus.subscribe(topics.SYSTEM_SCHEDULE_ADD, self._on_schedule_add)
        self._schedule_cancel_sub = await self._bus.subscribe(topics.SYSTEM_SCHEDULE_CANCEL, self._on_schedule_cancel)
        now = self._clock.now()
        for sched in self._view.active():
            self._arm(sched, now)
        self._tasks = [
            asyncio.create_task(self._second_loop(), name="kernel-tick-second"),
            asyncio.create_task(self._idle_loop(), name="kernel-tick-idle"),
            asyncio.create_task(self._sleep_loop(), name="kernel-tick-sleep"),
        ]

    async def stop(self) -> None:
        for sub in (self._touch_sub, self._schedule_add_sub, self._schedule_cancel_sub):
            if sub is not None:
                await sub.unsubscribe()
        for task in [*self._tasks, *self._armed.values()]:
            task.cancel()
        for task in [*self._tasks, *self._armed.values()]:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self._armed.clear()

    # -- handlers ---------------------------------------------------------
    async def _on_percept(self, message: Message) -> None:
        self.activity.touch()

    async def _on_schedule_add(self, message: Message) -> None:
        p = message.payload
        at = p.get("at")
        every = p.get("every_seconds")
        if (at is None) == (every is None):
            self._logger.warning("kernel.schedule.invalid", detail="exactly one of at/every_seconds required")
            return
        if every is not None and every > self._max_schedule_duration_s:
            self._logger.warning("kernel.schedule.invalid", detail="every_seconds exceeds max_duration_s")
            return
        fire_at = at if at is not None else self._clock.now() + every
        added = Message.new(
            topics.SYSTEM_SCHEDULE_ADDED, source=self._source, trace_id=message.trace_id, causation_id=message.id,
            payload={"schedule_id": p["schedule_id"], "at": at, "every_seconds": every,
                     "label": p["label"], "payload": p.get("payload")},
            clock=self._clock.now,
        )
        await self._ledger.append(SCHEDULE_STREAM, Event(
            stream=SCHEDULE_STREAM, type="schedule.added", ts=self._clock.now(), trace_id=message.trace_id,
            causation_id=message.id,
            payload={"schedule_id": p["schedule_id"], "fire_at": fire_at,
                     "recurrence": {"every_s": every} if every else None,
                     "label": p["label"], "payload": p.get("payload") or {}, "requested_by": message.source},
        ))
        self._view.applied_seq += 1
        sched = _Schedule(schedule_id=p["schedule_id"], label=p["label"], fire_at=fire_at,
                          every_seconds=every, payload=p.get("payload") or {}, requested_by=message.source)
        self._view._schedules[sched.schedule_id] = sched  # noqa: SLF001 -- same module, projection detail
        self._arm(sched, self._clock.now())
        await self._bus.publish(validate(added))

    async def _on_schedule_cancel(self, message: Message) -> None:
        sid = message.payload["schedule_id"]
        await self._ledger.append(SCHEDULE_STREAM, Event(
            stream=SCHEDULE_STREAM, type="schedule.cancelled", ts=self._clock.now(), trace_id=message.trace_id,
            causation_id=message.id, payload={"schedule_id": sid},
        ))
        sched = self._view._schedules.get(sid)  # noqa: SLF001
        if sched is not None:
            sched.cancelled = True
        task = self._armed.pop(sid, None)
        if task is not None:
            task.cancel()

    # -- arming -------------------------------------------------------
    def _arm(self, sched: _Schedule, now: float) -> None:
        delay = max(0.0, sched.fire_at - now)
        self._armed[sched.schedule_id] = asyncio.create_task(self._fire_after(sched, delay), name=f"sched-{sched.schedule_id}")

    async def _fire_after(self, sched: _Schedule, delay: float) -> None:
        await self._clock.sleep(delay)
        if sched.cancelled:
            return
        now = self._clock.now()
        next_fire_at = now + sched.every_seconds if sched.every_seconds else None
        await self._ledger.append(SCHEDULE_STREAM, Event(
            stream=SCHEDULE_STREAM, type="schedule.fired", ts=now, trace_id=str(uuid.uuid4()), causation_id=None,
            payload={"schedule_id": sched.schedule_id, "next_fire_at": next_fire_at},
        ))
        await self._bus.publish(Message.new(
            topics.PERCEPT_TIME_SCHEDULED, source=self._source,
            payload={"schedule_id": sched.schedule_id, "label": sched.label}, clock=self._clock.now,
        ))
        if next_fire_at is not None and not sched.cancelled:
            sched.fire_at = next_fire_at
            self._arm(sched, now)

    # -- tick loops -----------------------------------------------------
    async def _second_loop(self) -> None:
        while True:
            await self._clock.sleep(1.0)
            self._n += 1
            await self._bus.publish(Message.new(
                topics.SYSTEM_TICK_SECOND, source=self._source, payload={"n": self._n}, clock=self._clock.now,
            ))

    async def _idle_loop(self) -> None:
        while True:
            await self._clock.sleep(min(1.0, self._idle_tick_cooldown_s))
            if not self._is_running():
                continue
            idle = self.activity.idle_seconds()
            now = self._clock.now()
            if idle >= self._idle_threshold_s and (now - self._last_idle_tick) >= self._idle_tick_cooldown_s:
                self._last_idle_tick = now
                await self._bus.publish(Message.new(
                    topics.SYSTEM_TICK_IDLE, source=self._source,
                    payload={"idle_seconds": idle, "since_last_idle_tick": now - self._last_idle_tick},
                    clock=self._clock.now,
                ))

    async def _sleep_loop(self) -> None:
        while True:
            await self._clock.sleep(self._sleep_every_s)
            if not self._is_running():
                continue
            await self._bus.publish(Message.new(
                topics.SYSTEM_TICK_SLEEP, source=self._source,
                payload={"window_seconds": self._sleep_every_s}, clock=self._clock.now,
            ))


__all__ = ["ActivityClock", "ScheduleView", "Scheduler", "parse_duration"]
