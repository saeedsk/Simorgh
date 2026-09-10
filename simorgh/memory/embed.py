"""A dependency-free semantic embedding via the hashing trick, ported
verbatim from v1 `src/memory/long_term.py::embed_text` (docs/blueprint/
subsystems/05-memory.md section 5): each token hashed into one of `dim`
buckets and accumulated, then L2-normalized. Captures shared vocabulary
between texts (paraphrases with overlapping words score as similar)
without a network call or third-party model (principle 4.14)."""

from __future__ import annotations

import functools
import hashlib
import math
import re

EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@functools.lru_cache(maxsize=4096)
def embed_text(text: str, dim: int = EMBED_DIM) -> tuple[float, ...]:
    vector = [0.0] * dim
    for token in _tokenize(text):
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dim
        vector[bucket] += 1.0
    norm = math.sqrt(sum(c * c for c in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(c / norm for c in vector)


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b))


def sparse_embed_text(text: str, dim: int = EMBED_DIM) -> tuple[tuple[int, float], ...]:
    """The same vector as `embed_text`, as `((bucket, weight), ...)` in
    ASCENDING bucket order, with the zero buckets left out.

    Why this exists, and why the ordering is part of the contract: the
    hashing vector is overwhelmingly zeros (a 30-word memory touches at
    most 30 of 256 buckets), so a cosine between two of them only ever
    needs the buckets they share. `recall.py` uses that to score a whole
    memory store from an inverted index instead of materialising and
    multiplying N dense vectors -- the difference between 1,000 ms and
    20 ms at 10,000 records.

    Ascending order makes the answer BIT-IDENTICAL to the dense path,
    not merely close. `cosine_similarity` sums `a[i]*b[i]` for i in
    0..dim-1; every term this skips is exactly `0.0`, and adding 0.0 to
    a float is exact, so summing the surviving terms in the same
    (ascending) order yields the same float. That is what lets recall
    get faster without any argument about whether the ranking moved.
    """
    # Deliberately NOT `lru_cache`d, unlike `embed_text`: every caller
    # is either indexing a record (each text seen exactly once, so a
    # cache is pure overhead and 4,096 retained vectors of pure waste)
    # or embedding a query, which is one call per recall.
    counts: dict[int, float] = {}
    for token in _tokenize(text):
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dim
        counts[bucket] = counts.get(bucket, 0.0) + 1.0
    norm = math.sqrt(sum(c * c for c in counts.values()))
    if norm == 0.0:
        return ()
    return tuple((bucket, counts[bucket] / norm) for bucket in sorted(counts))


def sparse_cosine(query: tuple[tuple[int, float], ...], other: tuple[tuple[int, float], ...]) -> float:
    """Cosine between two `sparse_embed_text` vectors -- for the one-off
    comparison; `recall.py` accumulates over an inverted index instead."""
    lookup = dict(other)
    return sum(weight * lookup[bucket] for bucket, weight in query if bucket in lookup)


__all__ = ["EMBED_DIM", "cosine_similarity", "embed_text", "sparse_cosine", "sparse_embed_text"]
