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
import shutil
import time
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

from . import datasets, swebench
from .api import Case, CaseResult, RunRecord, Suite
from .config import Config
from .scoring import answer_format, score_case

#: Prefix on the errors that mean the case was never actually put to
#: the system. Those are unmeasured, not wrong.
_UNASKED = "never asked --"


class Runner:
    def __init__(self, bus, *, config: Config | None = None, clock=None,
                 on_progress=None, repo_root: Path | None = None) -> None:
        self._bus = bus
        self._config = config or Config()
        self._clock = clock
        self._on_progress = on_progress or (lambda **_: None)
        # SWE-bench checkouts and logs are written relative to this, the
        # same root the file tools resolve their paths against -- a
        # checkout Sim cannot address by the path we give it is a
        # checkout it cannot fix.
        self._repo_root = Path(repo_root or Path.cwd())

    def _now(self) -> float:
        if self._clock is None:
            return time.time()
        return self._clock() if callable(self._clock) else self._clock.now()

    def prompt(self, case: Case, attachment: str = "") -> str:
        """The question as the system is asked it.

        The answer-format instruction is part of GAIA, not our
        invention: the benchmark scores a specific answer shape and its
        own prompt asks for it. Asking without it and then scoring
        strictly would measure formatting, not capability."""
        parts = [case.question]
        if attachment:
            parts.append(f"The file this question is about is at `{attachment}`. Read it.")
        if case.functions:
            parts.append(f"Functions you may call:\n{case.functions}")
        parts.append(answer_format(case.mode))
        return "\n\n".join(parts)

    def patch_prompt(self, case: Case, checkout: str) -> str:
        """A SWE-bench case as a piece of work, not a question.

        The system is given the issue and a real checkout, and is scored
        on whether the repository's own tests pass afterwards -- so the
        instruction that matters is where the code is, and that editing
        the tests is not a fix."""
        return "\n\n".join([
            f"Fix this bug in the repository checked out at `{checkout}`.",
            case.question,
            "\n".join([
                f"The whole project is under `{checkout}` -- read it, find the cause, and change "
                f"the source files there.",
                "Do not edit or add tests. The project's own test suite decides whether this is "
                "fixed, it is restored before it runs, and any change you make to it is discarded.",
                "To run that project's tests, call run_tests with a path inside the checkout "
                f"(for example `{checkout}/path/to/test_file.py`): it runs inside the project's "
                "own container, where its dependencies are installed. Running the whole suite is "
                "slow; name the test file nearest the code you changed.",
                "git_commit with a path inside the checkout commits there, not in this repository.",
                "There is no answer to write out. The change you leave in those files IS the "
                "answer, so finish by saving your edits.",
            ]),
        ])

    async def run_case(self, case: Case) -> CaseResult:
        if case.mode == "swebench":
            return await self._run_swebench(case)
        attachment = ""
        if case.needs_attachment:
            attachment, problem = await self._fetch_attachment(case)
            if problem:
                # Still honest, and now rare: a question about a
                # spreadsheet we could not download is unanswerable, and
                # scoring it wrong would flatter nothing and mislead us.
                return CaseResult(
                    case_id=case.id, level=case.level, correct=False, skipped=True,
                    expected=case.answer, error=problem,
                )
        started = time.monotonic()
        answer_text, steps, cost_usd, error = await self._ask(case, self.prompt(case, attachment))
        seconds = time.monotonic() - started
        if error and not answer_text:
            return CaseResult(case_id=case.id, level=case.level, correct=False, expected=case.answer,
                              seconds=seconds, steps=steps, cost_usd=cost_usd, error=error,
                              skipped=error.startswith(_UNASKED))
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

    async def _fetch_attachment(self, case: Case) -> tuple[str, str]:
        """`(path Sim can open, problem)`.

        The file lands under the workspace because that is the one
        directory the file tools may both read and write -- a file
        anywhere else is one the answering system cannot open, which
        would leave the case just as unanswerable as not fetching it.
        The path handed to the model is repo-relative for the same
        reason: that is what `read_file` resolves."""
        source = datasets.SOURCES.get(case.suite)
        if source is None:
            return "", (f"needs the attached file {case.attachment!r}, and {case.suite!r} is not a "
                        f"suite this system knows how to fetch files for")
        relative = f"{self._config.attachment_dir}/{case.id}"
        path, problem = await asyncio.to_thread(
            datasets.fetch_attachment, source, case,
            dest=self._repo_root / relative, timeout=self._config.fetch_timeout_s)
        if problem or path is None:
            # The file's name belongs in the reason: "could not fetch a
            # file" is not something anyone can act on.
            return "", f"needs the attached file {case.attachment!r} -- " + (
                problem or "it could not be fetched")
        return f"{relative}/{path.name}", ""

    async def _ask(self, case: Case, prompt: str, *, kind: str = "research") -> tuple[str, int, float, str]:
        """Ask the real system one thing. `(answer, steps, cost, error)`.

        Shared by every mode, because what is being measured is this
        path -- Guardian, Planning, the tool loop and the step budget --
        and a second way of asking would measure a second system."""
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
                        "kind": kind, "description": prompt,
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
                return "", 0, 0.0, f"{_UNASKED} could not create the task: {exc!r}"
            task_id = reply.payload.get("task_id", "")
            if not task_id:
                return "", 0, 0.0, f"{_UNASKED} planning created no task"
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
                return "", 0, 0.0, (f"{_UNASKED} planning handed back an existing task ({dup_of!r}) "
                                    f"instead of asking this case's question")
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
        return answer_text, steps, cost_usd, error

    async def _run_swebench(self, case: Case) -> CaseResult:
        """One SWE-bench instance, scored by running its own tests.

        Every early return here is `skipped=True`, and that distinction
        is the whole point: "we could not run the tests" and "the patch
        did not fix the bug" are different facts, and only the second
        one is about the system under test."""
        instance = case.payload()
        started = time.monotonic()
        ok, why = await asyncio.to_thread(swebench.available)
        if not ok:
            return CaseResult(case_id=case.id, level=case.level, correct=False, skipped=True,
                              expected=case.answer, error=why)
        if not instance.get("image") or not instance.get("eval_script"):
            return CaseResult(
                case_id=case.id, level=case.level, correct=False, skipped=True, expected=case.answer,
                error="this case carries no container image or eval script -- reload the suite "
                      "(`benchmark load swebench-verified`), which now stores both")

        relative = f"{self._config.swebench_checkout_dir}/{case.id}"
        checkout = self._repo_root / relative
        problem = await asyncio.to_thread(
            swebench.materialize, instance, checkout,
            timeout=self._config.swebench_setup_timeout_s)
        if problem:
            return CaseResult(case_id=case.id, level=case.level, correct=False, skipped=True,
                              expected=case.answer, error=problem)
        try:
            # The reply text is deliberately dropped: this case is
            # scored by running tests, and nothing the system says about
            # its own work is evidence.
            _said, steps, cost_usd, error = await self._ask(
                case, self.patch_prompt(case, relative), kind="patch")
            patch, trouble = await asyncio.to_thread(
                swebench.diff_of, checkout, base=str(instance.get("base_commit") or ""))
        finally:
            # The checkout has done its job the moment the diff is read;
            # the patch is re-applied to a pristine container anyway.
            await asyncio.to_thread(shutil.rmtree, checkout, True)

        seconds = time.monotonic() - started
        if trouble:
            return CaseResult(case_id=case.id, level=case.level, correct=False, skipped=True,
                              expected=case.answer, seconds=seconds, steps=steps,
                              cost_usd=cost_usd, error=trouble)
        verdict, _log = await asyncio.to_thread(
            swebench.evaluate, instance, patch,
            timeout=self._config.swebench_eval_timeout_s,
            log_path=self._repo_root / self._config.swebench_log_dir / f"{case.id}.log")
        detail = verdict.detail
        if error and not verdict.resolved:
            # What stopped the task is part of why the patch is what it
            # is -- a case that ran out of steps half way through a fix
            # should not read as "the model was wrong".
            detail = f"{detail}; the task itself {error}"
        return CaseResult(
            case_id=case.id, level=case.level, correct=verdict.resolved, skipped=verdict.skipped,
            answer=patch[:4000], expected=case.answer, seconds=time.monotonic() - started,
            steps=steps, cost_usd=cost_usd, blocked_by=error, error="" if verdict.resolved else detail,
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
