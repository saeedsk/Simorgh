"""Consolidation on `system.tick.sleep` (docs/blueprint/subsystems/05-
memory.md section 4): flag contradictions, prune each durable kind, and
-- if a real Cognition is reachable -- ask for a distilled semantic
summary of the window's episodic activity (`cognition.think`,
`purpose=consolidate`). Degrades honestly: no real provider answering is
a `floor:true` reply, never a fabricated distillation (principle 4.5)."""

from __future__ import annotations

from dataclasses import dataclass, field

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus

from .store import MemoryEngine


@dataclass(frozen=True)
class ConsolidationReport:
    contradictions: list[tuple[str, str, str]]
    pruned: dict[str, int] = field(default_factory=dict)
    distilled: bool = False


async def run_consolidation(
    engine: MemoryEngine, *, bus: Bus, source: str, keep_per_kind: dict[str, int],
    since: float | None = None, cognition_timeout: float = 30.0,
) -> ConsolidationReport:
    flagged = await engine.flag_contradictions(kind="semantic")
    pruned = {kind: await engine.prune(kind=kind, keep=keep) for kind, keep in keep_per_kind.items()}

    distilled = False
    filters = {"since": since} if since is not None else None
    episodic_items, _ = await engine.retrieve(query="", kinds=["episodic"], k=20, filters=filters)
    if episodic_items:
        request = Message.new(topics.COGNITION_THINK, source=source, payload={
            "purpose": "consolidate",
            "messages": [{"role": "user", "content": "\n".join(i.content for i in episodic_items)}],
            "budget": {"max_tokens": 2_000, "max_cost_usd": 0.1},
            "require_real_provider": False,
        })
        try:
            reply = await bus.request(request, timeout=cognition_timeout)
        except Exception:  # noqa: BLE001 -- cognition unreachable: skip distillation this cycle, never fabricate one
            reply = None
        if reply is not None and reply.payload.get("ok") is not False and not reply.payload.get("floor", True):
            await engine.store(kind="semantic", content=reply.payload["text"], tags=["consolidation"], source_ref="", confidence=None)
            distilled = True

    return ConsolidationReport(contradictions=flagged, pruned=pruned, distilled=distilled)


__all__ = ["ConsolidationReport", "run_consolidation"]
