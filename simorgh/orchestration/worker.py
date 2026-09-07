"""The `Worker` (16 section 3.4/5): claims one `task.available` command at
a time (consumer group `workers`, competing-consumer -- multiple Worker
instances share the group and never double-claim the same delivery), runs
its Session to a terminal Outcome, and reports it. Tracks `system.state.
changed` so an in-flight Session can check `is_paused()` between steps
(Flow 5) -- lease-heartbeat renewal and wall-clock budgets are not
implemented this session (see README).
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message

from . import profiles
from .api import Outcome, Session
from .context import DEFAULT_TIMEOUT_S
from .resume import restore_step_count
from .session import SessionRunner


class Worker:
    def __init__(
        self, bus, ledger, *, clock=None, worker_id: str | None = None,
        assemble_timeout_s: float = DEFAULT_TIMEOUT_S, think_timeout_s: float | None = None,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._clock = clock
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
            assemble_timeout_s=assemble_timeout_s, **runner_kwargs,
        )
        self._subs: list = []

    async def start(self) -> None:
        self._subs.append(await self._bus.subscribe(topics.TASK_AVAILABLE, self._on_available, group="workers"))
        self._subs.append(await self._bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))

    async def stop(self) -> None:
        for s in self._subs:
            await s.unsubscribe()
        self._subs.clear()

    async def _on_state_changed(self, message: Message) -> None:
        self._paused = message.payload.get("state") == "paused"

    async def _on_available(self, message: Message) -> None:
        task_id = message.payload["task_id"]
        kind = message.payload.get("kind", "chat")
        claim_req = Message.new(
            topics.TASK_CLAIM, source=self._bus.source,
            payload={"task_id": task_id, "worker_id": self.worker_id},
            partition_key=f"task:{task_id}", clock=self._clock,
        )
        reply = await self._bus.request_or_error(claim_req, timeout=2.0)
        if reply.payload.get("ok") is False or not reply.payload.get("granted", False):
            return  # another worker claimed it first, or Planning has no Planning subsystem yet in this test

        task = reply.payload.get("task") or {}
        mode = task.get("mode", "execute")
        description = task.get("description", "")
        profile = profiles.for_task(kind, mode)
        session = Session(
            task_id=task_id, kind=kind, mode=mode, profile=profile,
            worker_id=self.worker_id, user_text=description,
        )
        session.budget.max_steps = profile.max_steps
        session.budget.max_revisions = profile.max_revisions

        await restore_step_count(session, self._ledger)

        outcome = await self.run(session, user_text=description)
        await self._report(session, outcome)

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
        outcome = await self.run(session, user_text=text)
        await self._report(session, outcome)

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
                "artifacts": [], "verification_ref": outcome.verification_ref,
            }
            if outcome.confidence is not None:
                payload["confidence"] = outcome.confidence
        elif outcome.kind == "failed":
            payload = {"task_id": session.task_id, "reason": outcome.reason, "terminal": True, "attempts": 1}
        else:
            payload = {"task_id": session.task_id, "reason": outcome.reason}

        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}", clock=self._clock)
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

        if session.kind == "chat":
            turn = Message.new(
                topics.TURN_COMPLETED, source=self._bus.source,
                payload={
                    "session_id": session.task_id, "task_id": session.task_id,
                    "text": outcome.result_summary, "floor": outcome.floor,
                    "tool_steps": len(session.steps), "user_text": session.user_text,
                },
                partition_key=f"task:{session.task_id}", clock=self._clock,
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
