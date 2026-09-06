"""Orchestration as a `Subsystem` (16 section 5): starts `config.workers`
`Worker` instances sharing the `workers` consumer group, so
`task.available` commands are load-balanced across them (03 section 5).
"""

from __future__ import annotations

import asyncio

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from .config import Config
from .worker import Worker

NAME = "orchestration"
VERSION = "0.1.0"


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.TASK_AVAILABLE, topics.SYSTEM_STATE_CHANGED,
        topics.ACTION_RESULT, topics.ACTION_DENIED, topics.ACTION_NEEDS_HUMAN, topics.VERIFY_RESULT,
        topics.PERCEPT_TEXT_RECEIVED,
    )
    produces: tuple[str, ...] = (
        topics.TASK_STARTED, topics.TASK_STEP, topics.TASK_PAUSED, topics.TASK_COMPLETED,
        topics.TASK_FAILED, topics.TASK_BLOCKED, topics.TURN_COMPLETED,
        topics.ACTION_PROPOSED, topics.VERIFY_REQUESTED, topics.SYSTEM_METRICS,
    )

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self._workers: list[Worker] = []
        self._ctx: Context | None = None
        self._percept_sub = None
        self._next_worker = 0
        self._metrics_task: asyncio.Task | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        for i in range(max(1, self.config.workers)):
            worker = Worker(ctx.bus, ctx.ledger, clock=ctx.clock.now if hasattr(ctx.clock, "now") else None,
                            worker_id=f"{ctx.name}-{i}")
            await worker.start()
            self._workers.append(worker)
        self._percept_sub = await ctx.bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, self._on_percept)
        if self.config.metrics_interval_s > 0:
            self._metrics_task = asyncio.create_task(self._metrics_loop(), name="orchestration-metrics")
        ctx.logger.info("orchestration.started", workers=len(self._workers))

    async def stop(self) -> None:
        if self._percept_sub is not None:
            await self._percept_sub.unsubscribe()
            self._percept_sub = None
        if self._metrics_task is not None:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
            self._metrics_task = None
        for w in self._workers:
            await w.stop()
        self._workers.clear()

    async def _on_percept(self, message) -> None:
        text = message.payload.get("text", "")
        if not text or not self._workers:
            return
        session_id = message.payload.get("session_id") or message.id
        worker = self._workers[self._next_worker % len(self._workers)]
        self._next_worker += 1
        await worker.run_percept_chat(session_id, text)

    def _workers_snapshot(self) -> list[dict]:
        return [
            {"worker_id": w.worker_id, "task_id": w.current_task_id, "kind": w.current_kind}
            for w in self._workers
        ]

    async def _metrics_loop(self) -> None:
        # Event-driven (publish on every claim/finish) would be more
        # "real-time," but a Worker doesn't otherwise need bus access of
        # its own beyond what it already has -- a short periodic tick
        # (default 3s, `Config.metrics_interval_s`) keeps this Service
        # the sole publisher, matching how `simorgh.bus.service` already
        # reports its own gauges (01 section 3.2), and is fast enough for
        # a dashboard without adding a callback path into `Worker`.
        while True:
            await asyncio.sleep(self.config.metrics_interval_s)
            try:
                await self._publish_metrics()
            except Exception:  # noqa: BLE001 -- metrics reporting must never crash the loop
                pass

    async def _publish_metrics(self) -> None:
        workers = self._workers_snapshot()
        await self._ctx.bus.publish(Message.new(
            topics.SYSTEM_METRICS, source=self._ctx.source,
            payload={
                "subsystem": "orchestration", "counters": {},
                "gauges": {
                    "workers.total": len(self._workers),
                    "workers.busy": sum(1 for w in workers if w["task_id"] is not None),
                    "workers": workers,
                },
            },
        ))

    async def health(self) -> Health:
        busy = sum(1 for w in self._workers if w.current_task_id is not None)
        return Health.ok(f"{busy}/{len(self._workers)} worker(s) busy")
