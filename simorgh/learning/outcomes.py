"""`OutcomeRecorder`: turns `task.completed` / `task.failed` / `task.blocked`
(the terminal, or not-yet-terminal-but-informative, facts about a task)
into `learn:outcomes` events and keeps `CompetenceTable` current (spec
section 5.1). `task_type` is derived from the task's own `created` event
on its `task:<id>` Ledger stream -- Planning owns that stream for
writing, but every subsystem may read it (only publish is restricted,
section 9 of `03`) -- rather than guessed from the terminal message,
which does not carry `kind`/`subject`. `strategy` is read from
`learn:patch:<task_id>` if this pipeline ran the task, else omitted
(never guessed).
"""

from __future__ import annotations

import time
from typing import Any

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.ledger.client import LedgerClient

from .competence import CompetenceTable
from .config import Config

_MAX_VERIFY_CACHE = 500


class OutcomeRecorder:
    def __init__(self, *, ledger: LedgerClient, competence: CompetenceTable, config: Config,
                 clock=None, publish=None) -> None:
        self._ledger = ledger
        self._competence = competence
        self._config = config
        self._clock = clock or time.time
        self._publish = publish  # async fn(type, payload) -> None; set by Service
        self._verify_cache: dict[str, dict] = {}
        self._verify_order: list[str] = []

    def cache_verify_result(self, payload: dict) -> None:
        vid = payload["verification_id"]
        self._verify_cache[vid] = payload
        self._verify_order.append(vid)
        while len(self._verify_order) > _MAX_VERIFY_CACHE:
            stale = self._verify_order.pop(0)
            self._verify_cache.pop(stale, None)

    async def _task_type_and_strategy(self, task_id: str) -> tuple[str, str | None]:
        task_type = "unknown"
        try:
            events = await self._ledger.read(f"task:{task_id}", limit=1)
            if events:
                p = events[0].payload
                kind = p.get("kind", "unknown")
                subject = p.get("subject")
                task_type = f"{kind}:{_area(subject)}" if subject else kind
        except Exception:  # noqa: BLE001 -- a lookup failure must never block recording
            pass
        strategy = None
        try:
            events = await self._ledger.read(f"learn:patch:{task_id}", limit=None)
            for e in events:
                if e.type == "started" and "strategy" in e.payload:
                    strategy = e.payload["strategy"]
        except Exception:  # noqa: BLE001
            pass
        return task_type, strategy

    async def on_task_completed(self, message: Message) -> None:
        p = message.payload
        task_id = p["task_id"]
        task_type, strategy = await self._task_type_and_strategy(task_id)
        verdict = "unknown"
        vref = p.get("verification_ref")
        if vref and vref in self._verify_cache:
            verdict = self._verify_cache[vref]["verdict"]
        await self._record(task_id=task_id, task_type=task_type, succeeded=True, weight=1.0,
                            verdict=verdict, cost_usd=0.0, duration_s=0.0, strategy=strategy,
                            stated_confidence=p.get("confidence"))

    async def on_task_failed(self, message: Message) -> None:
        p = message.payload
        task_id = p["task_id"]
        task_type, strategy = await self._task_type_and_strategy(task_id)
        await self._record(task_id=task_id, task_type=task_type, succeeded=False, weight=1.0,
                            verdict="failed", cost_usd=0.0, duration_s=0.0, strategy=strategy,
                            stated_confidence=None)

    async def on_task_blocked(self, message: Message) -> None:
        p = message.payload
        task_id = p["task_id"]
        task_type, strategy = await self._task_type_and_strategy(task_id)
        await self._record(task_id=task_id, task_type=task_type, succeeded=False,
                            weight=self._config.blocked_sample_weight, verdict="blocked",
                            cost_usd=0.0, duration_s=0.0, strategy=strategy, stated_confidence=None,
                            event_type="blocked")

    async def _record(self, *, task_id: str, task_type: str, succeeded: bool, weight: float, verdict: str,
                       cost_usd: float, duration_s: float, strategy: str | None,
                       stated_confidence: float | None, event_type: str = "completed") -> None:
        payload = {
            "task_id": task_id, "task_type": task_type, "succeeded": succeeded, "weight": weight,
            "verdict": verdict, "cost_usd": cost_usd, "duration_s": duration_s, "ts": self._clock(),
        }
        if strategy:
            payload["strategy"] = strategy
        if stated_confidence is not None:
            payload["stated_confidence"] = stated_confidence
        event = Event(stream="learn:outcomes", type="outcome", ts=self._clock(), trace_id=task_id,
                      causation_id=None, payload=payload, idempotency_key=f"{task_id}:{event_type}")
        seq = await self._ledger.append("learn:outcomes", event)
        # idempotency: a duplicate append returns the *existing* seq without
        # writing -- only fold into the live projection on a genuine new seq,
        # so a redelivered task.completed can never double-count.
        if seq > self._competence.applied_seq:
            self._competence.apply(Event(**{**event.__dict__, "seq": seq}))
            self._competence.applied_seq = seq
        if self._publish is not None:
            recorded: dict[str, Any] = {
                "task_id": task_id, "task_type": task_type, "succeeded": succeeded,
                "verdict": verdict, "cost_usd": cost_usd, "duration_s": duration_s,
            }
            if strategy:
                recorded["strategy"] = strategy
            if stated_confidence is not None:
                recorded["confidence"] = stated_confidence
            await self._publish(topics.LEARN_OUTCOME_RECORDED, recorded)
            await self._publish(topics.LEARN_COMPETENCE_UPDATED, {
                "task_type": task_type,
                "success_rate": self._competence.success_rate(task_type),
                "calibration": self._competence.calibration(task_type),
                "samples": self._competence.samples(task_type),
            })


def _area(subject: str) -> str:
    """`src/memory/retrieval.py` -> `src/memory` (spec section 5.1)."""
    parts = subject.split("/")
    return "/".join(parts[:2]) if len(parts) > 1 else subject
