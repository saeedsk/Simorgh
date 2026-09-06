"""`BusClient` -- the public Bus every subsystem holds (docs/blueprint/
subsystems/01-bus.md sections 3.4, 5.1, 5.2). This is the ONLY module in
`simorgh.bus` other packages may import (boundary rule, 02 section 4).

One client per subsystem, `source` fixed at construction by the Kernel
so a subsystem cannot spoof another; all clients share one backend.
The publish path is: validate -> policy -> stopping check -> backpressure
-> trace -> enqueue. Request/reply rides on a per-client inbox
subscription (`_inbox.<source>.<uuid>`), replies routed point-to-point
by the backend. Handlers run through a dispatcher wrapper that turns a
message into ack/nack semantics (auto-ack on return, nack on exception,
explicit `bus.nack()` honored) and never lets an exception cross the
bus boundary.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message, validate
from simorgh.contracts.protocols import Ledger, Subscription
from simorgh.contracts.registry import error_reply_payload

from .api import BusBackend, BusClosed, BusPolicy, BusTimeout, Delivery, Handler, PolicyViolation, SubscriptionSpec
from .config import Config
from .metrics import Metrics
from .policy import AllowAllPolicy
from .router import INBOX_PREFIX
from .trace import TraceWriter

Clock = Callable[[], float]
Logger = Callable[[str, dict], None]


class BusClient:
    """Implements `contracts.protocols.Bus`."""

    def __init__(
        self,
        backend: BusBackend,
        *,
        source: str,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
        policy: BusPolicy | None = None,
        config: Config | None = None,
        trace: TraceWriter | None = None,
        metrics: Metrics | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._backend = backend
        self._source = source
        self._clock = clock or time.time
        self._policy = policy or AllowAllPolicy()
        self._config = config or Config()
        self._metrics = metrics if metrics is not None else Metrics()
        self._trace = trace if trace is not None else TraceWriter(
            ledger, sample=self._config.trace_sample, blob_threshold=self._config.trace_blob_threshold_bytes,
            enabled=self._config.trace_enabled,
        )
        self._ledger = ledger
        self._logger = logger or (lambda event, fields: None)
        self._state = "running"
        self._inbox_pattern = f"{INBOX_PREFIX}{source}.{uuid.uuid4().hex}"
        self._inbox: Subscription | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._deliveries: dict[str, Delivery] = {}  # message id -> current delivery (for ack/nack)
        self._closed = False
        backend.set_dead_letter_hook(self._on_dead_letter)

    # -- properties ------------------------------------------------------------------
    @property
    def source(self) -> str:
        return self._source

    @property
    def metrics(self) -> Metrics:
        return self._metrics

    @property
    def trace(self) -> TraceWriter:
        return self._trace

    @property
    def backend(self) -> BusBackend:
        return self._backend

    @property
    def state(self) -> str:
        return self._state

    # -- lifecycle -------------------------------------------------------------------
    async def start(self) -> None:
        await self._backend.start()
        await self._trace.start()

    async def stop(self, *, drain_seconds: float | None = None) -> None:
        self.set_state("stopping")
        # fail every pending request so callers never hang on a stopped bus
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(BusClosed("bus stopped"))
        self._pending.clear()
        await self._trace.stop()
        await self._backend.stop()
        self._closed = True

    def set_state(self, state: str) -> None:
        """running | paused | stopping (installed by the Kernel; Flow 5)."""
        self._state = state
        self._backend.set_state(state)

    # -- message construction sugar ----------------------------------------------------
    def new(
        self,
        type: str,
        payload: dict,
        *,
        caused_by: Message | None = None,
        partition_key: str | None = None,
        priority: int | None = None,
        ttl_seconds: float | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> Message:
        """Fill source/trace/causation for a message this subsystem emits.
        When `caused_by` is given and `partition_key` is left unset, the
        parent's own partition is inherited (`Message.caused`'s own
        `setdefault`) -- passing `partition_key=None` explicitly here would
        defeat that inheritance, so it is only forwarded when the caller
        actually named one.
        """
        if caused_by is not None:
            routing: dict[str, Any] = {
                "priority": priority, "ttl_seconds": ttl_seconds,
                "idempotency_key": idempotency_key, "clock": self._clock,
            }
            if partition_key is not None:
                routing["partition_key"] = partition_key
            return caused_by.caused(type, payload, source=self._source, **routing)
        return Message.new(
            type, source=self._source, payload=payload, trace_id=trace_id, partition_key=partition_key,
            priority=priority, ttl_seconds=ttl_seconds, idempotency_key=idempotency_key, clock=self._clock,
        )

    # -- publish -----------------------------------------------------------------------
    async def publish(self, message: Message) -> None:
        validate(message)
        self._policy.check_publish(message.source, message.type, message.payload)
        if self._state == "stopping" and not message.type.startswith("system."):
            raise BusClosed(f"bus is stopping; refusing {message.type}")
        if message.priority < self._config.priority_preempt_threshold:
            await self._backpressure(message)
        if self._trace.should_trace(message):
            ref = await self._trace.write_blob_body(message)
            self._trace.write(message if ref is None else message.with_(payload={"payload_ref": ref}))
        await self._backend.enqueue(message)
        self._metrics.inc("published", message.type)

    async def _backpressure(self, message: Message) -> None:
        groups = getattr(self._backend, "groups_for", None)
        targets = groups(message) if groups is not None else set()
        while targets:
            depths = [await self._backend.depth(g) for g in targets]
            if all(d < self._config.max_queue_depth for d in depths):
                return
            self._metrics.inc("backpressure_waits", message.type)
            await asyncio.sleep(0.005)

    # -- subscribe ---------------------------------------------------------------------
    async def subscribe(
        self, pattern: str, handler: Handler, *, group: str | None = None, durable: bool = False,
        max_inflight: int = 16, max_handler_seconds: float | None = None,
    ) -> Subscription:
        self._policy.check_subscribe(self._source, pattern)
        spec = SubscriptionSpec(pattern=pattern, group=group, durable=durable, source=self._source,
                                max_inflight=max_inflight, max_handler_seconds=max_handler_seconds)
        wrapped = self._wrap(handler, spec)
        return await self._backend.register(spec, wrapped)

    def _wrap(self, handler: Handler, spec: SubscriptionSpec) -> Handler:
        async def _run(message: Message) -> None:
            self._metrics.inc("delivered", message.type)
            try:
                await handler(message)
                self._metrics.inc("acked", message.type)
            except Exception as exc:  # noqa: BLE001 -- never re-raised into the publisher
                self._metrics.inc("nacked" if spec.group is not None else "dropped", message.type)
                self._logger("bus.handler_error", {"type": message.type, "source": self._source, "error": repr(exc)})
                raise  # the backend turns this into nack/drop semantics
        return _run

    # -- explicit ack/nack -----------------------------------------------------------------
    async def ack(self, message: Message) -> None:
        d = self._current_delivery(message)
        if d is not None:
            await self._backend.ack(d)

    async def nack(self, message: Message, *, retry_after: float | None = None) -> None:
        d = self._current_delivery(message)
        if d is not None:
            self._metrics.inc("explicit_nack", message.type)
            await self._backend.nack(d, retry_after=retry_after)

    def _current_delivery(self, message: Message) -> Delivery | None:
        # Backends track the in-flight delivery per message id; an ack/nack for a message that is
        # not currently being handled by this client is a no-op (events are auto-acked anyway).
        finder = getattr(self._backend, "_current_delivery_for", None)
        return finder(message) if finder is not None else None

    # -- request / reply ---------------------------------------------------------------------
    async def _ensure_inbox(self) -> None:
        if self._inbox is None:
            self._inbox = await self._backend.register(
                SubscriptionSpec(pattern=self._inbox_pattern, group=None, durable=False, source=self._source),
                self._on_reply,
            )

    async def _on_reply(self, message: Message) -> None:
        fut = self._pending.pop(message.correlation_id or "", None)
        if fut is None or fut.done():
            self._metrics.inc("late_replies", message.type)
            return
        fut.set_result(message)

    async def request(self, message: Message, *, timeout: float | None = None) -> Message:
        await self._ensure_inbox()
        timeout = self._config.request_default_timeout if timeout is None else timeout
        message = message.with_(reply_to=self._inbox_pattern)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[message.id] = fut
        started = time.perf_counter()
        await self.publish(message)
        try:
            reply = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(message.id, None)
            self._metrics.inc("request_timeouts", message.type)
            raise BusTimeout(f"no reply to {message.type} ({message.id}) within {timeout}s") from None
        self._metrics.observe_request_latency((time.perf_counter() - started) * 1000.0)
        return reply

    async def request_or_error(self, message: Message, *, timeout: float | None = None) -> Message:
        """`request()`, but a timeout comes back as the synthetic error reply
        of 03 section 9 instead of an exception."""
        try:
            return await self.request(message, timeout=timeout)
        except BusTimeout:
            return message.reply(
                topics.reply_type_for(message.type),
                error_reply_payload("timeout", f"no reply within {timeout or self._config.request_default_timeout}s", retryable=True),
                source="bus", clock=self._clock,
            )

    async def reply(self, request: Message, *, type: str, payload: dict) -> None:
        if not request.reply_to:
            raise ValueError(f"{request.type} ({request.id}) is not a request: no reply_to")
        reply = request.reply(type, payload, source=self._source, clock=self._clock).with_(reply_to=request.reply_to)
        await self.publish(reply)

    # -- dead letters ---------------------------------------------------------------------------
    async def _on_dead_letter(self, delivery: Delivery, reason: str, last_error: str) -> None:
        m = delivery.message
        self._metrics.inc("dead", m.type)
        if self._ledger is not None:
            try:
                await self._ledger.append(
                    f"dead:{m.type}",
                    Event(stream=f"dead:{m.type}", type=m.type, ts=self._clock(), trace_id=m.trace_id,
                          causation_id=m.id, idempotency_key=f"dead:{m.id}:{delivery.attempt}",
                          payload={"message": m.to_dict(), "reason": reason, "attempts": delivery.attempt,
                                   "last_error": last_error, "group": delivery.group}),
                )
            except Exception as exc:  # noqa: BLE001
                self._logger("bus.dead_letter_ledger_failed", {"type": m.type, "error": repr(exc)})
        await self._emit_health("degraded", f"dead-letter {m.type} after {delivery.attempt} attempt(s): {reason}")

    async def _emit_health(self, status: str, detail: str) -> None:
        try:
            await self.publish(Message.new(
                topics.SYSTEM_HEALTH, source="bus", clock=self._clock,
                payload={"subsystem": "bus", "status": status, "detail": detail},
            ))
        except Exception:  # noqa: BLE001 -- health reporting must never recurse into failure
            pass

    async def emit_metrics(self) -> dict:
        inflight = getattr(self._backend, "inflight", None)
        depths: dict[str, int] = {}
        for g in list((inflight() if inflight else {}).keys()):
            depths[g] = await self._backend.depth(g)
        body = self._metrics.snapshot(depths, inflight() if inflight else {})
        await self.publish(Message.new(topics.SYSTEM_METRICS, source="bus", payload=body, clock=self._clock))
        return body


__all__ = ["BusClient", "BusClosed", "BusTimeout", "PolicyViolation"]
