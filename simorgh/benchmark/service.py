"""The benchmark subsystem.

Answers four requests on the bus: list the suites, start a run, read the
history, read one run's detail. A run happens in a background task and
narrates its progress on `benchmark.progress`, because a GAIA run is
tens of minutes and the CLI should be able to say where it is -- the
same lesson the loader's silent gate taught earlier the same day.

Only one run at a time, on purpose. Two concurrent runs would share one
Worker and one budget, and each would measure the other's contention.
"""

from __future__ import annotations

import asyncio
import time

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health
from simorgh.contracts.registry import error_reply_payload

from . import datasets as datasets_mod
from .api import RunRecord
from .config import Config
from .runner import Runner
from .store import RunStore

VERSION = "0.1.0"

_CONSUMES = (
    topics.BENCHMARK_RUN_REQUEST, topics.BENCHMARK_HISTORY_REQUEST,
    topics.BENCHMARK_SUITES_REQUEST, topics.BENCHMARK_LOAD_REQUEST, topics.BENCHMARK_STOP_REQUEST,
    topics.COGNITION_PROVIDER_STATUS,
)
_PRODUCES = (
    topics.BENCHMARK_RUN_REPLY, topics.BENCHMARK_HISTORY_REPLY, topics.BENCHMARK_SUITES_REPLY,
    topics.BENCHMARK_LOAD_REPLY, topics.BENCHMARK_STOP_REPLY,
    topics.BENCHMARK_PROGRESS, topics.BENCHMARK_RUN_COMPLETED, topics.TASK_CREATE, topics.UI_NOTICE,
)


class Service:
    name = "benchmark"
    version = VERSION
    consumes = _CONSUMES
    produces = _PRODUCES

    def __init__(self, *, config: Config | None = None) -> None:
        self._config_from_caller = config
        self._config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        self._store: RunStore | None = None
        self._task: asyncio.Task | None = None
        self._running: dict = {}
        # Which model answered, for the per-model history. Cognition
        # broadcasts this at startup and on every provider change.
        self._model = "unknown"

    # -- Subsystem protocol --------------------------------------------
    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        if self._config_from_caller is None and ctx.config:
            self._config = Config.from_mapping(dict(ctx.config))
        self._store = RunStore(ctx.ledger, clock=ctx.clock.now)
        handlers = {
            topics.BENCHMARK_SUITES_REQUEST: self._on_suites,
            topics.BENCHMARK_RUN_REQUEST: self._on_run,
            topics.BENCHMARK_HISTORY_REQUEST: self._on_history,
            topics.BENCHMARK_LOAD_REQUEST: self._on_load,
            topics.BENCHMARK_STOP_REQUEST: self._on_stop,
            topics.COGNITION_PROVIDER_STATUS: self._on_provider,
        }
        for topic, handler in handlers.items():
            self._subs.append(await ctx.bus.subscribe(topic, handler))
        ctx.logger.info("benchmark.started", suites=len(datasets_mod.SOURCES))

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise
                pass
        self._task = None
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []

    async def health(self) -> Health:
        if self._task is not None and not self._task.done():
            return Health.ok(f"running {self._running.get('suite', '?')}")
        return Health.ok("idle")

    def _cache_dir(self):
        from pathlib import Path

        return Path(self._config.cache_dir).expanduser() if self._config.cache_dir else None

    # -- handlers ------------------------------------------------------
    async def _on_provider(self, message: Message) -> None:
        payload = message.payload
        if payload.get("selected") or self._model == "unknown":
            self._model = str(payload.get("model") or payload.get("provider") or "unknown")

    async def _on_suites(self, message: Message) -> None:
        suites = []
        for source in datasets_mod.known():
            cached = datasets_mod.load_cached(source, self._cache_dir())
            suites.append({
                "name": source.name, "dataset": source.dataset, "description": source.description,
                "gated": source.gated, "scorable": source.scorable,
                "why_not_scorable": source.why_not_scorable,
                "cached_cases": len(cached) if cached else 0,
                "levels": list(cached.levels()) if cached else [],
            })
        await self._ctx.bus.reply(message, type=topics.BENCHMARK_SUITES_REPLY, payload={
            "suites": suites, "model": self._model, "running": bool(self._task and not self._task.done()),
        })

    async def _on_stop(self, message: Message) -> None:
        """End the run in flight. Its partial result is still recorded --
        the cases it did answer are real evidence."""
        if self._task is None or self._task.done():
            await self._ctx.bus.reply(message, type=topics.BENCHMARK_STOP_REPLY,
                                      payload={"stopped": False, "detail": "no benchmark run is in flight"})
            return
        running = dict(self._running)
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- the cancel is the point
            pass
        await self._ctx.bus.reply(message, type=topics.BENCHMARK_STOP_REPLY, payload={
            "stopped": True, "run_id": running.get("run_id", ""), "suite": running.get("suite", ""),
            "detail": (
                f"stopped after {running.get('index', 0)} of {running.get('total', 0)} cases; "
                "the partial result is recorded"
            ),
        })

    async def _on_load(self, message: Message) -> None:
        """Download a suite without running it -- how an operator gets
        the cases onto the machine, and checks their token works, before
        spending model calls on them."""
        name = message.payload.get("suite") or ""
        try:
            suite = await asyncio.to_thread(
                datasets_mod.load, name, refresh=bool(message.payload.get("refresh")),
                timeout=self._config.fetch_timeout_s, cache_dir=self._cache_dir(),
            )
        except datasets_mod.DatasetUnavailable as exc:
            await self._ctx.bus.reply(message, type=topics.BENCHMARK_LOAD_REPLY,
                                      payload=error_reply_payload("dataset_unavailable", str(exc)))
            return
        source = datasets_mod.SOURCES[name]
        await self._ctx.bus.reply(message, type=topics.BENCHMARK_LOAD_REPLY, payload={
            "suite": suite.name, "suite_version": suite.version, "cases": len(suite),
            "levels": list(suite.levels()), "scorable": source.scorable,
            "needs_attachment": sum(1 for c in suite.cases if c.needs_attachment),
            "cache_path": str(datasets_mod.cache_path(source, self._cache_dir())),
        })

    async def _on_history(self, message: Message) -> None:  # noqa: D401
        payload = message.payload
        run_id = payload.get("run_id") or ""
        if run_id:
            record = await self._store.detail(run_id)
            await self._ctx.bus.reply(message, type=topics.BENCHMARK_HISTORY_REPLY, payload={
                "runs": [record.to_payload()] if record else [], "model": self._model,
            })
            return
        records = await self._store.history(
            suite=payload.get("suite", ""), model=payload.get("model", ""),
            limit=int(payload.get("limit") or self._config.history_limit),
        )
        await self._ctx.bus.reply(message, type=topics.BENCHMARK_HISTORY_REPLY, payload={
            "runs": [r.to_payload(with_cases=False) for r in records], "model": self._model,
            "running": bool(self._task and not self._task.done()), "progress": dict(self._running),
        })

    async def _on_run(self, message: Message) -> None:
        payload = message.payload
        if self._task is not None and not self._task.done():
            # Say what to do about it, not just what is true. The
            # creator hit this and the message named neither how far
            # along the run was in time nor how to stop it (2026-09-08).
            index = self._running.get("index", 0)
            total = self._running.get("total", 0)
            elapsed = time.monotonic() - self._running.get("started", time.monotonic())
            await self._ctx.bus.reply(message, type=topics.BENCHMARK_RUN_REPLY,
                                      payload=error_reply_payload("already_running", (
                                          f"a {self._running.get('suite', '?')} run is on case {index} of "
                                          f"{total} after {elapsed:.0f}s -- one at a time, or they would "
                                          f"measure each other's contention. `benchmark` shows its progress; "
                                          f"`benchmark stop` ends it."
                                      ), retryable=True))
            return
        name = payload.get("suite") or "gaia"
        limit = int(payload.get("limit") or self._config.default_cases)
        level = str(payload.get("level") or "")
        try:
            suite = await asyncio.to_thread(
                datasets_mod.load, name, refresh=bool(payload.get("refresh")),
                timeout=self._config.fetch_timeout_s, cache_dir=self._cache_dir(),
            )
        except datasets_mod.DatasetUnavailable as exc:
            await self._ctx.bus.reply(message, type=topics.BENCHMARK_RUN_REPLY,
                                      payload=error_reply_payload("dataset_unavailable", str(exc)))
            return
        source = datasets_mod.SOURCES[name]
        if not source.scorable:
            payload = error_reply_payload("not_scorable", source.why_not_scorable)
            payload["cases"] = len(suite)
            await self._ctx.bus.reply(message, type=topics.BENCHMARK_RUN_REPLY, payload=payload)
            return
        chosen = suite.sample(limit, level=level)
        if not len(chosen):
            await self._ctx.bus.reply(message, type=topics.BENCHMARK_RUN_REPLY,
                                      payload=error_reply_payload("no_cases", (
                                          f"{name} has no cases at level {level!r}" if level else f"{name} has no cases"
                                      )))
            return
        record = RunRecord(suite=chosen.name, suite_version=chosen.version, model=self._model,
                           note=payload.get("note", ""))
        self._running = {"run_id": record.run_id, "suite": chosen.name, "index": 0,
                         "total": len(chosen), "started": time.monotonic()}
        self._task = asyncio.create_task(self._run(chosen, record), name=f"benchmark-{record.run_id}")
        await self._ctx.bus.reply(message, type=topics.BENCHMARK_RUN_REPLY, payload={
            "ok": True, "run_id": record.run_id, "suite": chosen.name, "cases": len(chosen),
            "model": self._model, "suite_version": chosen.version,
        })

    # -- the run -------------------------------------------------------
    async def _run(self, suite, record: RunRecord) -> None:
        ctx = self._ctx
        assert ctx is not None
        started = time.monotonic()

        def _progress(*, index: int, total: int, case, record: RunRecord) -> None:
            self._running.update({"index": index, "total": total, "case": case.id,
                                  "correct": record.correct, "attempted": record.attempted})
            asyncio.ensure_future(ctx.bus.publish(Message.new(
                topics.BENCHMARK_PROGRESS, source=ctx.source, payload={
                    "run_id": record.run_id, "suite": suite.name, "index": index, "total": total,
                    "case_id": case.id, "level": case.level,
                    "correct": record.correct, "attempted": record.attempted,
                    "elapsed_s": round(time.monotonic() - started, 1),
                }, clock=ctx.clock.now,
            )))

        runner = Runner(ctx.bus, config=self._config, clock=ctx.clock.now, on_progress=_progress)
        try:
            finished = await runner.run(suite, model=self._model, note=record.note, record=record)
        except asyncio.CancelledError:
            record.partial = True
            record.finished_at = ctx.clock.now()
            await self._store.append(record)
            raise
        except Exception as exc:  # noqa: BLE001 -- a crashed run is recorded, not lost
            record.partial = True
            record.note = f"{record.note} (crashed: {exc!r})".strip()
            record.finished_at = ctx.clock.now()
            await self._store.append(record)
            ctx.logger.warning("benchmark.run_failed", run_id=record.run_id, error=repr(exc))
            return
        finally:
            self._running = {}
        await self._store.append(finished)
        await ctx.bus.publish(Message.new(
            topics.BENCHMARK_RUN_COMPLETED, source=ctx.source,
            payload=finished.to_payload(with_cases=False), clock=ctx.clock.now,
        ))
        await ctx.bus.publish(Message.new(topics.UI_NOTICE, source=ctx.source, payload={
            "level": "info", "source": "benchmark", "text": (
                f"{finished.suite}: {finished.correct}/{finished.attempted} correct "
                f"({finished.accuracy * 100:.1f}%) as {finished.model}"
            ),
        }, clock=ctx.clock.now))


__all__ = ["Service", "VERSION"]
