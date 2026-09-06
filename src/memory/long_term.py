"""Persistent, durable memory for Simorgh.

Continuity of self, per docs/SOUL.md's Philosophical Grounding, is
continuity of *record* rather than continuity of process: whatever process
is currently running should be able to reload the same memory a prior
process wrote. MemoryStore is the interface that guarantees that; the
concrete backend can be swapped (local disk today, a redundant multi-cloud
object store later -- see docs/EVOLUTION.md) without touching callers.
"""

from __future__ import annotations

import abc
import functools
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS = 30 * 24 * 60 * 60


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@functools.lru_cache(maxsize=4096)
def embed_text(text: str, dim: int = _EMBED_DIM) -> tuple[float, ...]:
    """Lightweight, dependency-free semantic embedding via the hashing
    trick: each token is hashed into one of `dim` buckets and accumulated,
    then the resulting vector is L2-normalized. This is a stdlib-only
    stand-in for a learned embedding model -- it captures shared
    vocabulary between texts (so paraphrases with overlapping words score
    as similar) without any network call or third-party model.

    Cached: the same (text, dim) pair recurs often -- semantic_search
    re-embeds every candidate record on every call -- so memoizing avoids
    re-hashing unchanged record content repeatedly.
    """
    vector = [0.0] * dim
    for token in _tokenize(text):
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dim
        vector[bucket] += 1.0
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(component / norm for component in vector)


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass(frozen=True)
class MemoryRecord:
    """One durable fact Simorgh has learned or experienced.

    `kind` is a free-form label; conventional values are "episodic"
    (something that happened), "semantic" (a fact learned), "procedural"
    (a skill or how-to), "outcome" (the result of a dispatched action, see
    src/orchestrator/reflection.py), and "lineage" (a record of a
    self-modification).

    Episodic records may carry a `metadata["antecedent_ids"]` list naming
    the ids of records that causally preceded this one (e.g. the failure
    that led to this outcome), so planning can walk cause -> effect chains
    instead of relying on keyword recency alone. Use MemoryStore.link_causal
    to set this and MemoryStore.causes_of / consequences_of to walk it.
    """

    id: str
    kind: str
    content: str
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(kind: str, content: str, **metadata: Any) -> "MemoryRecord":
        return MemoryRecord(
            id=str(uuid.uuid4()),
            kind=kind,
            content=content,
            created_at=time.time(),
            metadata=metadata,
        )


class MemoryStore(abc.ABC):
    """Interface for durable memory. Implementations must make `add`
    durable before returning -- a crash immediately after `add()` must not
    lose the record.
    """

    @abc.abstractmethod
    def add(self, record: MemoryRecord) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def get(self, record_id: str) -> MemoryRecord | None:
        raise NotImplementedError

    @abc.abstractmethod
    def query(
        self, kind: str | None = None, limit: int | None = None
    ) -> list[MemoryRecord]:
        """Return records, most recent first, optionally filtered by kind."""
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, record_id: str) -> bool:
        """Permanently remove a record. Returns True if it existed. Used
        for consolidation/pruning (src/orchestrator/consolidation.py), not
        by normal request-handling code paths.
        """
        raise NotImplementedError

    def remember(self, kind: str, content: str, **metadata: Any) -> MemoryRecord:
        """Convenience: build and store a MemoryRecord in one call."""
        record = MemoryRecord.create(kind, content, **metadata)
        self.add(record)
        return record

    def semantic_search(
        self,
        query_text: str,
        kind: str | None = None,
        limit: int = 10,
        min_similarity: float = 0.0,
    ) -> list[MemoryRecord]:
        """Return records most semantically similar to `query_text`,
        ranked by cosine similarity of hashing-trick embeddings
        (see embed_text) rather than recency or exact keyword match --
        so a query surfaces records that share vocabulary/context even
        if worded differently, and doesn't just return the newest ones.

        Ranking multiplies similarity by score_confidence, so a stale or
        repeatedly-contradicted record (see score_confidence,
        flag_contradiction) sinks in results well before reconsolidate
        gets around to pruning it -- confidence decay affects what
        callers see immediately, not just what survives consolidation.

        min_similarity filters on raw semantic similarity, not the
        confidence-weighted score, so it still means "semantically
        relevant enough" regardless of a record's current confidence.

        Ties and near-ties fall back to recency: `query()` already
        returns records newest-first, and Python's sort is stable, so
        equally-ranked records keep that relative order.
        """
        query_vector = embed_text(query_text)
        candidates = self.query(kind=kind)
        scored = [
            (record, cosine_similarity(query_vector, embed_text(record.content)))
            for record in candidates
        ]
        scored = [pair for pair in scored if pair[1] >= min_similarity]
        scored.sort(key=lambda pair: pair[1] * self.score_confidence(pair[0]), reverse=True)
        return [record for record, _ in scored[:limit]]

    def _replace(self, record: MemoryRecord) -> None:
        """Durably update an existing record's content in place.

        Must preserve the record's position among other records for
        recency-ordered `query()` results -- unlike delete+add, this must
        not make an untouched record appear "most recent". Default falls
        back to delete+add (weaker: briefly loses the record on crash, and
        reorders it); subclasses backed by an ordered on-disk log should
        override this for stronger crash safety and stable ordering.
        """
        self.delete(record.id)
        self.add(record)

    def link_causal(self, consequence_id: str, antecedent_id: str) -> None:
        """Tag `consequence_id` as causally following from `antecedent_id`.

        Stored as a `metadata["antecedent_ids"]` list on the consequence
        record, updated via `_replace` so subclasses don't each need to
        implement in-place metadata updates, and so the record's recency
        ordering isn't disturbed just because it was causally linked.
        """
        record = self.get(consequence_id)
        if record is None:
            raise KeyError(consequence_id)
        antecedent_ids = list(record.metadata.get("antecedent_ids", []))
        if antecedent_id not in antecedent_ids:
            antecedent_ids.append(antecedent_id)
        updated = MemoryRecord(
            id=record.id,
            kind=record.kind,
            content=record.content,
            created_at=record.created_at,
            metadata={**record.metadata, "antecedent_ids": antecedent_ids},
        )
        self._replace(updated)

    def causes_of(self, record_id: str) -> list[MemoryRecord]:
        """Return the antecedent records tagged as causes of `record_id`."""
        record = self.get(record_id)
        if record is None:
            return []
        causes = []
        for antecedent_id in record.metadata.get("antecedent_ids", []):
            antecedent = self.get(antecedent_id)
            if antecedent is not None:
                causes.append(antecedent)
        return causes

    def consequences_of(self, record_id: str) -> list[MemoryRecord]:
        """Return records that name `record_id` as a causal antecedent."""
        return [
            record
            for record in self.query()
            if record_id in record.metadata.get("antecedent_ids", [])
        ]

    def score_confidence(self, record: MemoryRecord) -> float:
        """Return this record's current confidence: a stored base value
        (1.0 unless lowered by flag_contradiction, defaulting to 1.0 for
        records that predate confidence tracking) exponentially decayed by
        time since it was last confirmed. Half-life defaults to
        `_DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS` (30 days) but can be
        overridden per-record via `metadata["half_life_seconds"]` (0 or
        negative disables decay for a record meant to never go stale).

        Confirmation resets the clock: reconsolidate stamps
        `metadata["last_confirmed_at"]` whenever a record's subject shows
        up in recent activity, so a record that's still relevant keeps its
        full confidence even if old, while one nobody has touched in a
        long time quietly loses weight until reconsolidate prunes it.
        """
        base = float(record.metadata.get("confidence", 1.0))
        half_life = float(
            record.metadata.get("half_life_seconds", _DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS)
        )
        if half_life <= 0:
            return base
        last_confirmed_at = float(record.metadata.get("last_confirmed_at", record.created_at))
        elapsed = max(0.0, time.time() - last_confirmed_at)
        return base * (0.5 ** (elapsed / half_life))

    def find_contradictions(
        self, kind: str = "semantic"
    ) -> list[tuple[MemoryRecord, MemoryRecord]]:
        """Find pairs of same-kind records that share a `metadata["subject"]`
        but disagree on `content` -- e.g. two "semantic" facts about the same
        subject that say different things. Consolidation
        (src/orchestrator/consolidation.py) calls this at sleep time to
        surface conflicts that would otherwise sit side by side in memory
        forever, each queried back as if equally true.
        """
        records = self.query(kind=kind)
        by_subject: dict[Any, list[MemoryRecord]] = {}
        for record in records:
            subject = record.metadata.get("subject")
            if subject is None:
                continue
            by_subject.setdefault(subject, []).append(record)

        pairs = []
        for subject_records in by_subject.values():
            for i, a in enumerate(subject_records):
                for b in subject_records[i + 1 :]:
                    if a.content != b.content:
                        pairs.append((a, b))
        return pairs

    def flag_contradiction(self, record_a_id: str, record_b_id: str) -> None:
        """Mark two records as contradicting each other and halve each
        one's confidence, rather than letting both silently stand as
        equally true. Tagged via `metadata["contradicts"]` /
        `metadata["confidence"]` and written through `_replace` so recency
        ordering is undisturbed. Neither record is deleted -- reconciling
        (choosing one, merging, or discarding both) is left to a human or
        a future agent with more context than a shared-subject match can
        supply.
        """
        if record_a_id == record_b_id:
            raise ValueError("a record cannot contradict itself")
        for this_id, other_id in ((record_a_id, record_b_id), (record_b_id, record_a_id)):
            record = self.get(this_id)
            if record is None:
                raise KeyError(this_id)
            contradicts = list(record.metadata.get("contradicts", []))
            if other_id not in contradicts:
                contradicts.append(other_id)
            confidence = float(record.metadata.get("confidence", 1.0)) * 0.5
            updated = MemoryRecord(
                id=record.id,
                kind=record.kind,
                content=record.content,
                created_at=record.created_at,
                metadata={
                    **record.metadata,
                    "contradicts": contradicts,
                    "confidence": confidence,
                },
            )
            self._replace(updated)

    def consolidate_contradictions(
        self, kind: str = "semantic"
    ) -> list[tuple[MemoryRecord, MemoryRecord]]:
        """Consolidation-time entry point: find every contradicting pair of
        same-kind records and flag each one, in a single call.

        Bundles find_contradictions + flag_contradiction so a sleep-time
        consolidation pass (src/orchestrator/consolidation.py) doesn't
        silently let conflicting records sit side by side at equal
        confidence -- it just calls this once per kind. Returns the flagged
        pairs so the caller can log or surface them for human/agent
        reconciliation, which this method does not attempt on its own.
        """
        pairs = self.find_contradictions(kind=kind)
        for record_a, record_b in pairs:
            self.flag_contradiction(record_a.id, record_b.id)
        return pairs

    def reconsolidate(
        self,
        activity_kind: str = "outcome",
        kinds: tuple[str, ...] = ("semantic",),
        activity_limit: int = 200,
        prune_below: float = 0.1,
    ) -> list[str]:
        """Confidence-weighted consolidation pass: for each of `kinds`,
        first flag internal contradictions (via consolidate_contradictions,
        which halves confidence on each side of a conflicting pair), then
        cross-check every record against recent `activity_kind` (default:
        "outcome") records. A record whose subject shows up there is
        "confirmed" -- its decay clock (`metadata["last_confirmed_at"]`,
        see score_confidence) resets to now, so it keeps full confidence
        even if old. Everything else -- including records with no
        `subject` at all, which previously dodged this pass entirely -- is
        scored by score_confidence's time-based half-life decay and pruned
        once that falls below `prune_below`. Meant to be called
        periodically by consolidation (src/orchestrator/consolidation.py),
        not on every query -- it costs one full scan of both the activity
        log and each kind, plus a `_replace`/`delete` per record touched.

        Folding contradiction-flagging in here means a record that's both
        stale (absent from recent activity, so its confidence keeps
        decaying) and contradicted by a peer (so its base confidence was
        already halved) loses ground on both counts in the same pass, so
        it's pruned sooner than either check alone would manage -- exactly
        the "stale/contradictory" entries this pass exists to catch.

        Matching is a coarse, case-insensitive substring check of each
        record's `metadata["subject"]` (the same field find_contradictions
        keys on) against recent activity content/request_text -- not
        semantic matching. That's deliberate: this only confirms what
        looks current by a cheap, auditable rule, and leaves ambiguous
        cases for a human or a better-informed future agent rather than
        guessing.
        """
        activity_records = self.query(kind=activity_kind, limit=activity_limit)
        haystack = " ".join(
            f"{r.content} {r.metadata.get('request_text', '')}" for r in activity_records
        ).lower()

        pruned_ids = []
        for kind in kinds:
            self.consolidate_contradictions(kind=kind)
            for record in self.query(kind=kind):
                subject = record.metadata.get("subject")
                confirmed = subject is not None and str(subject).lower() in haystack
                if confirmed:
                    confidence = float(record.metadata.get("confidence", 1.0))
                else:
                    confidence = self.score_confidence(record)
                if confidence < prune_below:
                    self.delete(record.id)
                    pruned_ids.append(record.id)
                elif confirmed:
                    updated = MemoryRecord(
                        id=record.id,
                        kind=record.kind,
                        content=record.content,
                        created_at=record.created_at,
                        metadata={**record.metadata, "last_confirmed_at": time.time()},
                    )
                    self._replace(updated)
        return pruned_ids


class InMemoryStore(MemoryStore):
    """Non-durable, process-local memory store. Useful for tests, and as
    the last-resort backend if even local disk isn't writable -- a process
    that can't persist memory should still be able to run this session.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, MemoryRecord] = {}
        self._order: list[str] = []

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            self._records[record.id] = record
            self._order.append(record.id)

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def query(
        self, kind: str | None = None, limit: int | None = None
    ) -> list[MemoryRecord]:
        with self._lock:
            return _filter_ordered(self._records, reversed(self._order), kind, limit)

    def delete(self, record_id: str) -> bool:
        with self._lock:
            if record_id not in self._records:
                return False
            del self._records[record_id]
            self._order.remove(record_id)
            return True

    def _replace(self, record: MemoryRecord) -> None:
        with self._lock:
            if record.id not in self._records:
                raise KeyError(record.id)
            self._records[record.id] = record


class JSONFileMemoryStore(MemoryStore):
    """Append-only JSON-Lines memory store on local disk.

    Each record is written and fsync'd before `add` returns, so a crash
    loses at most the record that was mid-write. On construction, all
    existing records are loaded into memory for fast querying.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: dict[str, MemoryRecord] = {}
        self._order: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = MemoryRecord(**json.loads(line))
                self._records[record.id] = record
                self._order.append(record.id)

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(record)) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._records[record.id] = record
            self._order.append(record.id)

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def query(
        self, kind: str | None = None, limit: int | None = None
    ) -> list[MemoryRecord]:
        with self._lock:
            return _filter_ordered(self._records, reversed(self._order), kind, limit)

    def delete(self, record_id: str) -> bool:
        with self._lock:
            if record_id not in self._records:
                return False
            del self._records[record_id]
            self._order.remove(record_id)
            self._rewrite()
            return True

    def _replace(self, record: MemoryRecord) -> None:
        with self._lock:
            if record.id not in self._records:
                raise KeyError(record.id)
            self._records[record.id] = record
            self._rewrite()

    def _rewrite(self) -> None:
        """Rewrite the on-disk log to match in-memory state, atomically:
        write to a sibling temp file and fsync it, then os.replace() over
        the real path. A crash at any point leaves either the old file or
        the new one fully intact -- never a partially-written one, and
        never neither (unlike a delete-then-add sequence, which has a
        window where the record exists in neither form).
        """
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            for record_id in self._order:
                fh.write(json.dumps(asdict(self._records[record_id])) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, self._path)


def _filter_ordered(
    records: dict[str, MemoryRecord],
    ids_newest_first: Any,
    kind: str | None,
    limit: int | None,
) -> list[MemoryRecord]:
    results = []
    for record_id in ids_newest_first:
        record = records[record_id]
        if kind is not None and record.kind != kind:
            continue
        results.append(record)
        if limit is not None and len(results) >= limit:
            break
    return results