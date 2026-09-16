"""Memory's internal value types (docs/blueprint/subsystems/05-memory.md
section 3.4)."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS = 30 * 24 * 60 * 60  # 30 days, ported from v1

#: Tags that say where a record CAME FROM, not what it is ABOUT.
#:
#: `flag_contradictions` groups records by their first tag, standing in
#: for v1's `metadata["subject"]`. Consolidation writes every summary
#: tagged `consolidation`, so all of them landed in one group as though
#: they shared a subject, and each pass flagged the two newest as
#: contradicting each other. Measured on the creator's ledger
#: 2026-09-16: 132 contradictions, every one semantic-vs-semantic,
#: every one between adjacent records, every one "both tagged
#: 'consolidation'" -- one per summary, for as long as Sim had been
#: running. Two summaries of two different evenings do not contradict
#: each other; they are simply two different evenings.
NOT_A_SUBJECT: frozenset = frozenset({"consolidation", "distilled"})


def subject_of(payload: dict) -> str:
    """The tag a contradiction was found under.

    New events carry `tag`. The ones already on disk do not, so it is
    read back out of the `evidence` line they do carry -- an append-only
    stream cannot be rewritten, and 132 wrong penalties had to stop
    counting without pretending they were never written.
    """
    tag = str((payload or {}).get("tag") or "")
    if tag:
        return tag
    import re

    found = re.match(r"both tagged '([^']*)'", str((payload or {}).get("evidence") or ""))
    return found.group(1) if found else ""


def is_real_contradiction(payload: dict) -> bool:
    """Whether a flagged pair should count against its records at all.

    A contradiction between two records that share only their
    provenance is not evidence about either of them.
    """
    return subject_of(payload) not in NOT_A_SUBJECT


@dataclass(frozen=True)
class MemoryItem:
    ref: str
    kind: str
    content: str
    tags: tuple[str, ...]
    confidence: float
    ts: float
    source_ref: str = ""
    # How well this item matched the query it was retrieved for, as
    # `MemoryStore._score` computed it. Set by `retrieve`, 0.0 when the
    # item did not come from a query. It used to be discarded the moment
    # after it was computed, while the reply reported decay-from-creation
    # under the name "score" -- so every fresh record scored 1.0 however
    # irrelevant, and a no-hit query answered with two perfect scores
    # (observer, 2026-09-10).
    score: float = 0.0

    def score_confidence(self, *, now: float, half_life_seconds: float, penalty: float = 1.0) -> float:
        """Exponential decay from creation, times any contradiction
        penalty folded in from later `contradiction.flagged` events (05
        section 5) -- ported from v1 `MemoryStore.score_confidence`,
        simplified to decay-from-creation only (no reconfirmation
        tracking this build session; see README "What's not built yet")."""
        if half_life_seconds <= 0:
            return self.confidence * penalty
        elapsed = max(0.0, now - self.ts)
        return self.confidence * penalty * (0.5 ** (elapsed / half_life_seconds))


@dataclass(frozen=True)
class Turn:
    request_text: str
    response_text: str
    ts: float


__all__ = [
    "NOT_A_SUBJECT", "is_real_contradiction", "subject_of","DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS", "MemoryItem", "Turn"]
