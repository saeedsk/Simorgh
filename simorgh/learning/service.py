"""`Service`: wires `OutcomeRecorder`, `CompetenceTable`, strategy
suggestion, and the patch/skill pipeline runner into the real Bus/Ledger
(spec section 5). Scope note (see README build log): this build
implements the outcome/competence/strategy core and the full patch and
skill pipeline (Flow 4); `evolve` batch pipelines, hot-swap experiments,
and knowledge distillation are not yet built -- `learn.pipeline.run{kind:
evolve}` is acknowledged and rejected with an honest `floor` outcome
rather than silently mishandled.
"""

from __future__ import annotations

import uuid
from typing import Any

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from .competence import CompetenceTable
from .config import Config
from .correlator import Correlator
from .outcomes import OutcomeRecorder
from .pipeline import PatchPipeline

VERSION = "0.1.0"


class Service:
    name = "learning"
    version = VERSION
    consumes = (
        topics.TASK_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED,
        topics.ACTION_RESULT, topics.ACTION_DENIED, topics.VERIFY_RESULT,
        topics.LEARN_PIPELINE_RUN, topics.LEARN_STRATEGY_SUGGEST,
    )
    produces = (
        topics.LEARN_OUTCOME_RECORDED, topics.LEARN_COMPETENCE_UPDATED, topics.LEARN_PIPELINE_COMPLETED,
        topics.LEARN_STRATEGY_SUGGEST_REPLY, topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SELF_PATCH_REVERTED,
        topics.LEARN_SKILL_ACQUIRED, topics.ACTION_PROPOSED, topics.VERIFY_REQUESTED, topics.MEMORY_STORE,
    )

    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        self._ctx: Context | None = None
        self._competence = CompetenceTable()
        self._action_correlator = Correlator(id_field="action_id")
        self._verify_correlator = Correlator(id_field="verification_id")
        self._subs: list = []
        self._running_pipelines: dict[str, "PatchPipeline"] = {}
        self._degraded: str | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
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
        self._subs.append(await ctx.bus.subscribe(topics.ACTION_RESULT, self._on_action_result))
        self._subs.append(await ctx.bus.subscribe(topics.ACTION_DENIED, self._on_action_denied))
        self._subs.append(await ctx.bus.subscribe(topics.LEARN_PIPELINE_RUN, self._on_pipeline_run, group="learning"))
        self._subs.append(await ctx.bus.subscribe(topics.LEARN_STRATEGY_SUGGEST, self._on_strategy_suggest))

    async def stop(self) -> None:
        self._action_correlator.cancel_all()
        self._verify_correlator.cancel_all()
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()

    async def health(self) -> Health:
        if self._degraded:
            return Health.degraded(self._degraded)
        return Health.ok(f"{len(self._running_pipelines)} pipeline(s) running")

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
        self._verify_correlator.resolve(message.payload)

    async def _on_action_result(self, message: Message) -> None:
        self._action_correlator.resolve(message.payload)

    async def _on_action_denied(self, message: Message) -> None:
        # A denial resolves the same future a result would -- the pipeline
        # sees `{"denied": True, ...}` and treats it as terminal for this step.
        payload = dict(message.payload)
        payload["denied"] = True
        self._action_correlator.resolve(payload)

    # -- strategy ---------------------------------------------------------------
    async def _on_strategy_suggest(self, message: Message) -> None:
        from .strategy import build_reply
        reply = build_reply(message.payload["task_type"], competence=self._competence, config=self._config)
        ctx = self._ctx
        assert ctx is not None
        await ctx.bus.reply(message, type=topics.LEARN_STRATEGY_SUGGEST_REPLY, payload=reply)

    # -- pipeline dispatch --------------------------------------------------------
    async def _on_pipeline_run(self, message: Message) -> None:
        p = message.payload
        task_id, kind = p["task_id"], p["kind"]
        if kind == "evolve":
            # Not yet built this pass (README build log) -- an honest floor
            # outcome rather than a silent no-op or a fabricated result.
            await self._publish(topics.LEARN_PIPELINE_COMPLETED, {
                "task_id": task_id, "outcome": "floor",
                "detail": "evolve batch pipeline is not implemented in this build",
            })
            return
        if len(self._running_pipelines) >= self._config.max_concurrent_pipelines:
            await self._publish(topics.LEARN_PIPELINE_COMPLETED, {
                "task_id": task_id, "outcome": "floor", "detail": "max_concurrent_pipelines reached",
            })
            return
        pipeline = PatchPipeline(
            task_id=task_id, kind=kind, description=p["description"], subject=p.get("subject"),
            prior_reasons=list(p.get("prior_reasons") or []), config=self._config, ledger=self._ctx.ledger,
            clock=self._ctx.clock.now, propose_action=self._propose_action, request_verify=self._request_verify,
            action_correlator=self._action_correlator, verify_correlator=self._verify_correlator,
            publish=self._publish,
        )
        self._running_pipelines[task_id] = pipeline
        try:
            await pipeline.run()
        finally:
            self._running_pipelines.pop(task_id, None)

    async def _propose_action(self, *, action_id: str, tool: str, args: dict, scope: dict,
                               reversibility: str, rationale: str, task_id: str) -> None:
        await self._publish(topics.ACTION_PROPOSED, {
            "action_id": action_id, "tool": tool, "args": args, "scope": scope,
            "reversibility": reversibility, "rationale": rationale, "proposed_by": self.name, "task_id": task_id,
        })

    async def _request_verify(self, *, verification_id: str, task_id: str, kind: str,
                               subject_ref: str, checklist_hint: str) -> None:
        await self._publish(topics.VERIFY_REQUESTED, {
            "verification_id": verification_id, "task_id": task_id, "kind": kind,
            "subject_ref": subject_ref, "checklist_hint": checklist_hint,
        })


__all__ = ["Service", "VERSION"]
