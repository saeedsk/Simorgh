"""What the sidecars share (stage 15 items 5, 5b and 5c).

A sidecar is somebody else's memory library run against the same month
and the same questions, so the native systems have something to be
measured against. The rules are the plan's, and they are the same for
each:

- The package is imported only here, under `try/except ImportError`.
  Absent, the system reports every case skipped with the reason and the
  pip line that installs it -- never failed. Nothing in `simorgh/memory` or
  the Kernel imports a sidecar; they live only in this harness.
- Telemetry is forced off in the environment before the import.
- Everything it stores is in a temporary directory, deleted afterwards,
  with an embedded store and no server.
- Its model is the Together model Sim uses, over the OpenAI-compatible
  endpoint, with the key from the environment, behind `meter.Meter`'s
  hard cap. It runs only with `--paid`; `--dry-run` prints what it would
  cost instead.
- It records, per episode, the calls, tokens, dollars and seconds
  ingestion took. That is half of the comparison.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from .corpus import Episode, Question
from .meter import Meter

#: Embeddings go to Gemini's OpenAI-compatible endpoint, not Together:
#: on 2026-10-27 Together served no embedding model per token to this
#: account (multilingual-e5-large-instruct and bge-base-en-v1.5 both
#: answered HTTP 400 "non-serverless model", though `/v1/models` lists
#: the second). Overridable, endpoint and key included, because that
#: changes.
EMBED_MODEL_ENV = "SIMORGH_EVALS_EMBED_MODEL"
EMBED_BASE_URL_ENV = "SIMORGH_EVALS_EMBED_BASE_URL"
EMBED_KEY_ENV = "GEMINI_API_KEY"
DEFAULT_EMBED_MODEL = "gemini-embedding-001"
DEFAULT_EMBED_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_EMBED_DIMENSIONS = 768
EMBED_DIMENSIONS_ENV = "SIMORGH_EVALS_EMBED_DIMENSIONS"
KEY_ENV = "TOGETHER_API_KEY"


@dataclass(frozen=True)
class Settings:
    """Where a sidecar's model calls go, and what they cost."""

    api_key: str
    model: str
    base_url: str
    embed_model: str
    price_in: float
    price_out: float
    embed_dimensions: int = DEFAULT_EMBED_DIMENSIONS
    embed_base_url: str = DEFAULT_EMBED_BASE_URL
    embed_api_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        from simorgh.cognition.providers import together

        return cls(api_key=os.environ.get(KEY_ENV, ""), model=together.DEFAULT_MODEL,
                   base_url=together.DEFAULT_BASE_URL,
                   embed_model=os.environ.get(EMBED_MODEL_ENV, "") or DEFAULT_EMBED_MODEL,
                   price_in=together.PRICE_IN, price_out=together.PRICE_OUT,
                   embed_dimensions=int(os.environ.get(EMBED_DIMENSIONS_ENV, "") or DEFAULT_EMBED_DIMENSIONS),
                   embed_base_url=os.environ.get(EMBED_BASE_URL_ENV, "") or DEFAULT_EMBED_BASE_URL,
                   embed_api_key=os.environ.get(EMBED_KEY_ENV, ""))


@dataclass
class Ingestion:
    """What feeding the month cost, one row per episode."""

    rows: list[dict] = field(default_factory=list)
    stopped: str = ""                  # why ingestion stopped early, if it did

    def summary(self) -> dict:
        n = len(self.rows)
        seconds = sorted(r["seconds"] for r in self.rows)
        return {
            "episodes": n,
            "calls": sum(r["calls"] for r in self.rows),
            "tokens_in": sum(r["tokens_in"] for r in self.rows),
            "tokens_out": sum(r["tokens_out"] for r in self.rows),
            "usd": round(sum(r["usd"] for r in self.rows), 4),
            "calls_per_episode": round(sum(r["calls"] for r in self.rows) / n, 2) if n else 0.0,
            "usd_per_episode": round(sum(r["usd"] for r in self.rows) / n, 5) if n else 0.0,
            "seconds_per_episode_p50": seconds[n // 2] if n else 0.0,
            "stopped": self.stopped,
        }


class Sidecar:
    """The shape every sidecar fills in. `load()` is the guarded import."""

    name = ""
    install = ""                       # the pip line that installs it
    #: For the dry-run estimate: model calls per episode, tokens per call.
    calls_per_episode = 8
    tokens_in_per_call = 2_500
    tokens_out_per_call = 400
    #: The model calls one question costs (an embedding, usually).
    calls_per_question = 1

    def __init__(self, *, paid: bool, cap_usd: float, settings: Settings | None = None) -> None:
        self.paid = paid
        self.settings = settings or Settings.from_env()
        self.meter = Meter(cap_usd=cap_usd, price_in=self.settings.price_in, price_out=self.settings.price_out,
                           reserve_in=self.tokens_in_per_call, reserve_out=self.tokens_out_per_call)
        #: Facts about this run the report must state (which graph store,
        #: how privacy was mapped).
        self.notes: dict[str, str] = {}
        self._lib = None

    # -- the guarded import ---------------------------------------------------
    def load(self) -> tuple[object | None, str]:
        """(the library's handles, "") or (None, why it cannot be used)."""
        raise NotImplementedError

    def skip_reason(self) -> str:
        if self._lib is None:
            lib, why = self.load()
            if lib is None:
                return f"{self.name}: {why}; {self.install}"
            self._lib = lib
        if not self.paid:
            return f"{self.name} calls a real model; pass --paid (and --cap-usd) to run it"
        cap = self.meter.cap_usd
        if not (math.isfinite(cap) and cap > 0):
            return f"{self.name} needs a finite --cap-usd above zero (got {cap!r}); it never runs uncapped"
        if not self.settings.api_key:
            return f"{self.name}: no {KEY_ENV} in the environment"
        if not self.settings.embed_api_key:
            return f"{self.name}: no {EMBED_KEY_ENV} in the environment (embeddings go to {self.settings.embed_base_url})"
        return ""

    def estimate(self, episodes: int, questions: int) -> dict:
        calls = episodes * self.calls_per_episode + questions * self.calls_per_question
        tokens_in = episodes * self.calls_per_episode * self.tokens_in_per_call + questions * 50
        tokens_out = episodes * self.calls_per_episode * self.tokens_out_per_call
        usd = (tokens_in * self.settings.price_in + tokens_out * self.settings.price_out) / 1_000_000
        return {"calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": round(usd, 3),
                "cap_usd": self.meter.cap_usd, "model": self.settings.model}

    async def open(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def ingest(self, episode: Episode) -> None:
        raise NotImplementedError

    async def context(self, question: Question) -> list[str]:
        raise NotImplementedError


def groups_for(asker: str) -> list[str]:
    """What a sidecar searches for one person: the household and their own."""
    return ["household", f"person_{asker}"]


__all__ = ["DEFAULT_EMBED_DIMENSIONS", "DEFAULT_EMBED_MODEL", "EMBED_BASE_URL_ENV", "EMBED_DIMENSIONS_ENV", "EMBED_KEY_ENV", "EMBED_MODEL_ENV", "Ingestion", "KEY_ENV",
           "Settings", "Sidecar", "groups_for"]
