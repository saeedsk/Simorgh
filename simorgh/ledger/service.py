"""The Ledger as a `Subsystem` (02-ledger sections 3.1-3.2, 5.5): the
storage engine itself is substrate handed to every subsystem via
`Context.ledger`; this Service is the small message-facing wrapper that
runs record compaction on `system.tick.sleep`, publishes
`system.metrics`, and answers `health()` -- `down` when the backend
cannot persist, `degraded` when free disk is under 5 %.
"""

from __future__ import annotations

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
        self.compactions = 0
        self.last_report: dict | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        if not self.client.started:
            await self.client.start()
        self._subscription = await ctx.bus.subscribe(topics.SYSTEM_TICK_SLEEP, self._on_sleep)
        ctx.logger.info("ledger.started", backend=type(self.client.backend).__name__)

    async def stop(self) -> None:
        if self._subscription is not None:
            await self._subscription.unsubscribe()
            self._subscription = None
        await self.client.stop()

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
        now = self._ctx.clock.now() if self._ctx is not None else message.ts
        report = await run_compaction(self.client.backend, self.policy, now=now)
        self.compactions += 1
        self.last_report = report.as_payload()
        if report.streams_deleted or report.events_truncated:
            await self.client.append(
                COMPACTION_STREAM,
                Event(stream=COMPACTION_STREAM, type="ledger.compacted", ts=now, trace_id=message.trace_id,
                      causation_id=message.id, payload=report.as_payload()),
            )
        await self.publish_metrics(cause=message)

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
