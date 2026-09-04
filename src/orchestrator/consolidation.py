"""Consolidation ("sleep") mode: periodic maintenance, the way biological
sleep handles memory consolidation and waste clearance. See
docs/BIOMIMICRY.md, "Sleep."

Not a background daemon -- nothing in this codebase runs unsupervised
(Directive 5, Restraint, counsels caution around unattended autonomous
operation). `run_consolidation` is a single maintenance pass a caller (the
CLI's 'sleep' command, a future scheduler under the creator's control)
triggers explicitly, and it returns a report of what it did rather than
acting invisibly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.memory.long_term import MemoryStore
from src.orchestrator.reflection import OutcomeLog, Proposal, ReflectionAgent


@dataclass(frozen=True)
class ConsolidationReport:
    proposals: list[Proposal]
    pruned_counts: dict[str, int] = field(default_factory=dict)


def run_consolidation(
    store: MemoryStore,
    reflection_agent: ReflectionAgent | None = None,
    keep_per_kind: dict[str, int] | None = None,
) -> ConsolidationReport:
    """One maintenance pass: reflect on recent outcomes (surfacing
    proposals, same as ReflectionAgent.reflect() alone would), then prune
    each kind named in `keep_per_kind` down to its most recent N records --
    the analog of clearing stale memory rather than accumulating
    everything forever. Nothing outside `keep_per_kind` is touched.
    """
    reflection_agent = reflection_agent or ReflectionAgent(OutcomeLog(store))
    proposals = reflection_agent.reflect()

    pruned_counts = {
        kind: _prune_kind(store, kind, keep) for kind, keep in (keep_per_kind or {}).items()
    }

    return ConsolidationReport(proposals=proposals, pruned_counts=pruned_counts)


def _prune_kind(store: MemoryStore, kind: str, keep: int) -> int:
    records = store.query(kind=kind)  # most-recent-first
    stale = records[keep:] if keep >= 0 else []
    for record in stale:
        store.delete(record.id)
    return len(stale)
