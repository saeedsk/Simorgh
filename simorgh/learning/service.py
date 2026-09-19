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
from .config import Config
from .outcomes import OutcomeRecorder

VERSION = "0.1.0"


class Service:
    name = "learning"
    version = VERSION
    consumes = (
        topics.TASK_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED,
        topics.VERIFY_RESULT,
        topics.LEARN_STRATEGY_SUGGEST,
    )
    produces = (
        topics.LEARN_OUTCOME_RECORDED, topics.LEARN_COMPETENCE_UPDATED,
        topics.LEARN_STRATEGY_SUGGEST_REPLY,
    )

    def __init__(self, config: Config | None = None) -> None:
        self._config_from_caller = config
        self._config = config or Config()
        self._ctx: Context | None = None
        self._competence = CompetenceTable()
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
        self._outcomes = OutcomeRecorder(
            ledger=ctx.ledger, competence=self._competence, config=self._config,
            clock=ctx.clock.now, publish=self._publish,
        )
        try:
            await ctx.ledger.rebuild(self._competence, "learn:outcomes")
        except Exception as exc:  # noqa: BLE001 -- a bad rebuild must degrade, never crash start()
            self._degraded = f"competence rebuild failed: {exc!r}"

        self._subs.append(await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_completed))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_failed))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_BLOCKED, self._on_task_blocked))
        self._subs.append(await ctx.bus.subscribe(topics.VERIFY_RESULT, self._on_verify_result))
        self._subs.append(await ctx.bus.subscribe(topics.LEARN_STRATEGY_SUGGEST, self._on_strategy_suggest))

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
    async def _on_strategy_suggest(self, message: Message) -> None:
        from .strategy import build_reply
        reply = build_reply(message.payload["task_type"], competence=self._competence, config=self._config)
        ctx = self._ctx
        assert ctx is not None
        await ctx.bus.reply(message, type=topics.LEARN_STRATEGY_SUGGEST_REPLY, payload=reply)


__all__ = ["Service", "VERSION"]
