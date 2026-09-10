"""`Service(Subsystem)` for Memory (docs/blueprint/subsystems/05-memory.md
sections 5, 9): wires `memory.retrieve`/`.store` and consolidation on
`system.tick.sleep`."""

from __future__ import annotations

import asyncio

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from .config import Config
from .consolidation import run_consolidation
from .store import MemoryEngine

VERSION = "0.1.0"
DEFAULT_KEEP_PER_KIND = {"episodic": 2_000, "semantic": 2_000, "procedural": 500}


class Service:
    name = "memory"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.MEMORY_RETRIEVE, topics.MEMORY_STORE, topics.SYSTEM_TICK_SLEEP, topics.TURN_COMPLETED,
        topics.SYSTEM_TICK_SECOND,
    )
    produces: tuple[str, ...] = (
        topics.MEMORY_RETRIEVE_REPLY, topics.MEMORY_STORED, topics.MEMORY_CONTRADICTION_FLAGGED,
        topics.MEMORY_CONSOLIDATED, topics.MEMORY_FORGOTTEN, topics.SYSTEM_METRICS,
    )

    def __init__(self, *, config: Config | None = None, keep_per_kind: dict[str, int] | None = None) -> None:
        self._config_from_caller = config
        self._config = config or Config()
        self._keep_per_kind = keep_per_kind or dict(DEFAULT_KEEP_PER_KIND)
        self._tick_seconds = 0
        self._first_consolidation: asyncio.Task | None = None
        self._warm: asyncio.Task | None = None

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
        self.engine = MemoryEngine(ctx.ledger, self._config, clock=ctx.clock)
        self._sub_retrieve = await ctx.bus.subscribe(topics.MEMORY_RETRIEVE, self._on_retrieve)
        self._sub_store = await ctx.bus.subscribe(topics.MEMORY_STORE, self._on_store)
        self._sub_sleep = await ctx.bus.subscribe(topics.SYSTEM_TICK_SLEEP, self._on_sleep)
        self._sub_turn = await ctx.bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed)
        self._sub_tick = await ctx.bus.subscribe(topics.SYSTEM_TICK_SECOND, self._on_tick)
        # Boot is the right place to pay for the recall index -- see
        # `MemoryEngine.warm`. Not awaited: a large store takes a
        # noticeable moment and start() must not hold the Kernel up for
        # it. A recall that arrives first simply waits on the same work.
        self._warm = asyncio.create_task(self._warm_index(), name="memory-index-warm")
        if self._config.consolidate_after_start_s > 0:
            self._first_consolidation = asyncio.create_task(
                self._consolidate_after_start(), name="memory-first-consolidation")

    async def _warm_index(self) -> None:
        try:
            records = await self.engine.warm()
            self._ctx.logger.info("memory.index_warmed", records=records)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- an unwarmed index is slow, not broken
            self._ctx.logger.warning("memory.index_warm_failed", error=repr(exc))

    async def stop(self) -> None:
        if self._warm is not None:
            self._warm.cancel()
            try:
                await self._warm
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._warm = None
        if self._first_consolidation is not None:
            self._first_consolidation.cancel()
            try:
                await self._first_consolidation
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise from a background pass
                pass
            self._first_consolidation = None
        for sub in (self._sub_retrieve, self._sub_store, self._sub_sleep, self._sub_turn, self._sub_tick):
            await sub.unsubscribe()

    async def _consolidate_after_start(self) -> None:
        """One consolidation pass shortly after boot.

        `DEFAULT_KEEP_PER_KIND` describes a steady state of 2,000
        records per kind, and `retrieve`'s cost is a function of exactly
        that number -- but nothing reached it. The only caller of
        `run_consolidation` was `system.tick.sleep`, and the Kernel's
        sleep loop waits a full `sleep_every_s` (6 hours, `kernel/api.py`)
        before its first tick and then `continue`s past it if the system
        is not RUNNING at that moment. Every session shorter than six
        hours -- which is nearly all of them -- pruned nothing and
        flagged no contradictions, so memory only ever grew. The Ledger
        hit the identical bug on 2026-09-07 (190,865 expired streams
        still on disk) and fixed it with `compact_after_start_s`; this
        is the same fix for the same reason.

        Deliberately not inside `start()`: the pass reads every durable
        stream and may ask Cognition for a distillation, and boot is not
        the place to wait for either. A failure is logged and dropped --
        memory that cannot consolidate still recalls.
        """
        try:
            await asyncio.sleep(self._config.consolidate_after_start_s)
            await self._consolidate(window=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._ctx.logger.warning("memory.first_consolidation_failed", error=repr(exc))

    async def health(self) -> Health:
        return Health.ok()

    async def _on_retrieve(self, message: Message) -> None:
        payload = message.payload
        items, truncated = await self.engine.retrieve(
            query=payload.get("query", ""), kinds=payload.get("kinds", []),
            k=payload.get("k", self._config.default_k), filters=payload.get("filters"),
        )
        await self._ctx.bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
            "items": [
                # `score` is how well this matched the query; the decayed
                # confidence is reported beside it under a name that says
                # what it is. Until 2026-09-10 `score` WAS the decay, so a
                # no-hit query answered with two identical 1.0000s and
                # nothing downstream could tell relevant from recent.
                {"ref": i.ref, "kind": i.kind, "content": i.content,
                 "score": i.score,
                 "confidence_now": i.score_confidence(
                     now=self._ctx.clock.now(), half_life_seconds=self._config.half_life_seconds),
                 "confidence": i.confidence, "ts": i.ts}
                for i in items
            ],
            "truncated": truncated,
        })

    async def _on_store(self, message: Message) -> None:
        payload = message.payload
        if payload["kind"] == "working":
            # working memory is a session-scoped rolling window, not a
            # durable item -- `content` is treated as the response half
            # of a turn; a bare store with no paired request is still
            # recorded (empty request) so nothing is silently dropped.
            session_id = (payload.get("tags") or [None])[0] or "default"
            self.engine.working.add(session_id, "", payload["content"], ts=self._ctx.clock.now())
            return
        ref = await self.engine.store(
            kind=payload["kind"], content=payload["content"], tags=payload.get("tags", []),
            source_ref=payload.get("source_ref", ""), confidence=payload.get("confidence"),
        )
        await self._ctx.bus.publish(Message.new(
            topics.MEMORY_STORED, source=self._ctx.source, payload={"ref": ref, "kind": payload["kind"]},
        ))

    async def _on_turn_completed(self, message: Message) -> None:
        """Flow 1's own episodic-write arrow (02 section 5), closing the
        gap milestone 104 left open: `turn.completed` didn't carry the
        human's own words until that same milestone added `user_text`
        (optional, so an older producer still validates) -- with nothing
        said this turn there is nothing worth remembering, so an empty
        pair is skipped rather than filling episodic memory with blanks
        from the honest-floor path (`floor: true`, `text: ""`)."""
        payload = message.payload
        user_text = payload.get("user_text", "")
        reply_text = payload.get("text", "")
        if not user_text and not reply_text:
            return
        content = f"User: {user_text}\nSim: {reply_text}" if user_text else reply_text
        ref = await self.engine.store(
            kind="episodic", content=content, tags=[payload.get("session_id", "")],
            source_ref=payload.get("task_id", ""), confidence=None,
        )
        await self._ctx.bus.publish(Message.new(
            topics.MEMORY_STORED, source=self._ctx.source, payload={"ref": ref, "kind": "episodic"},
        ))

    async def _on_tick(self, message: Message) -> None:
        # A dashboard's "what does Sim remember" view (02-system-
        # architecture.md section 6.2), on the same `system.metrics`
        # channel every other subsystem's own gauges already use --
        # every 30s, matching Cognition's own tick throttle, not every
        # second tick (a stream read per kind is cheap but not free).
        self._tick_seconds += 1
        if self._tick_seconds % 30 != 0:
            return
        counts = await self.engine.counts()
        await self._ctx.bus.publish(Message.new(
            topics.SYSTEM_METRICS, source=self._ctx.source,
            payload={"subsystem": "memory", "counters": {}, "gauges": {"records": counts}},
        ))

    async def _on_sleep(self, message: Message) -> None:
        await self._consolidate(window=message.payload.get("window_seconds"))

    async def _consolidate(self, *, window: float | None) -> None:
        since = self._ctx.clock.now() - window if window else None
        report = await run_consolidation(
            self.engine, bus=self._ctx.bus, source=self._ctx.source, keep_per_kind=self._keep_per_kind, since=since,
        )
        for ref_a, ref_b, evidence in report.contradictions:
            await self._ctx.bus.publish(Message.new(
                topics.MEMORY_CONTRADICTION_FLAGGED, source=self._ctx.source,
                payload={"ref_a": ref_a, "ref_b": ref_b, "evidence": evidence, "confidence_after": 0.5},
            ))
        await self._ctx.bus.publish(Message.new(
            topics.MEMORY_CONSOLIDATED, source=self._ctx.source,
            payload={"window": window or 0.0, "distilled": 1 if report.distilled else 0, "pruned": sum(report.pruned.values())},
        ))
        pruned_total = sum(report.pruned.values())
        if pruned_total:
            await self._ctx.bus.publish(Message.new(
                topics.MEMORY_FORGOTTEN, source=self._ctx.source,
                payload={"refs": [], "reason": f"consolidation pruned {pruned_total} record(s) across {len(report.pruned)} kind(s)"},
            ))


__all__ = ["Service", "VERSION"]
