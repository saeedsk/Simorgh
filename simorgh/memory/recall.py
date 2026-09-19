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

from .api import is_real_contradiction
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
    confidence never change once written, so a record already read can
    never be wrong -- only incomplete, and the cursor fixes that on the
    next sync. Forgetting is a tombstone in another stream, not a
    mutation of this one, so it is applied at query time rather than by
    editing the index.

    The one way a stream is NOT append-only is compaction
    (`ledger/compaction.py` truncating below a retention window), and
    this index does not see it: a record read before the truncation
    keeps being recalled by this process afterwards, while a restart
    stops returning it (measured on a jsonl ledger, 2026-09-10 -- five
    records, three truncated, all five still recalled). No default
    retention covers `memory:` and nothing writes memory snapshots, so
    nothing truncates these streams today; a `[ledger.retention]` entry
    for `memory:` would turn "forgotten by policy" into "still recalled
    until the next boot". Said here rather than guarded against,
    because the cheap guard -- re-reading the stream to check its floor
    -- is the exact per-recall cost this index exists to remove.
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
        # Dense vectors computed here and not yet persisted: (ref, provider, vector).
        self.fresh: list[tuple[str, str, tuple]] = []
        # BM25 over words, for the dense path's hybrid ranking (stage 5
        # item 2): term -> (positions, term frequencies), and each record's
        # length in words. Stdlib only.
        self.terms: dict[str, tuple[array, array]] = {}
        self.lengths = array("i")
        # The dense vectors as one float32 matrix, rebuilt when they change.
        self._matrix = None

    def __len__(self) -> int:
        return len(self.records)

    def add(self, record: Record, embedder, persisted=None) -> None:
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
            self._matrix = None
            words = _words(record.content)
            self.lengths.append(len(words))
            counts: dict[str, int] = {}
            for word in words:
                counts[word] = counts.get(word, 0) + 1
            for word, count in counts.items():
                posting = self.terms.get(word)
                if posting is None:
                    posting = self.terms[word] = (array("i"), array("i"))
                posting[0].append(position)
                posting[1].append(count)
            current = getattr(embedder, "provider", None)
            if persisted is not None and persisted[0] == current:
                # Embedded once, by an earlier process (stage 5 item 1).
                self.vectors.append((persisted[0], persisted[1]))
                return
            provider, vector = embedder.embed(record.content)
            if provider == current and provider != HASHING:
                self.fresh.append((record.ref, provider, vector))
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

        Same order is necessary and was not sufficient. The terms are
        collected and handed to the SAME `sum()` the dense path uses,
        because CPython's `sum()` over floats is not a running `+=`: since
        3.12 it carries a Neumaier compensation term, so summing the
        identical terms in the identical order with `+=` gives a
        DIFFERENT float. Measured here on 20,000 hashed records against
        one query: 44 of them, each off by one ULP, enough to swap two
        near-tied records in the ranking -- while the module claimed, and
        a regression test pinned, that the two paths agree exactly
        (observer, 2026-09-10). Going through `sum()` keeps the property
        true by construction on any Python, compensated or not, instead
        of by an argument about how the interpreter adds.

        Every term this still leaves out is exactly `0.0`, which no
        summation -- compensated or naive -- can change the answer by.
        """
        terms: dict[int, list[float]] = {}
        for bucket, query_weight in sparse_embed_text(query):
            posting = self.postings.get(bucket)
            if posting is None:
                continue
            for position, weight in zip(posting[0], posting[1]):
                product = query_weight * weight
                bucketed = terms.get(position)
                if bucketed is None:
                    terms[position] = [product]
                else:
                    bucketed.append(product)
        return {position: sum(values) for position, values in terms.items()}

    def bm25(self, query: str, *, k1: float = 1.2, b: float = 0.75) -> dict[int, float]:
        """`{position: BM25 score}` for the records sharing a word with `query`."""
        n = len(self.lengths)
        if not n:
            return {}
        average = (sum(self.lengths) / n) or 1.0
        scores: dict[int, float] = {}
        import math

        for word in set(_words(query)):
            posting = self.terms.get(word)
            if posting is None:
                continue
            idf = math.log(1.0 + (n - len(posting[0]) + 0.5) / (len(posting[0]) + 0.5))
            for position, tf in zip(posting[0], posting[1]):
                norm = tf * (k1 + 1.0) / (tf + k1 * (1.0 - b + b * self.lengths[position] / average))
                scores[position] = scores.get(position, 0.0) + idf * norm
        return scores

    def dense_scores(self, query_pair) -> list[float]:
        """Every record's cosine against the query, from one matrix product
        (stage 5 item 2): the per-record Python loop cost 47 ms at 2,422
        records. Rows whose vector is from another embedder than the query
        (hashed before warm-up) fall back exactly as `dense_similarity`."""
        query_provider, query_vec, _text = query_pair
        try:
            import numpy as np
        except ImportError:  # pragma: no cover -- numpy arrives with any dense embedder
            return [self.dense_similarity(i, query_pair) for i in range(len(self.vectors))]
        if not self.vectors:
            return []
        rows = [i for i, (provider, _v) in enumerate(self.vectors) if comparable(query_provider, provider)]
        out = [0.0] * len(self.vectors)
        if rows and len(rows) == len(self.vectors):
            if self._matrix is None or self._matrix.shape[0] != len(self.vectors):
                self._matrix = np.asarray([np.asarray(v, dtype=np.float32) for _p, v in self.vectors], dtype=np.float32)
            products = self._matrix @ np.asarray(query_vec, dtype=np.float32)
            return [float(x) for x in products]
        for i in range(len(self.vectors)):
            out[i] = self.dense_similarity(i, query_pair)
        return out

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
        # ref -> (provider, vector) from `memory:vectors`: what earlier
        # processes already embedded, so a restart embeds nothing twice.
        self.persisted: dict[str, tuple[str, array]] = {}
        self._vectors = RefSet(VECTOR_STREAM)
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
            if not self.hashing:
                await self._vectors.sync(self._ledger, self._apply_vector)
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
                    ), self._embedder, self.persisted.get(ref))

    def _apply_vector(self, event) -> None:
        vector = decode_vector(event.payload.get("v", ""))
        if vector is not None and event.payload.get("ref"):
            self.persisted[event.payload["ref"]] = (str(event.payload.get("provider") or ""), vector)

    def take_fresh(self) -> list[tuple[str, str, tuple]]:
        """The dense vectors computed since the last call, to persist."""
        out = []
        for index in self.kinds.values():
            out.extend(index.fresh)
            index.fresh.clear()
        return out

    def stale(self, limit: int = 0) -> list[tuple[str, int, str]]:
        """`(kind, position, content)` of records whose vector is not from
        the current embedder -- hashed before the model was warm, or by an
        older model. Oldest first; at most `limit` when given."""
        current = getattr(self._embedder, "provider", None)
        out = []
        for kind, index in self.kinds.items():
            for position, (provider, _vector) in enumerate(index.vectors):
                if provider != current:
                    out.append((kind, position, index.records[position].content))
                    if limit and len(out) >= limit:
                        return out
        return out

    async def upgrade(self, *, batch: int = 64, write=None) -> int:
        """Re-embed the stale records with the warm model, in a thread, a
        batch at a time; each new vector goes to `write(ref, provider,
        vector)` to be persisted. Returns how many were upgraded. Recall
        keeps answering throughout: a record is swapped only when its new
        vector is ready."""
        done = 0
        while True:
            chunk = self.stale(limit=batch)
            if not chunk or not getattr(self._embedder, "ready", True):
                return done
            fresh = await asyncio.to_thread(self._embedder.embed_many, [content for _k, _p, content in chunk])
            upgraded = 0
            for (kind, position, _content), (provider, vector) in zip(chunk, fresh):
                if provider != getattr(self._embedder, "provider", None):
                    continue            # the model fell back for this one; leave it
                index = self.kinds[kind]
                index.vectors[position] = (provider, array("d", vector))
                upgraded += 1
                if write is not None:
                    await write(index.records[position].ref, provider, vector)
            done += upgraded
            if not upgraded:
                return done

    def _apply_tombstone(self, event) -> None:
        self.tombstoned.update(event.payload.get("refs", []))

    def _apply_contradiction(self, event) -> None:
        # This is the penalty `retrieve` scores with, so a wrong flag here
        # does not merely mis-rank a record -- it quarters it. Every
        # consolidation summary on the creator's ledger carried two of
        # them (0.5 x 0.5 = 0.25), which is why distilled memory lost to
        # raw transcripts on every recall (2026-09-16).
        if not is_real_contradiction(event.payload):
            return
        for side in ("ref_a", "ref_b"):
            ref = event.payload[side]
            self.penalties[ref] = self.penalties.get(ref, 1.0) * 0.5


_WORD = __import__("re").compile(r"[a-z0-9\u0600-\u06ff]+")


#: Words BM25 ignores. Without them, measured on a 500-record fixture with
#: the real local model (2026-09-19): dense alone found 10/10 paraphrased
#: facts in the top 3, fused with BM25 only 6/10 -- "the", "for", "what"
#: matched filler records and outvoted the meaning. With them, 10/10.
_STOPWORDS = frozenset(
    "a about am an and are as at be been but by can could did do does for from had has have he her him his how i "
    "if in into is it its just me must my no not now of on or our she should so than that the their them then "
    "there these they this those to us was we were what when where which who will with would you your".split())


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOPWORDS]


#: Reciprocal rank fusion's constant: the usual 60.
RRF_K = 60


def fused(dense: list[float], lexical: dict[int, float]) -> list[float]:
    """Reciprocal rank fusion of the dense and the BM25 rankings, scaled
    to 0..1 (1 = first in both). A record with no word in common with the
    query gets only its dense share, so a paraphrase still ranks."""
    order = sorted(range(len(dense)), key=lambda i: dense[i], reverse=True)
    dense_rank = {position: rank for rank, position in enumerate(order, start=1)}
    lexical_rank = {position: rank for rank, position in
                    enumerate(sorted(lexical, key=lexical.get, reverse=True), start=1)}
    best = 2.0 / (RRF_K + 1)
    out = []
    for position in range(len(dense)):
        score = 1.0 / (RRF_K + dense_rank[position])
        if position in lexical_rank:
            score += 1.0 / (RRF_K + lexical_rank[position])
        out.append(score / best)
    return out


#: Dense vectors, persisted once each (stage 5 item 1): `vector.stored`
#: events `{ref, provider, v}` with `v` the float32 vector in base64 --
#: 384 dimensions is 2 KB, inside the Ledger's inline limit.
VECTOR_STREAM = "memory:vectors"


def encode_vector(vector) -> str:
    import base64

    return base64.b64encode(array("f", vector).tobytes()).decode("ascii")


def decode_vector(text: str):
    import base64

    try:
        raw = base64.b64decode(text or "", validate=True)
    except ValueError:
        return None
    if not raw or len(raw) % 4:
        return None
    floats = array("f")
    floats.frombytes(raw)
    return array("d", floats)


__all__ = ["KindIndex", "RRF_K", "Record", "RecallIndex", "RefSet", "VECTOR_STREAM", "decode_vector", "encode_vector", "fused"]
