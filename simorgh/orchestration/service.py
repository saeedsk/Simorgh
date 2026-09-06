"""Orchestration as a `Subsystem` (16 section 5): starts `config.workers`
`Worker` instances sharing the `workers` consumer group, so
`task.available` commands are load-balanced across them (03 section 5).
"""

from __future__ import annotations

from simorgh.contracts import topics
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
        topics.ACTION_PROPOSED, topics.VERIFY_REQUESTED,
    )

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self._workers: list[Worker] = []
        self._ctx: Context | None = None
        self._percept_sub = None
        self._next_worker = 0

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        for i in range(max(1, self.config.workers)):
            worker = Worker(ctx.bus, ctx.ledger, clock=ctx.clock.now if hasattr(ctx.clock, "now") else None,
                            worker_id=f"{ctx.name}-{i}")
            await worker.start()
            self._workers.append(worker)
        self._percept_sub = await ctx.bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, self._on_percept)
        ctx.logger.info("orchestration.started", workers=len(self._workers))

    async def stop(self) -> None:
        if self._percept_sub is not None:
            await self._percept_sub.unsubscribe()
            self._percept_sub = None
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

    async def health(self) -> Health:
        return Health.ok(f"{len(self._workers)} worker(s)")
