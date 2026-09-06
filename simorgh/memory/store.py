"""The memory engine (docs/blueprint/subsystems/05-memory.md sections 4-5):
episodic/semantic/procedural records as one-event-per-item Ledger streams
(`memory:episodic`, `memory:semantic`, `memory:procedural`), retrieval by
lexical+embedding similarity times confidence plus a recency term,
confidence decay ported from v1 `score_confidence`, and forgetting as a
tombstone stream rather than a physical delete -- append-only stays
append-only (principle 4.4) even for "pruning."

Working memory is deliberately NOT a Ledger stream: it is a bounded,
non-durable rolling window per session, exactly like v1's
`ShortTermMemory` -- it resets with the process, the way working memory
doesn't survive the way consolidated long-term memory does.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Clock, Ledger

from .api import MemoryItem, Turn
from .config import Config
from .embed import cosine_similarity, embed_text

KINDS = ("episodic", "semantic", "procedural")
TOMBSTONE_STREAM = "memory:tombstones"
CONTRADICTION_STREAM = "memory:contradictions"


def stream_for(kind: str) -> str:
    return f"memory:{kind}"


class WorkingMemory:
    """Per-session bounded rolling window -- the working-memory kind,
    kept in-process (never durable), ported from v1 `ShortTermMemory`."""

    def __init__(self, *, max_turns: int, max_chars: int) -> None:
        self._max_turns = max_turns
        self._max_chars = max_chars
        self._sessions: dict[str, deque[Turn]] = defaultdict(deque)

    def add(self, session_id: str, request_text: str, response_text: str, *, ts: float) -> None:
        turns = self._sessions[session_id]
        turns.append(Turn(request_text, response_text, ts))
        while len(turns) > self._max_turns:
            turns.popleft()
        while len(turns) > 1 and self._total_chars(turns) > self._max_chars:
            turns.popleft()

    def recent(self, session_id: str, limit: int | None = None) -> list[Turn]:
        turns = list(self._sessions.get(session_id, ()))
        return turns[-limit:] if limit is not None else turns

    def _total_chars(self, turns: deque[Turn]) -> int:
        return sum(len(t.request_text) + len(t.response_text) for t in turns)


class MemoryEngine:
    def __init__(self, ledger: Ledger, config: Config, *, clock: Clock) -> None:
        self._ledger = ledger
        self._config = config
        self._clock = clock
        self.working = WorkingMemory(max_turns=config.working_max_turns, max_chars=config.working_max_chars)

    # -- store -----------------------------------------------------------------------
    async def store(self, *, kind: str, content: str, tags: list[str], source_ref: str, confidence: float | None) -> str:
        stream = stream_for(kind)
        seq = await self._ledger.append(stream, Event(
            stream=stream, type="item.stored", ts=self._clock.now(), trace_id="", causation_id=None,
            idempotency_key=f"{stream}:{uuid.uuid4().hex}",
            payload={"content": content, "tags": list(tags), "source_ref": source_ref, "confidence": confidence if confidence is not None else 1.0},
        ))
        return f"{stream}:{seq}"

    # -- retrieve --------------------------------------------------------------------
    async def retrieve(self, *, query: str, kinds: list[str], k: int, filters: dict | None) -> tuple[list[MemoryItem], bool]:
        filters = filters or {}
        tombstoned = await self._tombstoned_refs()
        penalties = await self._contradiction_penalties()
        query_vec = embed_text(query) if query else None
        candidates: list[tuple[float, MemoryItem]] = []
        now = self._clock.now()

        for kind in kinds:
            if kind == "working":
                session_id = filters.get("session_id")
                if session_id:
                    for i, turn in enumerate(self.working.recent(session_id)):
                        content = f"{turn.request_text}\n{turn.response_text}"
                        item = MemoryItem(ref=f"working:{session_id}:{i}", kind="working", content=content,
                                          tags=(), confidence=1.0, ts=turn.ts)
                        candidates.append((self._score(query_vec, content, item, now, penalties.get(item.ref, 1.0)), item))
                continue
            for event in await self._ledger.read(stream_for(kind)):
                ref = f"{stream_for(kind)}:{event.seq}"
                if ref in tombstoned:
                    continue
                tags = tuple(event.payload.get("tags", []))
                if filters.get("tags") and not set(filters["tags"]) & set(tags):
                    continue
                if filters.get("since") is not None and event.ts < filters["since"]:
                    continue
                item = MemoryItem(ref=ref, kind=kind, content=event.payload.get("content", ""), tags=tags,
                                  confidence=float(event.payload.get("confidence", 1.0)), ts=event.ts,
                                  source_ref=event.payload.get("source_ref", ""))
                candidates.append((self._score(query_vec, item.content, item, now, penalties.get(ref, 1.0)), item))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        truncated = len(candidates) > k
        return [item for _, item in candidates[:k]], truncated

    def _score(self, query_vec, content: str, item: MemoryItem, now: float, penalty: float) -> float:
        similarity = cosine_similarity(query_vec, embed_text(content)) if query_vec is not None else 1.0
        confidence = item.score_confidence(now=now, half_life_seconds=self._config.half_life_seconds, penalty=penalty)
        age_days = max(0.0, now - item.ts) / 86400.0
        recency_bonus = 1.0 / (1.0 + age_days)
        return similarity * confidence + self._config.recency_weight * recency_bonus

    # -- contradiction / forgetting ----------------------------------------------------
    async def flag_contradictions(self, *, kind: str = "semantic") -> list[tuple[str, str, str]]:
        """Groups records by their first tag (the closest analog to v1's
        `metadata["subject"]`); for any group with more than one distinct
        content, flags the two most recent as contradicting -- append-only
        (a durable `contradictions` event), never a mutation of the
        original records (05 section 5, "confidence/decay")."""
        by_tag: dict[str, list[tuple[str, Event]]] = defaultdict(list)
        for event in await self._ledger.read(stream_for(kind)):
            tags = event.payload.get("tags", [])
            if not tags:
                continue
            ref = f"{stream_for(kind)}:{event.seq}"
            by_tag[tags[0]].append((ref, event))

        flagged: list[tuple[str, str, str]] = []
        for tag, items in by_tag.items():
            distinct = {e.payload.get("content") for _, e in items}
            if len(distinct) < 2:
                continue
            items.sort(key=lambda pair: pair[1].ts, reverse=True)
            (ref_a, ev_a), (ref_b, ev_b) = items[0], items[1]
            if ev_a.payload.get("content") == ev_b.payload.get("content"):
                continue
            evidence = f"both tagged {tag!r}: {ev_a.payload.get('content')!r} vs {ev_b.payload.get('content')!r}"
            await self._ledger.append(CONTRADICTION_STREAM, Event(
                stream=CONTRADICTION_STREAM, type="flagged", ts=self._clock.now(), trace_id="", causation_id=None,
                idempotency_key=f"contradiction:{ref_a}:{ref_b}",
                payload={"ref_a": ref_a, "ref_b": ref_b, "evidence": evidence},
            ))
            flagged.append((ref_a, ref_b, evidence))
        return flagged

    async def forget(self, refs: list[str], *, reason: str) -> None:
        await self._ledger.append(TOMBSTONE_STREAM, Event(
            stream=TOMBSTONE_STREAM, type="forgotten", ts=self._clock.now(), trace_id="", causation_id=None,
            payload={"refs": list(refs), "reason": reason},
        ))

    async def prune(self, *, kind: str, keep: int) -> int:
        """v1 `_prune_kind`: tombstone every record of `kind` past the
        most recent `keep` (by score-confidence, not just insertion
        order) -- a "forgotten" event, never a physical delete."""
        now = self._clock.now()
        penalties = await self._contradiction_penalties()
        scored = []
        for event in await self._ledger.read(stream_for(kind)):
            ref = f"{stream_for(kind)}:{event.seq}"
            item = MemoryItem(ref=ref, kind=kind, content=event.payload.get("content", ""),
                              tags=tuple(event.payload.get("tags", [])), confidence=float(event.payload.get("confidence", 1.0)),
                              ts=event.ts)
            scored.append((item.score_confidence(now=now, half_life_seconds=self._config.half_life_seconds, penalty=penalties.get(ref, 1.0)), ref))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        stale = [ref for _, ref in scored[keep:]] if keep >= 0 else []
        if stale:
            await self.forget(stale, reason=f"pruned below top {keep} of kind={kind}")
        return len(stale)

    async def counts(self) -> dict[str, int]:
        """Live (non-tombstoned) record count per durable kind -- a
        dashboard's "what does Sim remember" view (02-system-architecture.md
        section 6.2), not anything `retrieve()`'s own scoring/truncation
        needs, so kept as its own cheap pass over each kind's stream."""
        tombstoned = await self._tombstoned_refs()
        counts: dict[str, int] = {}
        for kind in KINDS:
            stream = stream_for(kind)
            events = await self._ledger.read(stream)
            counts[kind] = sum(1 for e in events if f"{stream}:{e.seq}" not in tombstoned)
        return counts

    async def _tombstoned_refs(self) -> set[str]:
        refs: set[str] = set()
        for event in await self._ledger.read(TOMBSTONE_STREAM):
            refs.update(event.payload.get("refs", []))
        return refs

    async def _contradiction_penalties(self) -> dict[str, float]:
        penalties: dict[str, float] = {}
        for event in await self._ledger.read(CONTRADICTION_STREAM):
            penalties[event.payload["ref_a"]] = penalties.get(event.payload["ref_a"], 1.0) * 0.5
            penalties[event.payload["ref_b"]] = penalties.get(event.payload["ref_b"], 1.0) * 0.5
        return penalties


__all__ = ["CONTRADICTION_STREAM", "KINDS", "MemoryEngine", "TOMBSTONE_STREAM", "WorkingMemory", "stream_for"]
