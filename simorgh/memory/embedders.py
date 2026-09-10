"""Where an embedding comes from -- and what each source can actually do.

`embed.py` hashes tokens into buckets. It needs no network, no key and
no package, which is why it is the default and why it will stay the
default. What it cannot do is recognise a paraphrase. Measured here,
2026-09-09:

    "the car is fast" vs "the automobile is quick"   -> 0.500
    "how do I stop the loop" vs
        "halting a runaway iteration"                -> 0.000

The second pair is the same thought in different words and scores
exactly zero, because the two share no token. That is not a bug in the
hashing trick; it is what the hashing trick is. It means memory recall
finds what Sim already knows how to say, and misses what it phrased
differently last week -- precisely when recall would be most useful.

This module makes the embedder pluggable so a real model can be dropped
in, WITHOUT requiring one (the creator, 2026-09-09: build it so that
"when the skill will be needed, user will provide account or api key
... but still the sim infra needs to be ready"):

| provider | needs | notes |
|---|---|---|
| `local` | the `sentence-transformers` package | real semantics, no key, no network |
| `openai` | `OPENAI_API_KEY` | text-embedding-3-small |
| `voyage` | `VOYAGE_API_KEY` | voyage-3 |
| `gemini` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | text-embedding-004 |
| `hashing` | nothing | always available; the honest floor |

`auto` picks a real model only when it is FREE and OFFLINE -- in
practice `local` -- and falls back to hashing otherwise. A remote,
billable provider is never chosen automatically, however many keys are
lying around the environment: an embedding sits on the hot path of every
recall, and a key exported for chat is not consent to be billed for
memory. Name one in `[memory] embedder` to use it.

Two things this module is careful about, both of which would otherwise
turn a quality improvement into a fault:

**Dimensions are part of the identity of a vector.** A cosine
similarity between a 256-dim hashed vector and a 1536-dim OpenAI vector
is meaningless -- and `zip()` computes one anyway, silently, over the
first 256 components. So every stored vector carries the provider and
dimension that made it, and a vector from a different embedder is
recomputed rather than compared. Switching providers degrades to "re-
embed on demand", never to "compare nonsense".

**An embedding call must never break recall.** A provider that is down,
rate-limited or slow falls back to hashing for that call and says so.
Worse recall is a bad day; a memory subsystem that raises is a broken
system.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections import OrderedDict

from .embed import EMBED_DIM, embed_text

HASHING = "hashing"

OPENAI_URL = "https://api.openai.com/v1/embeddings"
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "text-embedding-004:embedContent")

# Providers `auto` may choose on its own: free, offline, and with no
# per-call cost. A REMOTE provider must be named explicitly in config --
# see `choose_provider`.
AUTO_ELIGIBLE = ("local", "hashing")

# provider -> (env vars -- ANY one of them is enough, model name, dimension)
PROVIDERS: tuple[tuple[str, tuple[str, ...], str, int], ...] = (
    ("openai", ("OPENAI_API_KEY",), "text-embedding-3-small", 1536),
    ("voyage", ("VOYAGE_API_KEY",), "voyage-3", 1024),
    ("gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "text-embedding-004", 768),
    ("local", (), "all-MiniLM-L6-v2", 384),
    (HASHING, (), "hashing-trick", EMBED_DIM),
)


class EmbeddingUnavailable(Exception):
    """This embedder cannot answer; the caller falls back to hashing."""


def _row(provider: str):
    for row in PROVIDERS:
        if row[0] == provider:
            return row
    return None


def dimension_of(provider: str) -> int:
    row = _row(provider)
    return row[3] if row else EMBED_DIM


def key_for(provider: str, env) -> str:
    row = _row(provider)
    if not row:
        return ""
    for name in row[1]:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return ""


def local_model_available() -> bool:
    """Whether `sentence-transformers` can be imported. Deliberately
    only an import check: loading the model downloads weights, which is
    not something a capability probe should do behind someone's back."""
    import importlib.util

    return importlib.util.find_spec("sentence_transformers") is not None


def available_providers(env, *, local_check=local_model_available) -> list[str]:
    ready = []
    for name, keys, _model, _dim in PROVIDERS:
        if name == HASHING:
            ready.append(name)
        elif name == "local":
            if local_check():
                ready.append(name)
        elif any((env.get(k) or "").strip() for k in keys):
            ready.append(name)
    return ready


def choose_provider(configured: str, env, *, local_check=local_model_available) -> str:
    """The embedder to use.

    Never raises for lack of a key: hashing always works, so there is
    always an answer -- a memory subsystem that refuses to embed is
    worse than one that embeds crudely. A provider named explicitly but
    missing its key is different: that is a misconfiguration, and it is
    reported rather than silently downgraded, because someone who set
    `openai` wants to know their key is not being seen.
    """
    configured = (configured or "auto").strip().lower()
    ready = available_providers(env, local_check=local_check)
    if configured == "auto":
        # Only a free, offline embedder is chosen automatically.
        #
        # Caught by the test suite, 2026-09-09: this used to prefer any
        # configured provider, and a GEMINI_API_KEY that happened to be
        # exported for CHAT silently rerouted every memory embedding
        # through a paid endpoint -- one network call per candidate per
        # retrieve. The suite went from 90s to 170s and a memory test
        # started failing.
        #
        # Two things were wrong with that, beyond the flake. Nobody who
        # exports a key for one purpose is consenting to be billed for
        # another. And an embedding is on the hot path of every recall,
        # so a network round trip there is the wrong shape regardless of
        # who pays. A remote embedder is a real option -- it is just an
        # option somebody has to choose, by naming it in config.
        for name in ready:
            if name in AUTO_ELIGIBLE:
                return name
        return HASHING
    if _row(configured) is None:
        raise EmbeddingUnavailable(
            f"unknown embedder {configured!r}; known: {', '.join(n for n, _, _, _ in PROVIDERS)}")
    if configured not in ready:
        row = _row(configured)
        need = " or ".join(row[1]) if row[1] else "the `sentence-transformers` package"
        raise EmbeddingUnavailable(f"embedder {configured!r} needs {need}")
    return configured


def _post_json(opener, url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
    )
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace") or "{}")


def _embed_openai(text, env, opener, timeout):
    body = _post_json(opener, OPENAI_URL,
                      {"input": text, "model": _row("openai")[2]},
                      {"Authorization": f"Bearer {key_for('openai', env)}"}, timeout)
    return tuple(float(x) for x in (body.get("data") or [{}])[0].get("embedding") or ())


def _embed_voyage(text, env, opener, timeout):
    body = _post_json(opener, VOYAGE_URL,
                      {"input": [text], "model": _row("voyage")[2]},
                      {"Authorization": f"Bearer {key_for('voyage', env)}"}, timeout)
    return tuple(float(x) for x in (body.get("data") or [{}])[0].get("embedding") or ())


def _embed_gemini(text, env, opener, timeout):
    # The key goes in a header, not the query string: a key in a URL
    # ends up in logs, proxies and history.
    body = _post_json(
        opener, GEMINI_URL,
        {"model": "models/" + _row("gemini")[2], "content": {"parts": [{"text": text}]}},
        {"x-goog-api-key": key_for("gemini", env)}, timeout)
    return tuple(float(x) for x in ((body.get("embedding") or {}).get("values") or ()))


_REMOTE = {"openai": _embed_openai, "voyage": _embed_voyage, "gemini": _embed_gemini}


class Embedder:
    """One embedder, chosen once, with hashing underneath it.

    `embed(text)` returns `(provider, vector)` -- the provider included
    because a vector is only comparable to another from the same one.
    """

    def __init__(self, provider: str = "auto", *, env=None, opener=None,
                 timeout_s: float = 20.0, local_check=local_model_available,
                 encoder=None, logger=None) -> None:
        self._env = env if env is not None else os.environ
        self._opener = opener or urllib.request.urlopen
        self._timeout_s = timeout_s
        self._encoder = encoder
        self._logger = logger
        self._degraded = ""
        self._cache: OrderedDict[str, tuple[str, tuple[float, ...]]] = OrderedDict()
        self._cache_max = 4096
        try:
            self.provider = choose_provider(provider, self._env, local_check=local_check)
        except EmbeddingUnavailable as exc:
            # A misconfigured name must not take memory down with it.
            self.provider, self._degraded = HASHING, str(exc)

    @property
    def degraded(self) -> str:
        """Why this is not the embedder that was asked for, or ""."""
        return self._degraded

    def dimension(self) -> int:
        return dimension_of(self.provider)

    def embed(self, text: str) -> tuple[str, tuple[float, ...]]:
        """`(provider, vector)`. Cached, because one `retrieve` embeds
        every candidate's content: without a cache a paid provider would
        be billed for the whole memory store on every single query, and
        a local model would re-encode it."""
        key = (text or "").strip()
        hit = self._cache.get(key)
        if hit is not None:
            # Least-RECENTLY-USED, not first-in-first-out. Eviction used
            # to take `next(iter(...))` -- the oldest insertion -- with
            # no regard for use, so a working set larger than 4,096
            # evicted in exactly the order it was about to be asked for
            # again and the hit rate went to zero at the moment a cache
            # mattered most. Measured at 6,000 records, when `retrieve`
            # still embedded every one of them: 306 ms for the first
            # call and 455 ms for the second, i.e. the warm path was
            # SLOWER than the cold one (observer, 2026-09-10).
            self._cache.move_to_end(key)
            return hit
        answer = self._embed_uncached(key)
        if len(self._cache) >= self._cache_max:
            self._cache.popitem(last=False)
        self._cache[key] = answer
        return answer

    def _embed_uncached(self, text: str) -> tuple[str, tuple[float, ...]]:
        text = (text or "").strip()
        if not text or self.provider == HASHING:
            return HASHING, embed_text(text)
        try:
            if self.provider == "local":
                vector = tuple(float(x) for x in self._encode_local(text))
            else:
                vector = _REMOTE[self.provider](text, self._env, self._opener, self._timeout_s)
            if not vector:
                raise EmbeddingUnavailable("the provider returned no vector")
            return self.provider, _normalise(vector)
        except Exception as exc:  # noqa: BLE001
            # Worse recall is a bad day. A memory subsystem that raises
            # is a broken system, so this can only ever degrade.
            if self._logger is not None:
                self._logger.warning("embedding_fell_back", provider=self.provider, error=repr(exc))
            return HASHING, embed_text(text)

    def _encode_local(self, text: str):
        if self._encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover -- optional dependency
                raise EmbeddingUnavailable(
                    "the `sentence-transformers` package is not installed "
                    "(pip install sentence-transformers)"
                ) from exc
            self._encoder = SentenceTransformer(_row("local")[2])
        return self._encoder.encode(text)


def _normalise(vector: tuple[float, ...]) -> tuple[float, ...]:
    import math

    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return vector
    return tuple(component / norm for component in vector)


def comparable(stored_provider: str, current_provider: str) -> bool:
    """Whether a stored vector may be compared with a fresh one.

    Cosine similarity between a 256-dim hashed vector and a 1536-dim
    model vector is meaningless -- and `zip()` computes one anyway,
    silently, over the first 256 components, which is how this would
    otherwise fail: not loudly, but with quietly wrong recall.
    """
    return bool(stored_provider) and stored_provider == current_provider


__all__ = [
    "Embedder", "EmbeddingUnavailable", "HASHING", "PROVIDERS",
    "available_providers", "choose_provider", "comparable", "dimension_of", "key_for",
]
