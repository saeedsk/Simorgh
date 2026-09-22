"""Memory configuration (docs/blueprint/subsystems/05-memory.md section
3.5). Every field has a working default -- `[memory]` may be absent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .api import DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS


@dataclass(frozen=True)
class Config:
    half_life_seconds: float = DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS
    # `WorkingMemory`'s bounds (`store.py`): the per-(channel, person)
    # conversation window that every chat `turn.completed` feeds.
    working_max_turns: int = 20
    working_max_chars: int = 8_000
    # Unreachable by design (2026-09-08 observer audit): `service.py`'s
    # `_on_retrieve` falls back to this only when a `memory.retrieve`
    # payload omits `k`, but the wire contract
    # (`contracts/messages/memory.py`) declares `k` a *required* field,
    # so `Message.new(...)` raises before the fallback could ever run.
    # Both real publishers -- `execution/service.py`'s skill-description
    # lookup (k=3, tuned to that narrow lookup) and
    # `orchestration/context.py`'s context build (k=8, paired with its
    # own `items[:8]` slice and char budget) -- pass `k` explicitly and
    # have a specific reason for their own value, so there is no
    # "should omit k" caller to fix here. Setting this in simorgh.toml
    # changes nothing; `kernel/configcheck.py`'s `KNOWN_DEAD_FIELDS`
    # calls that out explicitly since the ordinary dead-section probe
    # cannot (the field parses into a real, different value -- it is
    # just never read).
    default_k: int = 5
    # Which embedder scores recall (`embedders.py`). "auto" uses a real
    # model only when it is FREE and OFFLINE (a local
    # sentence-transformers install) and the dependency-free hashing
    # trick otherwise -- never a remote API, however many keys happen to
    # be in the environment, since an embedding is on the hot path of
    # every recall and a key exported for chat is not consent to be
    # billed for memory. Name "openai"/"voyage"/"gemini" here to use one.
    # It matters more than it looks: hashing matches VOCABULARY, so
    # "how do I stop the loop" and "halting a runaway iteration" score
    # 0.000 against each other (measured 2026-09-09) -- recall finds
    # what Sim already knows how to say and misses what it phrased
    # differently.
    # hashing, not auto. `auto` picks a local sentence-transformer the moment
    # one is importable, and measured on the creator's own store (2,422
    # records, 2026-09-16) that costs 24.9 SECONDS on the first call -- the
    # model load plus re-embedding everything -- against 155 ms for hashing.
    # `orchestration/context.py` allows recall 0.25 s, so every turn in the
    # first half-minute after boot would lose its memory block silently, and
    # warm it is still 47 ms against 3 ms, three recalls to a turn.
    #
    # What it bought did not pay for that: paraphrase pairs that scored 0.000
    # became findable (0.197, 0.329), but "turn the lights on" vs "off" went
    # 0.750 -> 0.893 and stayed the highest score in the set. Better ranking
    # among related memories, no fix for the case it was chosen for.
    # `[memory] embedder = "local"` still opts in deliberately.
    #
    # auto again since 2026-09-19 (stage 5 items 1-2), because both costs
    # above are gone: the model loads in a thread after boot while recall
    # answers from hashing, vectors are persisted so it happens once, and a
    # dense recall is one matrix product fused with BM25 (13 ms p50 at 500
    # records). What it buys, measured with the real model on a 500-record
    # fixture: paraphrased facts in the top 3, hashing 0/10, hybrid 10/10.
    embedder: str = "auto"  # auto | local | openai | voyage | gemini | hashing
    recency_weight: float = 0.1  # scoring: similarity*confidence + recency_weight*recency_bonus
    # Seconds after start before the first consolidation pass (flag
    # contradictions, prune each kind to its keep count). Consolidation
    # otherwise runs only on `system.tick.sleep`, whose loop waits a
    # full `sleep_every_s` (6h) before its FIRST tick and skips it
    # entirely if the system is not RUNNING at that instant -- so a
    # session shorter than six hours pruned nothing, and the 2,000-per-
    # kind steady state `service.py::DEFAULT_KEEP_PER_KIND` describes
    # was never reached (2026-09-10). The Ledger learned exactly this
    # lesson on 2026-09-07 and carries the same field under the same
    # name shape (`[ledger] compact_after_start_s`); this is that fix
    # for the other stream that grows without bound. 0 disables.
    consolidate_after_start_s: float = 120.0
    #: How long consolidation waits for Cognition. It is the DEADLINE the
    #: providers then share: the Router gives each candidate
    #: `remaining / (still to try + 1)`, so 30 s over four providers was
    #: an 8 s slice each -- live, 2026-09-22: Together timed out, Gemini
    #: was abandoned at 8 s and its answer arrived 200 OK five seconds
    #: later, the Claude CLI got 6.9 s, and the floor "consolidated"
    #: nothing. Nobody waits on this work, so it may take its time.
    consolidate_timeout_s: float = 120.0

    @classmethod
    def from_mapping(cls, raw: Mapping) -> "Config":
        if not raw:
            return cls()
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


__all__ = ["Config"]
