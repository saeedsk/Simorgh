"""The Ledger as a `Subsystem` (02-ledger sections 3.1-3.2, 5.5): the
storage engine itself is substrate handed to every subsystem via
`Context.ledger`; this Service is the small message-facing wrapper that
runs record compaction on `system.tick.sleep`, publishes
`system.metrics`, and answers `health()` -- `down` when the backend
cannot persist, `degraded` when free disk is under 5 %.
"""

from __future__ import annotations

import asyncio

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message, validate
from simorgh.contracts.protocols import Context, Health
from simorgh.contracts.registry import get_spec

from .client import LedgerClient
from .compaction import RetentionPolicy, run_compaction
from .config import Config
from .streams import COMPACTION_STREAM

NAME = "ledger"
VERSION = "0.1.0"
LOW_DISK_FRACTION = 0.05


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (topics.SYSTEM_TICK_SLEEP,)
    produces: tuple[str, ...] = (topics.SYSTEM_HEALTH, topics.SYSTEM_METRICS)

    def __init__(self, client: LedgerClient, config: Config | None = None) -> None:
        self.client = client
        self.config = config or Config()
        self.policy = RetentionPolicy.parse(self.config.retention, keep_tail=self.config.keep_tail)
        self._ctx: Context | None = None
        self._subscription = None
        self._first_compaction: asyncio.Task | None = None
        self.compactions = 0
        self.last_report: dict | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        if not self.client.started:
            await self.client.start()
        self._subscription = await ctx.bus.subscribe(topics.SYSTEM_TICK_SLEEP, self._on_sleep)
        if self.config.compact_after_start_s > 0:
            self._first_compaction = asyncio.create_task(self._compact_after_start(), name="ledger-first-compaction")
        ctx.logger.info("ledger.started", backend=type(self.client.backend).__name__)

    async def stop(self) -> None:
        if self._subscription is not None:
            await self._subscription.unsubscribe()
            self._subscription = None
        if self._first_compaction is not None:
            self._first_compaction.cancel()
            try:
                await self._first_compaction
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise from a background pass
                pass
            self._first_compaction = None
        await self.client.stop()

    async def _compact_after_start(self) -> None:
        """One compaction pass shortly after boot.

        Live-caught 2026-09-07: retention already said `trace:` streams
        expire after 7 days, and 190,865 of them were still on disk (1.8GB)
        because the only thing that ran compaction was `system.tick.sleep`
        -- and the Kernel's sleep loop waits a full `sleep_every_s` (6h)
        before its *first* tick. A session that ends before then compacted
        nothing, so in practice compaction had never run at all.

        Deliberately not done inside `start()`: the pass walks every
        stream, and boot is not the place to wait for it. Failures are
        logged and dropped -- a ledger that cannot compact is still a
        ledger that works.
        """
        try:
            await asyncio.sleep(self.config.compact_after_start_s)
            await self._compact("start")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._ctx is not None:
                self._ctx.logger.warning("ledger.first_compaction_failed", error=repr(exc))

    async def health(self) -> Health:
        if not self.client.started:
            return Health.down("ledger not started")
        if self.client.last_error:
            return Health.down(self.client.last_error)
        try:
            stat = await self.client.backend.stat()
        except Exception as exc:  # noqa: BLE001
            return Health.down(f"stat failed: {exc}")
        free = stat.get("free_fraction")
        if isinstance(free, (int, float)) and free < LOW_DISK_FRACTION:
            return Health.degraded(f"free disk {free:.1%} < {LOW_DISK_FRACTION:.0%}")
        return Health.ok()

    # ---------------------------------------------------------------- handlers
    async def _on_sleep(self, message: Message) -> None:
        problems = get_spec(topics.SYSTEM_TICK_SLEEP).validate(message.payload)
        if problems or message.type != topics.SYSTEM_TICK_SLEEP:
            if self._ctx is not None:
                self._ctx.logger.warning("ledger.bad_tick", problems=problems, type=message.type)
            return  # a malformed tick has no side effects
        await self._compact("sleep_tick", cause=message)

    async def _compact(self, reason: str, *, cause: Message | None = None) -> None:
        """One retention pass, from either trigger (the 6-hourly sleep
        tick, or once shortly after start). Records what it removed."""
        now = self._ctx.clock.now() if self._ctx is not None else (cause.ts if cause is not None else 0.0)
        report = await run_compaction(self.client.backend, self.policy, now=now)
        self.compactions += 1
        self.last_report = report.as_payload()
        if report.streams_deleted or report.events_truncated:
            await self.client.append(
                COMPACTION_STREAM,
                Event(stream=COMPACTION_STREAM, type="ledger.compacted", ts=now,
                      trace_id=cause.trace_id if cause is not None else "",
                      causation_id=cause.id if cause is not None else None,
                      payload={**report.as_payload(), "reason": reason}),
            )
        await self.publish_metrics(cause=cause)

    async def publish_metrics(self, *, cause: Message | None = None) -> None:
        if self._ctx is None:
            return
        stat = await self.client.backend.stat()
        gauges = {k: v for k, v in stat.items() if v is not None}
        if self.last_report is not None:
            gauges["last_compaction"] = self.last_report
        payload = {"subsystem": NAME, "counters": dict(self.client.counters), "gauges": gauges}
        routing = {"trace_id": cause.trace_id, "causation_id": cause.id} if cause is not None else {}
        message = Message.new(topics.SYSTEM_METRICS, source=NAME, payload=payload, clock=self._ctx.clock.now, **routing)
        await self._ctx.bus.publish(validate(message))

    async def publish_health(self) -> None:
        if self._ctx is None:
            return
        health = await self.health()
        payload = {"subsystem": NAME, "status": health.status}
        if health.detail:
            payload["detail"] = health.detail
        await self._ctx.bus.publish(validate(Message.new(topics.SYSTEM_HEALTH, source=NAME, payload=payload,
                                                         clock=self._ctx.clock.now)))


__all__ = ["NAME", "Service", "VERSION"]
