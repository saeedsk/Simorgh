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
from . import swebench
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


def _compare_candidates(runs: list[dict]) -> list[int]:
    """Indices of the runs `history` will compare: the last two PER
    SUITE that scored at least one case.

    The view compares the two most recent scored runs of a suite, and
    only these carry per-case detail (the rest stay the cheap summary).
    Choosing the last two by position instead put a run interrupted
    before any case -- 0 attempted -- in the pair, so the run the view
    really compared had no cases and `benchmark history` said `over 0
    shared cases` for two runs of the same two cases (observer swe-01,
    2026-09-10)."""
    by_suite: dict[str, list[int]] = {}
    for i, run in enumerate(runs):
        if int(run.get("attempted") or 0) > 0:
            by_suite.setdefault(str(run.get("suite", "")), []).append(i)
    return [i for indices in by_suite.values() for i in indices[-2:]]


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
        await self._cancel_orphaned_cases()

    async def _cancel_orphaned_cases(self) -> None:
        """A run does not survive a restart; its tasks used to.

        Every case is a `benchmark`-origin task, and the runner is the
        only thing that ever waits for one. When Sim stopped mid-run
        (the creator's `exit`, a crash, a kill) the run was recorded
        `partial` and the case's task stayed `available` -- and was
        claimed by the next boot's worker, which ran a full patch session
        against a checkout the dead run had already deleted, failed on
        `refused: ... does not exist`, and did it again for the next
        one. Live, 2026-09-10 22:47: four such tasks from four dead runs
        (15:28, 15:49, 16:36, 18:37) sat ahead of the case a fresh run
        had just created -- same weight, older `created_at`, so the
        scheduler served them first -- and the fresh case's 600s clock
        ran while the single worker cleared ghosts. The two cases of the
        18:37 run had died the same way behind 312 synthetic tasks:
        `steps 0`, `no answer within 600s`, never started.

        So at boot every open benchmark task is cancelled. Nothing can
        be waiting for it: this service has no run in flight yet, and it
        is the only one that creates them.
        """
        assert self._ctx is not None
        try:
            reply = await self._ctx.bus.request(Message.new(
                topics.TASK_LIST_REQUEST, source=self._ctx.source, payload={}, clock=self._ctx.clock.now,
            ), timeout=5.0)
        except Exception as exc:  # noqa: BLE001 -- no Planning yet is not a reason to fail the boot
            self._ctx.logger.info("benchmark.orphan_sweep_skipped", error=repr(exc))
            return
        open_states = {"pending", "available", "blocked", "claimed", "in_progress", "paused"}
        orphans = [t for t in (reply.payload.get("tasks") or [])
                   if t.get("origin") == "benchmark" and t.get("status") in open_states]
        for t in orphans:
            await self._ctx.bus.publish(Message.new(
                topics.TASK_CANCEL, source=self._ctx.source, partition_key=f"task:{t['task_id']}",
                payload={"task_id": t["task_id"],
                         "reason": "benchmark case from a run that did not survive a restart -- nothing is waiting for it"},
                clock=self._ctx.clock.now,
            ))
        if orphans:
            self._ctx.logger.info("benchmark.orphaned_cases_cancelled", count=len(orphans),
                                  task_ids=[t["task_id"] for t in orphans][:20])

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
                "gated": source.gated, "scorable": source.scorable, "needs": source.needs,
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
        runs = [r.to_payload(with_cases=False) for r in records]
        # `history` shows a compare block for the two most recent runs of
        # each suite, and a real diff needs their per-case results -- the
        # summary payload above never carries `cases`. Fetch just those
        # two runs' full detail blobs (store.detail), same lookup
        # `benchmark <run_id>` already uses, and swap them in. Everything
        # else stays the cheap summary the chart plots.
        for i in _compare_candidates(runs):
            detail = await self._store.detail(runs[i].get("run_id", ""))
            if detail is not None:
                runs[i] = detail.to_payload(with_cases=True)
        await self._ctx.bus.reply(message, type=topics.BENCHMARK_HISTORY_REPLY, payload={
            "runs": runs, "model": self._model,
            "running": bool(self._task and not self._task.done()), "progress": self._progress_view(),
        })

    def _progress_view(self) -> dict:
        """`_running`, with its monotonic stamps turned into the elapsed
        seconds a reader can print. The raw stamps mean nothing outside
        this process, and the view used to carry them and nothing else
        about time -- so `benchmark` mid-run could not say how long the
        run, or the case, had been going (observer, 2026-09-10)."""
        view = dict(self._running)
        if not view:
            return view
        now = time.monotonic()
        if "started" in view:
            view["elapsed_s"] = round(now - view.pop("started"), 1)
        if "case_started" in view:
            view["case_elapsed_s"] = round(now - view.pop("case_started"), 1)
        return view

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
        if any(case.mode == "swebench" for case in suite.cases):
            # Checked once, here, rather than discovered a hundred times
            # in a row: without Docker every case would be skipped, and
            # a run of nothing but skips reads as a run that happened.
            ok, why = await asyncio.to_thread(swebench.available)
            if not ok:
                await self._ctx.bus.reply(
                    message, type=topics.BENCHMARK_RUN_REPLY,
                    payload=error_reply_payload("needs_docker", (
                        f"{why} -- each case is scored by running its repository's own tests "
                        f"in the container image the dataset names")))
                return
        if level:
            # "no such level" and "no cases at that level" are different
            # answers and used not to be. The creator typed `level=1`
            # through `level=4` at SWE-bench Verified and got
            # `no_cases` four times (live, 2026-09-10): its levels are
            # named by duration, and nothing in the refusal said so.
            resolved = suite.match_level(level)
            if resolved is None:
                await self._ctx.bus.reply(message, type=topics.BENCHMARK_RUN_REPLY,
                                          payload=error_reply_payload("no_such_level", (
                                              f"{name} has no level {level!r}. Its levels, easiest first: "
                                              + " · ".join(f"{i}={lv}" for i, lv in enumerate(suite.levels(), 1))
                                              + " -- the number or the name works.")))
                return
            level = resolved
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
            "model": self._model, "suite_version": chosen.version, "level": level,
        })

    # -- the run -------------------------------------------------------
    async def _run(self, suite, record: RunRecord) -> None:
        ctx = self._ctx
        assert ctx is not None
        started = time.monotonic()

        def _starting(*, index: int, total: int, case) -> None:
            # The case in flight, named as it starts: `benchmark` typed
            # mid-run answered "0/2  0/0 correct so far" for the whole
            # first case, because nothing here knew which case that was
            # until it had been scored (observer, 2026-09-10).
            self._running.update({"total": total, "case": case.id, "level": case.level,
                                  "case_started": time.monotonic()})

        # The progress publishes are fire-and-forget (the callback is
        # synchronous); they are collected so the run's completion
        # notice can wait for them. Without that the LAST case's line
        # printed after "2/2 correct" on the terminal (observer,
        # 2026-09-10) -- a verdict arriving after the summary of it.
        pending: list[asyncio.Future] = []

        def _progress(*, index: int, total: int, case, record: RunRecord) -> None:
            self._running.update({"index": index, "total": total, "case": case.id,
                                  "correct": record.correct, "attempted": record.attempted})
            last = record.results[-1] if record.results else None
            pending.append(asyncio.ensure_future(ctx.bus.publish(Message.new(
                topics.BENCHMARK_PROGRESS, source=ctx.source, payload={
                    "run_id": record.run_id, "suite": suite.name, "index": index, "total": total,
                    "case_id": case.id, "level": case.level,
                    "correct": record.correct, "attempted": record.attempted,
                    "elapsed_s": round(time.monotonic() - started, 1),
                    # This case's own verdict, for the one line per case
                    # the terminal prints. The totals alone cannot say
                    # whether the case just scored passed.
                    "case_correct": bool(last.correct) if last else False,
                    "case_skipped": bool(last.skipped) if last else False,
                    "case_seconds": round(last.seconds, 1) if last else 0.0,
                    "case_error": (last.error or "")[:300] if last else "",
                }, clock=ctx.clock.now,
            ))))

        runner = Runner(ctx.bus, config=self._config, clock=ctx.clock.now,
                        on_progress=_progress, on_start=_starting)
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
        if pending:
            # Every case's own line before the run's summary line.
            await asyncio.gather(*pending, return_exceptions=True)
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
