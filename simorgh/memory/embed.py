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


__all__ = ["EMBED_DIM", "cosine_similarity", "embed_text"]
