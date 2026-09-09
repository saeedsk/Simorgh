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
from .tools import forget_registered, note_registered, register_tool_policy

# Execution's own stream name, duplicated rather than imported: a
# subsystem may not import another subsystem
# (tests/simorgh/test_module_boundaries.py).
_TOOLS_STREAM = "execution:tools"

from .worker import Worker

NAME = "orchestration"
VERSION = "0.1.0"


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.TASK_AVAILABLE, topics.SYSTEM_STATE_CHANGED,
        topics.ACTION_RESULT, topics.ACTION_DENIED, topics.ACTION_NEEDS_HUMAN, topics.VERIFY_RESULT,
        topics.PERCEPT_TEXT_RECEIVED, topics.TOOL_REGISTERED,
    )
    produces: tuple[str, ...] = (
        topics.TASK_STARTED, topics.TASK_STEP, topics.TASK_PAUSED, topics.TASK_COMPLETED,
        topics.TASK_FAILED, topics.TASK_BLOCKED, topics.TURN_COMPLETED,
        topics.ACTION_PROPOSED, topics.VERIFY_REQUESTED, topics.SYSTEM_METRICS,
    )

    def __init__(self, config: Config | None = None) -> None:
        self._config_from_caller = config
        self.config = config or Config()
        self._workers: list[Worker] = []
        self._ctx: Context | None = None
        self._percept_sub = None
        self._tool_sub = None
        self._next_worker = 0
        self._metrics_task: asyncio.Task | None = None
        # Chat sessions in flight, each run off the bus handler so the
        # handler timeout cannot cancel a long turn (see `_on_percept`).
        self._chat_tasks: set[asyncio.Task] = set()

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        # Every service is handed its own `[section]` from simorgh.toml
        # (`kernel/context.py` builds `ctx.config` for exactly this) --
        # this one never read it, so `[orchestration] workers` (and
        # everything else in the section) had zero effect in `single`
        # mode, the mode `sim.sh` actually runs (observer, 2026-09-08).
        # A config passed by the caller still wins, so a test that
        # constructs the service with one is unaffected. See
        # `config.py`'s docstring for which fields this actually changes.
        if self._config_from_caller is None and ctx.config:
            self.config = Config.from_mapping(dict(ctx.config))
        for i in range(max(1, self.config.workers)):
            # `local-multi` mode gives this Context a real per-process
            # `instance_id` (the operator's own `--id`, kernel/service.py's
            # `ctx_factory.build("orchestration", instance_id=self.worker_id)`)
            # and always runs exactly one worker per process -- use it
            # verbatim so `status`/leases/logs show the id the operator
            # actually gave this process, not a synthetic "orchestration-0"
            # indistinguishable from every other worker process (observer,
            # 2026-09-08). `single` mode never sets instance_id, so its
            # in-process workers keep their existing "orchestration-i" naming.
            worker_id = ctx.instance_id if ctx.instance_id else f"{ctx.name}-{i}"
            worker = Worker(ctx.bus, ctx.ledger, clock=ctx.clock.now if hasattr(ctx.clock, "now") else None,
                            worker_id=worker_id, think_timeout_s=self.config.think_timeout_s)
            await worker.start()
            self._workers.append(worker)
        self._percept_sub = await ctx.bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, self._on_percept)
        # Execution announces every tool it registers -- builtin, skill,
        # MCP, external adapters -- and the router's policy table (which
        # used to be hand-edited per tool, see tools.py's own MCP note)
        # learns them here, so a newly wired open-source tool is callable
        # without anyone editing orchestration.
        self._tool_sub = await ctx.bus.subscribe(topics.TOOL_REGISTERED, self._on_tool_registered)
        await self._replay_registrations(ctx)
        if self.config.metrics_interval_s > 0:
            self._metrics_task = asyncio.create_task(self._metrics_loop(), name="orchestration-metrics")
        ctx.logger.info("orchestration.started", workers=len(self._workers))

    async def _replay_registrations(self, ctx) -> None:
        """Catch up on the announcements made before we were listening.

        Execution registers its tools on boot layer 3 and this subsystem
        subscribes on layer 6, the last one. The bus does not replay, so
        every `tool.registered` from boot landed on nobody and
        `known_tools()` stayed empty for the life of the process.

        For builtins that was invisible, because a profile names them
        anyway. Skills are the one tool class that can ONLY arrive
        through this set, so a skill announced at boot was never offered
        to any session -- most of why a skill Sim wrote was unreachable
        by Sim afterwards (observer, 2026-09-08).

        Execution records each registration in its own ledger stream, so
        the durable record already existed and nothing read it. A
        failure here is not fatal: the subscription above still carries
        everything registered from now on.
        """
        try:
            events = await ctx.ledger.read(_TOOLS_STREAM)
        except Exception as exc:  # noqa: BLE001 -- no such stream on a fresh install is normal
            ctx.logger.info("orchestration.tool_replay_skipped", error=repr(exc))
            return
        names = [str((e.payload or {}).get("name") or "") for e in events]
        for name in names:
            if name:
                note_registered(name)
        if names:
            ctx.logger.info("orchestration.tools_replayed", count=len(names))

    async def _on_tool_registered(self, message) -> None:
        p = message.payload
        note_registered(p.get("name", ""))
        register_tool_policy(
            p.get("name", ""), reversibility=p.get("reversibility", "irreversible"),
            provider=p.get("provider", "builtin"),
            marker_arg_key=p.get("marker_arg_key"),
        )

    async def stop(self) -> None:
        if self._tool_sub is not None:
            await self._tool_sub.unsubscribe()
            self._tool_sub = None
        forget_registered()
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
        for task in list(self._chat_tasks):
            task.cancel()
        for task in list(self._chat_tasks):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise from a chat
                pass
        self._chat_tasks.clear()
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
        # Hand off, do not await. This used to run the whole chat session
        # inside the bus handler, and the memory backend kills a handler
        # at `handler_timeout_seconds` (300s) -- less than half of what a
        # 6-step chat with 120s think calls can legitimately take. When
        # that fired the session was cancelled mid-step with no
        # `turn.completed`, no failure, no notice: the human's prompt just
        # never came back. Found by a watched chat trial 2026-09-07.
        task = asyncio.create_task(
            worker.run_percept_chat(session_id, text), name=f"chat-{session_id[:8]}",
        )
        self._chat_tasks.add(task)
        task.add_done_callback(self._chat_tasks.discard)

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
