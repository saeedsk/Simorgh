"""Passage vectors, and an honest account of what they are worth.

Memory has an embedder already (`simorgh/memory/embedders.py`), and
this cannot use it: a subsystem may not import another's internals
(`tests/simorgh/test_module_boundaries.py`). Rather than smuggle the
import in, this keeps the piece it actually needs -- two embedders and
a cosine -- and states the duplication rather than hiding it. If a
third caller ever wants one, the shared home is `contracts/`, and
moving it there is a small, separate change.

Two providers:

- **`local`**: a real sentence-transformers model. Genuinely semantic:
  "what is my excess" finds a passage that says "deductible". Optional,
  because it is a large dependency and a slow first load.
- **`hashing`**: stdlib, always available, and *not* semantic. It is a
  bag-of-words projection: it matches paraphrase only insofar as
  paraphrase shares words. It earns its place because it makes the
  vector half of hybrid retrieval work as a fuzzy, order-insensitive
  companion to FTS5's exact matching, and because it makes near-
  duplicate detection work.

The distinction matters enough that `kb_status` reports which is in use
and `kb_search` says so when a search was lexical-only. A retrieval
system that quietly is not doing what it claims is the exact failure
this project keeps calling out: a tool that succeeds while saying
nothing true.
"""

from __future__ import annotations

import hashlib
import math
import re

HASHING = "hashing"
LOCAL = "local"

#: Small enough to scan quickly, large enough that collisions between
#: unrelated words are rare at a personal corpus's vocabulary size.
HASHING_DIM = 512

#: The default sentence-transformers model: 384 dimensions, ~80 MB,
#: fast on CPU, and the one the memory subsystem also settled on.
LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LOCAL_DIM = 384

_WORD = re.compile(r"[\w']+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text or "") if len(t) > 1]


def local_model_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("sentence_transformers") is not None


def hashing_vector(text: str, dim: int = HASHING_DIM) -> list[float]:
    """Term frequency, hashed into `dim` buckets, then L2-normalised.

    Sub-linear term frequency (`1 + log tf`) rather than raw counts, so
    a passage that says "invoice" nine times does not drown one that
    says it twice and is actually about the invoice.
    """
    counts: dict[int, float] = {}
    for token in tokenize(text):
        bucket = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(),
                                "big") % dim
        counts[bucket] = counts.get(bucket, 0.0) + 1.0
    vector = [0.0] * dim
    for bucket, count in counts.items():
        vector[bucket] = 1.0 + math.log(count)
    return normalise(vector)


def normalise(vector) -> list[float]:
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    if norm == 0.0:
        return [float(v) for v in vector]
    return [float(v) / norm for v in vector]


def cosine(a, b) -> float:
    """Both sides are normalised on the way in, so this is a dot
    product. Mismatched dimensions score 0 rather than raising: a
    corpus embedded with one provider and queried with another is a
    real situation (someone installed the model after indexing), and
    the right answer is "these are not comparable", not a crash."""
    if len(a) != len(b):
        return 0.0
    return float(sum(float(x) * float(y) for x, y in zip(a, b)))


class Embedder:
    """One provider, chosen once, with a cache.

    `provider` is reported alongside every vector because a vector is
    only comparable to another from the same provider -- which is also
    why `Index` stores the provider per row.
    """

    def __init__(self, provider: str = "auto", *, model=None, dim: int = HASHING_DIM) -> None:
        self._model = model
        self._dim = dim
        self._cache: dict[str, list[float]] = {}
        self.degraded = ""
        self.provider = self._choose(provider)

    def _choose(self, requested: str) -> str:
        requested = (requested or "auto").strip().lower()
        if requested in ("", "auto"):
            return LOCAL if (self._model is not None or local_model_available()) else HASHING
        if requested == LOCAL:
            if self._model is None and not local_model_available():
                self.degraded = ("the `sentence-transformers` package is not installed "
                                 "(pip install sentence-transformers); using the hashing embedder, "
                                 "which matches words rather than meaning")
                return HASHING
            return LOCAL
        if requested == HASHING:
            return HASHING
        self.degraded = f"unknown embedder {requested!r}; using {HASHING}"
        return HASHING

    @property
    def semantic(self) -> bool:
        """Whether this embedder can match a paraphrase that shares no
        words. `kb_search` and `kb_status` both say so."""
        return self.provider == LOCAL

    def dimension(self) -> int:
        return LOCAL_DIM if self.provider == LOCAL else self._dim

    def embed(self, text: str) -> tuple[str, list[float]]:
        key = (text or "").strip()
        if not key:
            return self.provider, [0.0] * self.dimension()
        cached = self._cache.get(key)
        if cached is not None:
            return self.provider, cached
        vector = self._embed_uncached(key)
        if len(self._cache) < 8192:
            self._cache[key] = vector
        return self.provider, vector

    def _embed_uncached(self, text: str) -> list[float]:
        if self.provider != LOCAL:
            return hashing_vector(text, self._dim)
        try:
            model = self._ensure_model()
            return normalise([float(x) for x in model.encode(text)])
        except Exception as exc:  # noqa: BLE001
            # Worse recall is a bad day; an index that cannot be built
            # is a broken feature. This can only ever degrade.
            self.degraded = f"the local embedding model failed ({exc!r}); using the hashing embedder"
            self.provider = HASHING
            return hashing_vector(text, self._dim)

    def _ensure_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover -- optional dependency
                raise RuntimeError("sentence-transformers is not installed") from exc
            self._model = SentenceTransformer(LOCAL_MODEL)
        return self._model


__all__ = ["Embedder", "HASHING", "HASHING_DIM", "LOCAL", "LOCAL_DIM", "LOCAL_MODEL",
           "cosine", "hashing_vector", "local_model_available", "normalise", "tokenize"]
