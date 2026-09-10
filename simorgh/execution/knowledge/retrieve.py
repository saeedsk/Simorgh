"""Hybrid retrieval: exact matching and fuzzy matching, fused.

Neither half is enough on its own, and the ways they fail are opposite.
FTS5 finds "excess" only in a document that says "excess"; ask for
"deductible" and a policy that uses the British word is invisible.
Vectors find the neighbourhood but are hopeless at exactly the things a
personal corpus is full of -- an invoice number, a surname, a date.
Running both and fusing is not a refinement, it is the difference
between a search that works and one that works on the queries you
happened to test.

**Reciprocal rank fusion** does the fusing: each retriever contributes
`1 / (k + rank)` for the documents it returned, and the scores add.
Chosen over normalising and weighting the two score scales because
those scales are not comparable and never become so -- BM25 is an
unbounded negative log-odds, cosine is a bounded similarity, and any
constant relating them is a fit to one corpus. RRF only uses the
ordering each retriever is actually confident about, has one parameter,
and a passage both retrievers ranked highly wins without anyone having
to decide how much a bm25 of -8.2 is worth in cosines.
"""

from __future__ import annotations

from dataclasses import dataclass

from .api import Chunk, Citation, Hit
from .embed import cosine
from .index import Index

#: RRF's damping constant. 60 is the value from the original paper and
#: the one every implementation uses; it makes the difference between
#: rank 1 and rank 2 modest, which is the point -- a retriever's
#: ordering is informative at the top and noise by rank 40.
RRF_K = 60


@dataclass(frozen=True)
class Retrieved:
    hits: list[Hit]
    #: What actually ran. `kb_search` prints this when something was
    #: missing, so a lexical-only result is never passed off as hybrid.
    lexical: bool = True
    vector: bool = True
    note: str = ""


def _rrf(ranked_lists: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def search(index: Index, query: str, *, embedder=None, k: int = 8, candidates: int = 50,
           source: str = "", since: float = 0.0, min_score: float = 0.0) -> Retrieved:
    """The top `k` passages for `query`, with citations."""
    query = (query or "").strip()
    if not query:
        return Retrieved([], note="an empty query matches nothing")

    lexical_pairs = index.search_lexical(query, limit=candidates, source=source, since=since)
    lexical_ids = [chunk_id for chunk_id, _ in lexical_pairs]

    vector_ids: list[int] = []
    vector_scores: dict[int, float] = {}
    if embedder is not None:
        provider, query_vector = embedder.embed(query)
        scored: list[tuple[int, float]] = []
        for chunk_id, row_provider, values in index.vectors(source=source, since=since):
            if row_provider != provider:
                # Indexed with one embedder, queried with another: the
                # numbers are not comparable and pretending otherwise
                # would rank noise above real lexical hits.
                continue
            scored.append((chunk_id, cosine(query_vector, values)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        vector_scores = dict(scored)
        vector_ids = [chunk_id for chunk_id, score in scored[:candidates] if score > 0.0]

    fused = _rrf([ids for ids in (lexical_ids, vector_ids) if ids])
    if not fused:
        return Retrieved([], lexical=bool(index.has_fts), vector=embedder is not None,
                         note="nothing in your documents matched")

    lexical_set, vector_set = set(lexical_ids), set(vector_ids)
    hits: list[Hit] = []
    # Sorted by fused score, then by chunk id so a tie is stable rather
    # than dependent on dict ordering -- a search that returns a
    # different order for the same corpus and query is one nobody can
    # debug.
    for chunk_id in sorted(fused, key=lambda cid: (-fused[cid], cid)):
        if len(hits) >= k:
            break
        row = index.chunk_row(chunk_id)
        if row is None:
            continue
        found_by = tuple(name for name, member in
                         (("lexical", chunk_id in lexical_set), ("vector", chunk_id in vector_set))
                         if member)
        chunk = Chunk(doc_id=row["doc_id"], ordinal=row["ordinal"], text=row["text"],
                      heading_path=row["heading_path"], page=row["page"], tokens=row["tokens"])
        citation = Citation(doc_id=row["doc_id"], title=row["title"], path=row["path"],
                            page=row["page"], heading_path=row["heading_path"])
        score = fused[chunk_id]
        if score < min_score:
            continue
        hits.append(Hit(chunk=chunk, citation=citation, score=score, found_by=found_by,
                        privacy=row["privacy"]))

    note = ""
    if not index.has_fts:
        note = ("this sqlite has no FTS5, so only the vector half of the search ran -- "
                "exact terms may be missed")
    elif embedder is None:
        note = "vector search is off, so this was an exact-term search only"
    elif embedder is not None and not embedder.semantic:
        note = ("the hashing embedder is in use, so the vector half matches shared words rather "
                "than meaning -- install sentence-transformers for paraphrase matching")
    return Retrieved(hits, lexical=bool(index.has_fts), vector=embedder is not None, note=note)


def most_privileged(hits: list[Hit]) -> str:
    """The strictest privacy class among the hits, which is the one that
    governs what may be done with the set. A single `sensitive` passage
    in a set of eight makes the whole set sensitive: extraction from a
    mixed set cannot be shown to respect the boundary."""
    order = {"public": 0, "personal": 1, "sensitive": 2, "secret": 3}
    worst = "public"
    for hit in hits:
        if order.get(hit.privacy, 1) > order.get(worst, 0):
            worst = hit.privacy
    return worst


def render_passages(hits: list[Hit], *, max_chars: int = 6000) -> str:
    """The passages as the model sees them, each labelled with the
    citation it must use. The label goes *before* the text so a truncated
    prompt still has it."""
    blocks: list[str] = []
    used = 0
    for hit in hits:
        head = f"{hit.citation.render()} {hit.citation.human}"
        body = hit.chunk.text.strip()
        block = f"{head}\n{body}"
        if used + len(block) > max_chars:
            remaining = max_chars - used - len(head) - 2
            if remaining < 200:
                break
            block = f"{head}\n{body[:remaining]}…"
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


__all__ = ["RRF_K", "Retrieved", "most_privileged", "render_passages", "search"]
