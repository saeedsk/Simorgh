"""The `Worker` (16 section 3.4/5): claims one `task.available` command at
a time (consumer group `workers`, competing-consumer -- multiple Worker
instances share the group and never double-claim the same delivery), runs
its Session to a terminal Outcome, and reports it. Tracks `system.state.
changed` so an in-flight Session can check `is_paused()` between steps
(Flow 5). Runs a `task.lease_heartbeat` timer alongside a claimed task's
Session (`_heartbeat_loop`) so a single slow step cannot let its lease
expire before the next `task.step` renews it the normal way -- wall-clock
step budgets beyond `_ACTION_TIMEOUTS` are still not implemented (see
README).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import OrderedDict
from dataclasses import replace

# Through the client, not `bus.api`: a subsystem may import `bus.client`
# and nothing else of the Bus.
from simorgh.bus.client import UNBOUNDED
from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message

from . import profiles
from .api import Outcome, Session
from .context import DEFAULT_TIMEOUT_S
from .resume import restore_session
from .session import SessionRunner


# The most any one attempt may spend, whatever a task asks for. Nine
# attempts (`[planning] max_blocked_retries`) of this is the true ceiling.
MAX_STEP_CAP = 200


def step_cap(requested, default: int) -> int:
    """A task's own step cap if it set one (`task.create.max_steps`),
    else the profile's. The creator, 2026-09-07: "what if a task
    requires long and multiple tool access" -- a big task can now say so."""
    try:
        cap = int(requested) if requested is not None else 0
    except (TypeError, ValueError):
        cap = 0
    return min(MAX_STEP_CAP, cap) if cap > 0 else default


_CANCEL_MEMORY = 256


class Worker:
    def __init__(
        self, bus, ledger, *, clock=None, worker_id: str | None = None,
        assemble_timeout_s: float = DEFAULT_TIMEOUT_S, think_timeout_s: float | None = None,
        heartbeat_s: float = 30.0,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._clock = clock
        # `Config.heartbeat_s` (`orchestration/config.py`, default 30) --
        # documented there since before this fix as declared-but-unread.
        # This is the first code path that reads it: how often
        # `_heartbeat_loop` renews a claimed task's lease while a single
        # step is still running.
        self._heartbeat_s = heartbeat_s
        self.worker_id = worker_id or f"w-{uuid.uuid4().hex[:8]}"
        self._paused = False
        # Read by `Service`'s own periodic `system.metrics` publish (a
        # dashboard's "what is each worker doing right now" view) --
        # plain attributes, not an event, since a live snapshot only
        # ever needs the current value, not a history of transitions.
        self.current_task_id: str | None = None
        self.current_kind: str | None = None
        # `SessionRunner`'s own default (5s) was never actually reachable
        # from here before this fix -- `Config.think_timeout_s` (120s)
        # existed and was documented but nothing threaded it through, so
        # every real `cognition.think` call that took longer than 5s (a
        # cold-start `claude` CLI subprocess routinely does, even though
        # Cognition's own provider timeout allows up to 180s) silently
        # floored to an empty reply. Live-caught by the creator's own
        # first interactive use of `simorgh run`: a plain "hello" printed
        # nothing at all -- indistinguishable from a hung REPL, but it
        # was this timeout cutting off a real, still-in-flight answer.
        runner_kwargs = {} if think_timeout_s is None else {"think_timeout_s": think_timeout_s}
        self._runner = SessionRunner(
            bus, ledger, clock=clock, worker_id=self.worker_id, is_paused=lambda: self._paused,
            is_cancelled=self._is_cancelled,
            assemble_timeout_s=assemble_timeout_s, **runner_kwargs,
        )
        self._subs: list = []
        # Task ids somebody has asked to stop -> whether that cancel was
        # a preemption (requeue) rather than a rejection. Entries are
        # dropped when the session they stopped ends; the cap only
        # bounds cancels for tasks this worker never had.
        self._cancelled: OrderedDict[str, bool] = OrderedDict()

    async def start(self) -> None:
        # `max_inflight=1` is the whole concurrency policy, and it belongs
        # here rather than in a queue of our own.
        #
        # Live-caught 2026-09-07: the default is 16, so one worker ran up
        # to sixteen sessions at once, claiming far more of the backlog
        # than it could finish. The creator's `tasks` showed all 109 tasks
        # in `claimed` simultaneously, every session competing for the
        # same provider, and nothing completing. `current_task_id` being a
        # single value says one-at-a-time was always the intent.
        #
        # Doing it with the subscription rather than an internal queue
        # keeps the delivery unacknowledged until the session actually
        # finishes, which is what lets a *crashed* worker's task be
        # redelivered to the next one
        # (tests/simorgh/integration/test_local_multi_worker_crash_resume.py).
        # `UNBOUNDED`: the bus's per-handler default (300s) is a guard
        # against a hung handler, and it was silently the wall budget of
        # every task -- a session past 300s was cancelled mid-flight by
        # the bus, its work discarded, and the task re-run after the
        # lease expired (live, 2026-09-10). The session's own step
        # budget, think/tool timeouts and lease heartbeat are the bound.
        self._subs.append(await self._bus.subscribe(
            topics.TASK_AVAILABLE, self._on_available, group="workers", max_inflight=1,
            max_handler_seconds=UNBOUNDED,
        ))
        self._subs.append(await self._bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))
        self._subs.append(await self._bus.subscribe(topics.TASK_CANCEL, self._on_cancel))

    async def stop(self) -> None:
        for s in self._subs:
            await s.unsubscribe()
        self._subs.clear()

    def _is_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled

    def _requeued(self, task_id: str) -> bool:
        """Whether the cancel that stopped this task was a preemption.

        A preempted task is not failed: Planning has already put it back
        on the queue, so reporting an outcome for it would overwrite
        that with a terminal status."""
        return bool(self._cancelled.get(task_id))

    def _forget_cancel(self, task_id: str) -> None:
        """A cancel is spent once the session it stopped has ended.

        It used to live until the 256-entry cap evicted it, and with one
        worker a requeued task always comes back to the SAME worker --
        so a preempted task was claimed, killed at step 0 in 0.01s, and
        left terminally failed seven seconds after being requeued.
        Preemption destroyed exactly the work it was supposed to
        postpone (observer, 2026-09-08)."""
        self._cancelled.pop(task_id, None)

    async def _on_cancel(self, message: Message) -> None:
        """Remember the id; the session loop notices between steps.

        Not `task.cancel` -> kill the coroutine: cancelling mid-step
        would abandon an applied-but-uncommitted edit in the tree, which
        is the exact shape of the 2026-09-07 false completion. Stopping
        at a step boundary lets `SessionRunner`'s own cleanup run.
        """
        task_id = message.payload.get("task_id", "")
        if not task_id:
            return
        self._cancelled[task_id] = bool(message.payload.get("requeue"))
        while len(self._cancelled) > _CANCEL_MEMORY:
            self._cancelled.popitem(last=False)

    async def _on_state_changed(self, message: Message) -> None:
        self._paused = message.payload.get("state") == "paused"

    async def _on_available(self, message: Message) -> None:
        task_id = message.payload["task_id"]
        kind = message.payload.get("kind", "chat")
        claim_req = Message.new(
            topics.TASK_CLAIM, source=self._bus.source,
            payload={"task_id": task_id, "worker_id": self.worker_id},
            partition_key=f"task:{task_id}", trace_id=task_id, clock=self._clock,
        )
        reply = await self._bus.request_or_error(claim_req, timeout=2.0)
        if reply.payload.get("ok") is False or not reply.payload.get("granted", False):
            return  # another worker claimed it first, or Planning has no Planning subsystem yet in this test

        task = reply.payload.get("task") or {}
        mode = task.get("mode", "execute")
        description = await self._full_description(task)
        profile = profiles.for_task(kind, mode)
        session = Session(
            task_id=task_id, kind=kind, mode=mode, profile=profile,
            worker_id=self.worker_id, user_text=description, subject=task.get("subject"),
        )
        session.budget.max_steps = step_cap(task.get("max_steps"), profile.max_steps)
        session.budget.max_revisions = profile.max_revisions

        await restore_session(session, self._ledger)

        lease_seconds = float(message.payload.get("lease_seconds", 600.0))
        heartbeat = asyncio.create_task(self._heartbeat_loop(task_id, lease_seconds))
        try:
            outcome = await self.run(session, user_text=description)
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
        requeued = self._requeued(task_id)
        self._forget_cancel(task_id)
        if requeued:
            # Preemption, not rejection. Planning moved the task back to
            # `available` before we ever stopped; reporting an outcome
            # here would transition it to a terminal status instead
            # (and `available -> failed` is not even legal, so it
            # raised, was swallowed, and the record survived by
            # accident).
            return
        await self._report(session, outcome)

    async def _full_description(self, task: dict) -> str:
        """The task's brief, whole.

        A description longer than the Ledger's inline limit is stored as
        a blob and the wire carries a preview (`planning/store.py::
        _inline_or_blob`). Prompting with the preview would mean working
        from an instruction that stops mid-sentence, with nothing in the
        session saying so -- so the ref is read back here, and if it
        cannot be read the preview is used AND the failure is on the
        record, rather than the model quietly getting less than it was
        sent."""
        description = task.get("description", "")
        ref = task.get("description_ref") or ""
        if not ref or self._ledger is None:
            return description
        try:
            return (await self._ledger.get_blob(ref)).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 -- a readable preview beats no task
            logger = getattr(self._bus, "logger", None)
            if logger is not None:
                logger.warning("orchestration.description_ref_unreadable",
                               task_id=task.get("task_id"), ref=ref, error=repr(exc))
            return description

    async def _heartbeat_loop(self, task_id: str, lease_seconds: float) -> None:
        """Keeps a claimed task's lease alive for as long as we are still
        inside a single step's `await`.

        `TASK_STEP` (`planning.service._on_task_step` ->
        `TaskStore.refresh_lease`) only fires once a tool call
        *completes* -- so a single step that outlives `lease_seconds` on
        its own (a full `run_tests`, a stuck `web_fetch`, a cold-start
        `cognition.think`) got no renewal at all until it finished, and
        `Scheduler.scan_leases` treats an expired lease as available:
        it could hand this exact task_id to a second worker while we
        were still mid-step. Started the moment a claim is granted,
        cancelled in `_on_available`'s `finally` the instant the session
        ends, whatever the outcome -- so it never outlives the task it
        is renewing.
        """
        # Configured `heartbeat_s`, but never slower than a third of
        # THIS task's own lease -- a short `lease_seconds` (a test, or a
        # deliberately tight deployment) must not be outrun by a
        # `heartbeat_s` sized for the 600s default.
        interval = max(0.1, min(self._heartbeat_s, lease_seconds / 3.0))
        while True:
            await asyncio.sleep(interval)
            msg = Message.new(
                topics.TASK_LEASE_HEARTBEAT, source=self._bus.source,
                payload={"task_id": task_id, "worker_id": self.worker_id},
                partition_key=f"task:{task_id}", trace_id=task_id, clock=self._clock,
            )
            await self._bus.publish(msg)

    async def run(self, session: Session, *, user_text: str = "") -> Outcome:
        self.current_task_id, self.current_kind = session.task_id, session.kind
        try:
            return await self._runner.run(session, user_text=user_text)
        finally:
            self.current_task_id, self.current_kind = None, None

    async def run_percept_chat(self, session_id: str, text: str) -> None:
        """Flow 1 (02 section 5): a plain conversational percept has no
        Planning task behind it -- only the `batch`/`evolve`/`plan`
        commands go through `intent.goal.stated` -> Intake -> a real
        task. Runs an ephemeral chat session directly, keyed by the
        percept's own `session_id` (the same value Interface is already
        waiting on in `_pending_turns`), and reuses `run`/`_report`
        unchanged: every `TASK_*` handler this fires (`_on_task_started`
        et al. in `simorgh.planning.service`) checks `task is None` first,
        so an id Planning never created is always a safe no-op there --
        the one part of `_report` this session actually needs is its
        `if session.kind == "chat": publish turn.completed` branch.
        """
        profile = profiles.for_task("chat", "execute")
        session = Session(
            task_id=session_id, kind="chat", mode="execute", profile=profile,
            worker_id=self.worker_id, user_text=text,
        )
        session.budget.max_steps = profile.max_steps
        session.budget.max_revisions = profile.max_revisions
        try:
            outcome = await self.run(session, user_text=text)
        except asyncio.CancelledError:
            # A cancelled chat still owes the human an answer, or the
            # Interface waits on a future that never resolves and the turn
            # shows as running forever (watched chat trial, 2026-09-07).
            outcome = Outcome("failed", reason="the turn was cancelled before it finished")
            await self._report(session, outcome)
            raise
        except Exception as exc:  # noqa: BLE001 -- same: never let a turn vanish
            outcome = Outcome("failed", reason=f"the turn crashed: {exc!r}")
        await self._report(session, outcome)

    async def _artifacts_for(self, session: Session, outcome: Outcome) -> list[str]:
        """A plan session's whole product is the plan text, and Planning
        reads it from an artifact blob shaped `{"steps_text": ...}`
        (`_on_plan_worker_result`).

        Live-caught 2026-09-07: this list was the literal `[]`, always. So
        Planning always resolved an empty plan, `parse_steps` always
        returned nothing, and every project took the "decomposition
        produced no real steps -- will retry" branch. All 21 of the
        creator's projects sat at `0/0 steps` and no task in the entire
        ledger had a `parent_id`: not one project had ever been
        decomposed, and none could have been.

        Only plan sessions produce one. Every other kind reports its
        result in `result_summary` as before.
        """
        if session.mode != "plan" or not outcome.result_summary:
            return []
        try:
            blob = json.dumps({
                "goal": session.user_text, "steps_text": outcome.result_summary,
            }).encode("utf-8")
            return [await self._ledger.put_blob(blob, content_type="application/json")]
        except Exception as exc:  # noqa: BLE001 -- a blob failure must not lose the completion itself
            self._log_artifact_failure(session, exc)
            return []

    def _log_artifact_failure(self, session: Session, exc: Exception) -> None:
        logger = getattr(self._bus, "logger", None)
        if logger is not None:
            logger.warning("orchestration.plan_artifact_failed", task_id=session.task_id, error=repr(exc))

    async def _report(self, session: Session, outcome: Outcome) -> None:
        if outcome.kind == "paused":
            return  # session.py already emitted task.paused
        type_ = {
            "completed": topics.TASK_COMPLETED,
            "failed": topics.TASK_FAILED,
            "blocked": topics.TASK_BLOCKED,
        }[outcome.kind]
        if outcome.kind == "completed":
            payload = {
                "task_id": session.task_id, "result_summary": outcome.result_summary,
                "artifacts": await self._artifacts_for(session, outcome),
                "verification_ref": outcome.verification_ref,
            }
            if outcome.confidence is not None:
                payload["confidence"] = outcome.confidence
        elif outcome.kind == "failed":
            payload = {"task_id": session.task_id, "reason": outcome.reason, "terminal": True, "attempts": 1}
        else:
            payload = {"task_id": session.task_id, "reason": outcome.reason}
            if outcome.result_summary:
                payload["result_summary"] = outcome.result_summary

        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}",
                          trace_id=session.task_id, clock=self._clock)
        # Live-caught (the creator: "step 1 final answer ok [31.5s]" then a
        # minute of "still thinking" and no reply): the Ledger refuses any
        # inline string over its threshold (4096 chars by default), so a
        # long real answer raised ValidationError right here -- before the
        # TASK_COMPLETED/TURN_COMPLETED publishes below -- and the finished
        # reply was never delivered. The Ledger event gets a preview plus a
        # blob ref; the bus messages keep the full text.
        event = Event.from_message(msg, f"task:{session.task_id}")
        event = await self._deoversize_for_ledger(event, ("result_summary", "reason"))
        await self._ledger.append(f"task:{session.task_id}", event)
        await self._bus.publish(msg)

        # `turn.completed` was published for `session.kind == "chat"`
        # only -- but Memory's `_on_turn_completed` is the ONLY thing
        # in the whole system that ever writes episodic memory, so
        # every research/patch/skill/project outcome went unrecorded.
        # An observer proved it live 2026-09-08: a real research task
        # ran real web searches, answered, completed -- and a follow-up
        # task asking "what did you find out before, don't research
        # again" got nothing back and re-did the whole search from
        # scratch. Publishing this for every kind, not just chat, is
        # the fix. It is safe for Interface too: `_on_turn_completed`
        # there only resolves a future keyed by `session_id` in its own
        # `_pending_turns` map, which nothing but a live chat prompt
        # ever populates -- a non-chat task_id simply finds no waiter
        # and the message is a no-op there, exactly as before.
        turn = Message.new(
            topics.TURN_COMPLETED, source=self._bus.source,
            payload={
                "session_id": session.task_id, "task_id": session.task_id,
                # `result_summary` is empty for a blocked/failed
                # outcome and `reason` used to be dropped, so 175s
                # and six real model calls surfaced to the human as
                # "(no real answer this turn -- floor reply)" --
                # indistinguishable from having no provider at all
                # (observer, 2026-09-08).
                "text": outcome.result_summary or (
                    f"I could not finish this one: {outcome.reason}" if outcome.reason else ""
                ),
                "floor": outcome.floor,
                "tool_steps": len(session.steps), "user_text": session.user_text,
            },
            partition_key=f"task:{session.task_id}", trace_id=session.task_id, clock=self._clock,
        )
        await self._bus.publish(turn)

    async def _deoversize_for_ledger(self, event: Event, fields: tuple[str, ...]) -> Event:
        """Same convention as `kernel/migrate_v1.py`'s `_deoversize` and
        the `*_ref`/`blob:<sha256>` scheme `verification/service.py` and
        `execution/service.py` already use for real code and tool output:
        any oversized field is blob-stored and renamed `<field>_ref`, with
        a short inline preview kept under the original key so a Ledger
        reader (a log viewer, `pending`) still shows something without
        fetching the blob. Only touches the Ledger's own copy of the
        payload -- the bus `Message` (and so `turn.completed`'s real
        reader, the REPL/HTTP client) always keeps the full text."""
        threshold = self._ledger.inline_threshold
        payload = dict(event.payload)
        changed = False
        for field in fields:
            value = payload.get(field)
            if isinstance(value, str) and len(value) > threshold:
                ref = await self._ledger.put_blob(value.encode("utf-8"), content_type="text/plain")
                payload[field] = value[: threshold - 1] + "…"  # -1 leaves room for the ellipsis itself
                payload[f"{field}_ref"] = ref
                changed = True
        return replace(event, payload=payload) if changed else event
