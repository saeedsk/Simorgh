"""Asking the real system a benchmark's questions.

Deliberately the same path a human's `research <question>` takes: a
`task.create` on the bus, then wait for `task.completed`. A harness that
called Cognition directly would measure the model, not Sim -- and the
whole reason to have this is that the model is not the part that has
been failing. Guardian, Planning, the tool loop and the step budget are
all in the measurement, which is the point.

Cases run one at a time (`[benchmark] concurrency`), each with its own
step cap, and the run is recorded whether it finishes or is interrupted.
"""

from __future__ import annotations

import asyncio
import time

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

from .api import Case, CaseResult, RunRecord, Suite
from .config import Config
from .scoring import answer_format, score_case


class Runner:
    def __init__(self, bus, *, config: Config | None = None, clock=None,
                 on_progress=None) -> None:
        self._bus = bus
        self._config = config or Config()
        self._clock = clock
        self._on_progress = on_progress or (lambda **_: None)

    def _now(self) -> float:
        if self._clock is None:
            return time.time()
        return self._clock() if callable(self._clock) else self._clock.now()

    def prompt(self, case: Case) -> str:
        """The question as the system is asked it.

        The answer-format instruction is part of GAIA, not our
        invention: the benchmark scores a specific answer shape and its
        own prompt asks for it. Asking without it and then scoring
        strictly would measure formatting, not capability."""
        parts = [case.question]
        if case.functions:
            parts.append(f"Functions you may call:\n{case.functions}")
        parts.append(answer_format(case.mode))
        return "\n\n".join(parts)

    async def run_case(self, case: Case) -> CaseResult:
        if case.needs_attachment:
            # Honest rather than convenient: a question about a
            # spreadsheet we never downloaded is unanswerable, and
            # scoring it wrong would flatter nothing and mislead us.
            return CaseResult(
                case_id=case.id, level=case.level, correct=False, skipped=True,
                expected=case.answer, error=f"needs the attached file {case.attachment!r}",
            )
        started = time.monotonic()
        cost_usd = 0.0
        # Listen *before* asking. A fast pipeline can complete the task
        # between the create reply and a later subscribe, and the answer
        # would land on nobody -- the case would then time out and score
        # zero for a right answer (caught by the flow test, 2026-09-07).
        watch = _AnswerWatch(self._bus)
        await watch.start()
        try:
            try:
                reply = await self._bus.request(
                    Message.new(topics.TASK_CREATE, source=self._bus.source, payload={
                        "kind": "research", "description": self.prompt(case),
                        # NOT "human". A benchmark case is not something
                        # the human typed, and claiming it was had two
                        # costs: every case landed permanently in their
                        # `tasks` list as if they had asked for it, and
                        # each one preempted -- and, before the cancel
                        # fixes, killed -- real autonomous work
                        # (observer, 2026-09-08).
                        "origin": "benchmark",
                        "mode": "execute", "max_steps": self._config.case_max_steps,
                    }, clock=self._clock),
                    timeout=15.0,
                )
            except Exception as exc:  # noqa: BLE001 -- a harness failure is not a wrong answer
                return CaseResult(case_id=case.id, level=case.level, correct=False, skipped=True,
                                  expected=case.answer, error=f"could not create the task: {exc!r}")
            task_id = reply.payload.get("task_id", "")
            if not task_id:
                return CaseResult(case_id=case.id, level=case.level, correct=False, skipped=True,
                                  expected=case.answer, error="planning created no task")
            dup_of = reply.payload.get("deduplicated_against")
            if dup_of:
                # Belt-and-suspenders: `origin="benchmark"` is now exempt
                # from Intake's fuzzy dedupe (observer, 2026-09-08 --
                # every GAIA question got the shared ~330-char
                # answer-format suffix appended, which alone pushed
                # unrelated questions over the similarity threshold, so
                # 5 of 7 cases in one run silently got handed back an
                # unrelated, already-completed task_id). If a dedupe
                # ever fires here anyway -- a future policy change, a
                # genuinely repeated question -- fail the case
                # immediately with an honest reason instead of blocking
                # the full case_timeout_s waiting for an outcome that
                # already happened to a different case.
                return CaseResult(
                    case_id=case.id, level=case.level, correct=False, skipped=True, expected=case.answer,
                    error=f"planning handed back an existing task ({dup_of!r}) instead of asking this "
                          f"case's question -- never actually asked",
                )
            answer_text, steps, error = await watch.wait(task_id, self._config.case_timeout_s)
            # Read before `watch.stop()`, and after the outcome, so a
            # cancelled or blocked case still reports what it spent.
            cost_usd = watch.cost(task_id)
            if not answer_text and error:
                # A case we gave up on used to keep its worker. The
                # worker takes one task at a time, so case 1 timing out
                # meant cases 2..n queued behind a run nobody was waiting
                # for -- and each of those then timed out in turn. A run
                # degraded case by case for a reason that never appeared
                # in the result (observer, 2026-09-08).
                await self._bus.publish(Message.new(
                    topics.TASK_CANCEL, source=self._bus.source,
                    payload={"task_id": task_id, "reason": f"benchmark case {case.id} gave up: {error}"},
                    partition_key=f"task:{task_id}", clock=self._clock,
                ))
        finally:
            await watch.stop()
        seconds = time.monotonic() - started
        if error and not answer_text:
            return CaseResult(case_id=case.id, level=case.level, correct=False, expected=case.answer,
                              seconds=seconds, steps=steps, cost_usd=cost_usd, error=error)
        # There is an answer even though something of ours stopped it.
        # Score it: GAIA scores the answer, and our verifier is not part
        # of GAIA. Record the block, so "our verifier rejected a right
        # answer" is visible rather than indistinguishable from "wrong".
        correct, extracted = score_case(answer_text, case.answer, mode=case.mode)
        return CaseResult(
            case_id=case.id, level=case.level, correct=correct, answer=extracted,
            expected=case.answer, seconds=seconds, steps=steps, cost_usd=cost_usd,
            blocked_by=error, error=error,
        )

    async def run(self, suite: Suite, *, model: str = "unknown", note: str = "",
                  record: RunRecord | None = None) -> RunRecord:
        """Run `suite`. A caller may pass the record to fill, so that a
        run cancelled mid-flight still has its answered cases: the
        service used to store its own empty placeholder and tell the
        human "the partial result is recorded" when it was not
        (observer, 2026-09-08)."""
        if record is None:
            record = RunRecord(suite=suite.name, suite_version=suite.version, model=model, note=note)
        record.started_at = self._now()
        try:
            for index, case in enumerate(suite.cases, start=1):
                result = await self.run_case(case)
                record.results.append(result)
                # Fire progress only after the case is scored and
                # appended, so a cancellation mid-case (or `benchmark
                # stop`) never counts a case that never made it into
                # `record.results` -- `index` here is always the number
                # of cases actually recorded so far (observer,
                # 2026-09-08: "stopped after 2 of 4" when only 1 case
                # was stored).
                self._on_progress(index=index, total=len(suite), case=case, record=record)
        except asyncio.CancelledError:
            # An interrupted run is real evidence and is kept -- labelled,
            # so nobody compares five cases against fifty as equals.
            record.partial = True
            record.finished_at = self._now()
            raise
        finally:
            if not record.finished_at:
                record.finished_at = self._now()
        record.partial = record.partial or len(record.results) < len(suite)
        return record


class _AnswerWatch:
    """Subscribes to task outcomes before a case's task exists.

    Buffers by task_id, because the subscription is necessarily older
    than the id it is waiting for."""

    def __init__(self, bus) -> None:
        self._bus = bus
        self._subs: list = []
        self._steps: dict[str, int] = {}
        # What each case's task spent. `task.step` carries it now, and
        # nothing was reading it -- so every benchmark run reported a
        # cost of $0.00 for real, billed model calls.
        self._cost: dict[str, float] = {}
        self._outcomes: dict[str, tuple[str, dict]] = {}
        self._waiters: dict[str, asyncio.Future] = {}

    async def start(self) -> None:
        async def _on_step(message: Message) -> None:
            payload = message.payload
            task_id = payload.get("task_id", "")
            if payload.get("cost_usd"):
                # Counted on EVERY step, including the ones with no `ok`
                # -- a think that failed was still billed.
                self._cost[task_id] = self._cost.get(task_id, 0.0) + float(payload["cost_usd"])
            if payload.get("ok") is not None:
                self._steps[task_id] = self._steps.get(task_id, 0) + 1

        def _finisher(kind: str):
            async def _on(message: Message) -> None:
                task_id = message.payload.get("task_id", "")
                if not task_id or task_id in self._outcomes:
                    return
                self._outcomes[task_id] = (kind, message.payload)
                waiter = self._waiters.get(task_id)
                if waiter is not None and not waiter.done():
                    waiter.set_result(None)
            return _on

        self._subs = [
            await self._bus.subscribe(topics.TASK_STEP, _on_step),
            await self._bus.subscribe(topics.TASK_COMPLETED, _finisher("completed")),
            await self._bus.subscribe(topics.TASK_FAILED, _finisher("failed")),
            await self._bus.subscribe(topics.TASK_BLOCKED, _finisher("blocked")),
        ]

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []

    def cost(self, task_id: str) -> float:
        return round(self._cost.get(task_id, 0.0), 6)

    async def wait(self, task_id: str, timeout_s: float) -> tuple[str, int, str]:
        if task_id not in self._outcomes:
            waiter: asyncio.Future = asyncio.get_running_loop().create_future()
            self._waiters[task_id] = waiter
            try:
                await asyncio.wait_for(waiter, timeout=timeout_s)
            except asyncio.TimeoutError:
                return "", self._steps.get(task_id, 0), f"no answer within {timeout_s:.0f}s"
            finally:
                self._waiters.pop(task_id, None)
        kind, payload = self._outcomes[task_id]
        steps = self._steps.get(task_id, 0)
        text = str(payload.get("result_summary") or "")
        if kind != "completed":
            return text, steps, str(payload.get("reason") or f"the task was {kind}")
        return text, steps, ""


__all__ = ["Runner"]
