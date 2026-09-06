"""`Service(Subsystem)` for Memory (docs/blueprint/subsystems/05-memory.md
sections 5, 9): wires `memory.retrieve`/`.store` and consolidation on
`system.tick.sleep`."""

from __future__ import annotations

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
    consumes: tuple[str, ...] = (topics.MEMORY_RETRIEVE, topics.MEMORY_STORE, topics.SYSTEM_TICK_SLEEP)
    produces: tuple[str, ...] = (
        topics.MEMORY_RETRIEVE_REPLY, topics.MEMORY_STORED, topics.MEMORY_CONTRADICTION_FLAGGED,
        topics.MEMORY_CONSOLIDATED, topics.MEMORY_FORGOTTEN,
    )

    def __init__(self, *, config: Config | None = None, keep_per_kind: dict[str, int] | None = None) -> None:
        self._config = config or Config()
        self._keep_per_kind = keep_per_kind or dict(DEFAULT_KEEP_PER_KIND)

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self.engine = MemoryEngine(ctx.ledger, self._config, clock=ctx.clock)
        self._sub_retrieve = await ctx.bus.subscribe(topics.MEMORY_RETRIEVE, self._on_retrieve)
        self._sub_store = await ctx.bus.subscribe(topics.MEMORY_STORE, self._on_store)
        self._sub_sleep = await ctx.bus.subscribe(topics.SYSTEM_TICK_SLEEP, self._on_sleep)

    async def stop(self) -> None:
        for sub in (self._sub_retrieve, self._sub_store, self._sub_sleep):
            await sub.unsubscribe()

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
                {"ref": i.ref, "kind": i.kind, "content": i.content,
                 "score": i.score_confidence(now=self._ctx.clock.now(), half_life_seconds=self._config.half_life_seconds),
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

    async def _on_sleep(self, message: Message) -> None:
        window = message.payload.get("window_seconds")
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
