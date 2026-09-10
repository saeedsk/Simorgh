"""What `retrieve` scans, so that it stops scanning everything.

The problem this exists for, measured on a real jsonl ledger before it
did (2026-09-10, and by an earlier observer the same day):
`MemoryEngine.retrieve` read every event of every requested kind out of
the Ledger and embedded every one of them, on every single call. At
1,000 records per kind that is ~25 ms; at 10,000 it is ~1,000 ms.
`orchestration/context.py` gives the whole recall 0.25 s, and
consolidation's own steady state is 2,000 records per kind -- so Sim
lost its memory block routinely, and worst exactly when it had the most
to remember. Nothing about that was a wiring gap; the retrieval path
was O(store) by construction.

Three separate costs were in that number, and this module removes each:

1. **Re-reading the Ledger.** The stream is append-only, so a record
   that was read once can never change. `KindIndex` keeps what it has
   already seen and asks the Ledger only for events after its cursor.

2. **Re-embedding every record.** With the default hashing embedder a
   record's vector is a pure function of its text, so it is computed
   once at index time and never again. `Embedder`'s own text cache held
   4,096 entries and evicted FIFO, which meant that past ~4,096 records
   each retrieve evicted exactly what the previous one had cached and
   the warm path stopped existing (measured: 500 ms first call, 587 ms
   second, at 6,000 records -- the second call was *slower*). Keying the
   cache by record instead of by text removes the question.

3. **Multiplying N dense vectors.** A hashing vector is 256 buckets of
   which a 30-word memory fills at most 30, so the cosine between the
   query and a record only ever involves the buckets they share. The
   inverted index here (`bucket -> [(record, weight)]`) accumulates all
   N cosines by walking only the query's own buckets.

**This is not an approximation, and deliberately so.** A prefilter that
drops candidates before scoring was the obvious cheaper option and was
rejected: it can only be justified by an argument about how rarely it
loses a record, and "fast recall that quietly forgets things" is worse
than slow recall. Every record still gets a score, the score is the
same float the dense path computed (see `sparse_embed_text` on why
bit-identical rather than merely close), and the ranking is therefore
the same ranking. The saving comes from not doing arithmetic whose
answer is known to be zero.

The one path that is still O(N x dim) is a *real* embedding model
(`[memory] embedder = local|openai|...`): those vectors are dense, so
there is no zero to skip. That path still gets 1 and 2 -- each record is
embedded once ever, instead of once per retrieve, which for a remote
provider is the difference between one bill and one per query.
"""

from __future__ import annotations

import asyncio
from array import array
from dataclasses import dataclass

from simorgh.contracts.protocols import Ledger

from .embed import cosine_similarity, embed_text, sparse_embed_text
from .embedders import HASHING, comparable


@dataclass(slots=True)
class Record:
    """One indexed memory, in the shape `retrieve` scores it in."""

    ref: str
    ts: float
    tags: tuple[str, ...]
    confidence: float
    content: str
    source_ref: str


class KindIndex:
    """An incrementally-built, in-process view of one `memory:<kind>`
    stream: the records, their vectors, and (for the hashing embedder)
    an inverted index from bucket to the records that touch it.

    Append-only is what makes this safe. A record's text, tags, ts and
    confidence never change once written, so nothing here can go stale
    -- only incomplete, and the cursor fixes that on the next sync.
    Forgetting is a tombstone in another stream, not a mutation of this
    one, so it is applied at query time rather than by editing the index.
    """

    def __init__(self, stream: str, *, hashing: bool) -> None:
        self.stream = stream
        self.cursor = 0
        self.records: list[Record] = []
        self._hashing = hashing
        # bucket -> (positions in self.records, weights), as parallel
        # arrays rather than a list of tuples. At 20,000 records the
        # tuple-of-boxed-scalars form cost ~2 KB per record in postings
        # alone (79 MB of index for a store whose text is 5 MB); two
        # typed arrays are 12 bytes per posting.
        #
        # `d`, not `f`. Single precision saves another 4 bytes and
        # rounds the weight, which moves the cosine in the 8th decimal
        # and breaks the one property this whole path is built on --
        # that the indexed score IS the full-scan score. Caught by
        # `test_the_indexed_ranking_is_the_full_scan_ranking` the moment
        # it was tried.
        self.postings: dict[int, tuple[array, array]] = {}
        # position -> (provider, vector), for a real (dense) embedder only
        self.vectors: list[tuple[str, tuple[float, ...] | array]] = []

    def __len__(self) -> int:
        return len(self.records)

    def add(self, record: Record, embedder) -> None:
        position = len(self.records)
        self.records.append(record)
        if self._hashing:
            for bucket, weight in sparse_embed_text(record.content):
                posting = self.postings.get(bucket)
                if posting is None:
                    posting = self.postings[bucket] = (array("i"), array("d"))
                posting[0].append(position)
                posting[1].append(weight)
        else:
            provider, vector = embedder.embed(record.content)
            # `array('d')` rather than a tuple of Python floats: a
            # 1536-dim OpenAI vector as a tuple is ~50 KB of boxed
            # floats, so 10,000 of them is half a gigabyte; as an array
            # it is 12 KB. Double precision, not single -- see the
            # postings above: a rounded component changes the cosine,
            # and "the same ranking as before" is the point.
            self.vectors.append((provider, array("d", vector)))

    def similarities(self, query: str) -> dict[int, float]:
        """`{position: cosine}` for every record with a non-zero cosine
        against `query`. Absent means exactly 0.0, which is what the
        dense path computes for a record sharing no bucket.

        The query's buckets are walked in ascending order on purpose:
        each record then accumulates its terms in the same order the
        dense `cosine_similarity` sums them, so the float is identical
        rather than approximately equal.
        """
        sims: dict[int, float] = {}
        for bucket, query_weight in sparse_embed_text(query):
            posting = self.postings.get(bucket)
            if posting is None:
                continue
            for position, weight in zip(posting[0], posting[1]):
                sims[position] = sims.get(position, 0.0) + query_weight * weight
        return sims

    def dense_similarity(self, position: int, query_pair) -> float:
        """The dense path, using the vector stored at index time.

        Replicates `MemoryEngine._similarity` exactly, mismatch rule
        included: a record whose own embedding fell back to hashing is
        not comparable with a model-vector query, and both sides are
        re-hashed rather than compared over their first 256 components.
        """
        query_provider, query_vec, query_text = query_pair
        provider, vector = self.vectors[position]
        if not comparable(query_provider, provider):
            return cosine_similarity(embed_text(query_text), embed_text(self.records[position].content))
        return cosine_similarity(query_vec, tuple(vector))


class RefSet:
    """An incrementally-read stream reduced to a value -- tombstoned
    refs, or contradiction penalties. Same append-only argument as
    `KindIndex`: what has been read can never change."""

    def __init__(self, stream: str) -> None:
        self.stream = stream
        self.cursor = 0

    async def sync(self, ledger: Ledger, apply) -> None:
        events = await ledger.read(self.stream, from_seq=self.cursor + 1)
        for event in events:
            self.cursor = max(self.cursor, event.seq)
            apply(event)


class RecallIndex:
    """Every index one `MemoryEngine` needs, kept in step with the
    Ledger by `sync`."""

    def __init__(self, ledger: Ledger, embedder, *, streams, tombstone_stream: str,
                 contradiction_stream: str) -> None:
        self._ledger = ledger
        self._embedder = embedder
        # `getattr`, not `embedder.provider`: a test double is allowed
        # to be nothing but an `embed(text)`. An embedder that does not
        # say what it is takes the dense path, which calls its `embed`
        # for every record exactly as the pre-index code did -- the
        # sparse shortcut is only ever taken when the embedder has said
        # it is the hashing one.
        self.hashing = getattr(embedder, "provider", None) == HASHING
        self._stream_for = streams
        self.kinds: dict[str, KindIndex] = {}
        self.tombstoned: set[str] = set()
        self.penalties: dict[str, float] = {}
        self._tombstones = RefSet(tombstone_stream)
        self._contradictions = RefSet(contradiction_stream)
        # Two `retrieve` calls can interleave at any `await`; without
        # this both would read the same events past the same cursor and
        # index every record twice.
        self._lock = asyncio.Lock()

    def index_for(self, kind: str) -> KindIndex:
        index = self.kinds.get(kind)
        if index is None:
            index = self.kinds[kind] = KindIndex(self._stream_for(kind), hashing=self.hashing)
        return index

    async def sync(self, kinds, *, on_record=None) -> None:
        async with self._lock:
            await self._tombstones.sync(self._ledger, self._apply_tombstone)
            await self._contradictions.sync(self._ledger, self._apply_contradiction)
            for kind in kinds:
                index = self.index_for(kind)
                events = await self._ledger.read(index.stream, from_seq=index.cursor + 1)
                for event in events:
                    if event.seq <= index.cursor:
                        continue
                    index.cursor = event.seq
                    ref = f"{index.stream}:{event.seq}"
                    payload = event.payload
                    if on_record is not None:
                        on_record(ref, payload)
                    index.add(Record(
                        ref=ref, ts=event.ts, tags=tuple(payload.get("tags", [])),
                        confidence=float(payload.get("confidence", 1.0)),
                        content=payload.get("content", ""),
                        source_ref=payload.get("source_ref", ""),
                    ), self._embedder)

    def _apply_tombstone(self, event) -> None:
        self.tombstoned.update(event.payload.get("refs", []))

    def _apply_contradiction(self, event) -> None:
        for side in ("ref_a", "ref_b"):
            ref = event.payload[side]
            self.penalties[ref] = self.penalties.get(ref, 1.0) * 0.5


__all__ = ["KindIndex", "Record", "RecallIndex", "RefSet"]
