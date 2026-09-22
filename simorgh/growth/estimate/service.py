"""`Service`: wires `OutcomeRecorder`, `CompetenceTable` and strategy
suggestion into the real Bus/Ledger. Outcomes in, competence out.

Sim's own code changes land through Orchestration's worktree path
(`orchestration/session.py::_land`), which publishes
`learn.self_patch.applied`; this subsystem records the outcome. The
autonomous PatchPipeline that used to live here was retired on
2026-09-19: nothing published its trigger and its drafting tool was
never registered (2026-09-18 evaluation, C1/C14).
"""

from __future__ import annotations

import uuid
from typing import Any

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from .competence import CompetenceTable


def _half_life_s(config: Config) -> float:
    return max(0.0, float(getattr(config, "competence_half_life_days", 30.0))) * 86_400.0
from .config import Config
from .outcomes import OutcomeRecorder

VERSION = "0.1.0"


class Service:
    name = "growth.estimate"
    version = VERSION
    consumes = (
        topics.TASK_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED,
        topics.VERIFY_RESULT,
        topics.LEARN_STRATEGY_SUGGEST,
        # What Sim believes about its own competence, asked for (stage 6 item 1).
        topics.SELF_ESTIMATE_REQUEST,
    )
    produces = (
        topics.LEARN_OUTCOME_RECORDED, topics.LEARN_COMPETENCE_UPDATED,
        topics.LEARN_STRATEGY_SUGGEST_REPLY,
    )

    def __init__(self, config: Config | None = None) -> None:
        self._config_from_caller = config
        self._config = config or Config()
        self._ctx: Context | None = None
        self._competence = CompetenceTable(half_life_s=_half_life_s(self._config))
        self._subs: list = []
        self._degraded: str | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        # Live-caught as a class 2026-09-08: every service is handed its
        # own `[section]` from simorgh.toml (`kernel/context.py` builds
        # `ctx.config` for exactly this) and eleven of them never read
        # it. The settings existed, were documented, were parsed into a
        # Config dataclass with a `from_mapping` -- and nothing ever
        # called it, so changing the file changed nothing. The dominant
        # bug shape in this codebase: a designed slot with one side
        # implemented and nobody writing to it.
        #
        # A config passed by the caller still wins, so a test that
        # constructs the service with one is unaffected.
        if self._config_from_caller is None and ctx.config:
            self._config = Config.from_mapping(dict(ctx.config))
            # The table was built before the section was read, so its
            # half-life is the default until now (stage 6 item 1). Set
            # rather than rebuilt: a rebuild would drop a projection the
            # ledger may already have folded into.
            self._competence.half_life_s = _half_life_s(self._config)
        self._outcomes = OutcomeRecorder(
            ledger=ctx.ledger, competence=self._competence, config=self._config,
            clock=ctx.clock.now, publish=self._publish,
        )
        try:
            # `materialize`, not `rebuild`: rebuild READS a snapshot and
            # never writes one, so `CompetenceTable.snapshot_every = 200`
            # was declared and never honoured -- the read found nothing
            # every time and replayed the whole of `learn:outcomes` on
            # every boot. Harmless while the stream is short, which is
            # what the plan recorded ("replays whole in milliseconds
            # today"), and this project has already had one stream reach
            # 192,332 entries in a day (stage 6 item 1, 2026-09-21).
            await ctx.ledger.materialize(self._competence, "learn:outcomes")
        except Exception as exc:  # noqa: BLE001 -- a bad rebuild must degrade, never crash start()
            self._degraded = f"competence rebuild failed: {exc!r}"

        self._subs.append(await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_completed))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_failed))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_BLOCKED, self._on_task_blocked))
        self._subs.append(await ctx.bus.subscribe(topics.VERIFY_RESULT, self._on_verify_result))
        self._subs.append(await ctx.bus.subscribe(topics.LEARN_STRATEGY_SUGGEST, self._on_strategy_suggest))
        self._subs.append(await ctx.bus.subscribe(topics.SELF_ESTIMATE_REQUEST, self._on_estimate))
        # The second source (stage 8 item 2). Read at start because the
        # evals run outside the Kernel, before Sim is up.
        from pathlib import Path

        for candidate in (Path(self._config.evals_record), ctx.data_dir / "evals.jsonl"):
            try:
                found = self.load_evals(candidate)
            except Exception as exc:  # noqa: BLE001 -- no evals is not a failed start
                ctx.logger.warning("estimate.evals_unreadable", path=str(candidate), error=repr(exc))
                continue
            if found:
                ctx.logger.info("estimate.evals_loaded", path=str(candidate), suites=found)
                break

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()

    async def health(self) -> Health:
        if self._degraded:
            return Health.degraded(self._degraded)
        skipped = self._outcomes.skipped_unknown if getattr(self, "_outcomes", None) is not None else 0
        return Health.ok(f"recording outcomes; {skipped} untyped turn(s) skipped")

    # -- publish helper --------------------------------------------------------
    async def _publish(self, type_: str, payload: dict) -> None:
        ctx = self._ctx
        assert ctx is not None
        await ctx.bus.publish(Message.new(type_, source=ctx.source, payload=payload, clock=ctx.clock.now))

    # -- outcome handlers --------------------------------------------------------
    async def _on_task_completed(self, message: Message) -> None:
        await self._outcomes.on_task_completed(message)

    async def _on_task_failed(self, message: Message) -> None:
        await self._outcomes.on_task_failed(message)

    async def _on_task_blocked(self, message: Message) -> None:
        await self._outcomes.on_task_blocked(message)

    async def _on_verify_result(self, message: Message) -> None:
        self._outcomes.cache_verify_result(message.payload)

    # -- strategy ---------------------------------------------------------------
    async def _on_estimate(self, message: Message) -> None:
        """`self.estimate.request` -- what Sim believes about itself at
        this kind of work (stage 6 item 1), from the two sources that
        count (stage 8 item 2): verify-backed outcomes, and the eval
        suite that speaks for this task type."""
        task_type = str(message.payload.get("task_type") or "")
        strategy = str(message.payload.get("strategy") or "") or None
        await self._ctx.bus.reply(message, type=topics.SELF_ESTIMATE_REPLY,
                                  payload=self._competence.estimate(
                                      task_type, strategy=strategy,
                                      eval_suite=self._suite_for(task_type),
                                      eval_weight=self._config.eval_sample_weight))

    def _suite_for(self, task_type: str) -> str | None:
        """The eval suite that speaks for this task type, if one does.

        Matched on the type's first segment: a task type is
        `patch:src/memory`, and the suite is about patching, not about
        that directory.
        """
        head = (task_type or "").split(":", 1)[0]
        for kind, suite in self._config.eval_suites:
            if kind == head:
                return suite
        return None

    def load_evals(self, path) -> int:
        """Fold an `evals.jsonl` into the table (stage 8 item 2).

        Read from a file rather than the bus because the evals run
        outside the Kernel -- `simloader bless` runs them before Sim is
        even up, which is exactly when the numbers are worth having.
        The newest report per suite wins; older ones are history, not
        more evidence, and counting every historical run would let a
        suite that has been run fifty times outvote the house.
        """
        import json
        from pathlib import Path

        path = Path(path)
        if not path.exists():
            return 0
        newest: dict[str, dict] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            suite = str(row.get("suite") or "")
            if suite:
                newest[suite] = row
        for suite, row in newest.items():
            self._competence.record_eval(suite, passed=int(row.get("passed") or 0),
                                         total=int(row.get("total") or 0),
                                         weight=self._config.eval_sample_weight)
        return len(newest)

    async def _on_strategy_suggest(self, message: Message) -> None:
        from .strategy import build_reply
        reply = build_reply(message.payload["task_type"], competence=self._competence, config=self._config)
        ctx = self._ctx
        assert ctx is not None
        await ctx.bus.reply(message, type=topics.LEARN_STRATEGY_SUGGEST_REPLY, payload=reply)


__all__ = ["Service", "VERSION"]
