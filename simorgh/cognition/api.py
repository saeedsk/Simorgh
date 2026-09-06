"""Cognition's internal protocols and value types (docs/blueprint/
subsystems/04-cognition.md section 3.4). `Provider`/`ProviderResponse`
are restated from `simorgh.contracts.protocols` for a local, typed
import surface; everything here is stdlib-only.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from simorgh.contracts.protocols import Provider, ProviderResponse  # re-exported

__all__ = [
    "Provider", "ProviderResponse", "Purpose", "Budget", "BudgetStatus",
    "PromptBlock", "AssembledContext", "CompactedContext", "ParsedOutput",
    "ProviderUnavailable", "NoRealProvider", "Paused", "ContextTooLarge",
]


class Purpose(str, enum.Enum):
    CHAT = "chat"
    DRAFT = "draft"
    PLAN = "plan"
    REVIEW = "review"
    RESEARCH = "research"
    DECOMPOSE = "decompose"
    REGROUND = "reground"
    CONSOLIDATE = "consolidate"
    ENSEMBLE = "ensemble"


class ProviderUnavailable(Exception):
    """A provider could not answer this call; the Router tries the next
    candidate (or the floor)."""


class NoRealProvider(Exception):
    """Every candidate failed and `require_real_provider` was set --
    `service.py` turns this into `error.code=no_real_provider`."""


class Paused(Exception):
    """The system paused mid-call; the in-flight result is discarded
    (04 section 8)."""


class ContextTooLarge(Exception):
    """A protected block alone exceeds the purpose's budget -- protected
    blocks are never compacted (principle 4.6), so this is a real,
    reportable failure rather than a silent truncation."""


@dataclass(frozen=True)
class Budget:
    """One purpose's per-request spend ceiling, from `[cognition.purposes.<p>]`."""

    max_tokens_in: int
    max_tokens_out: int
    max_cost_usd: float
    require_real: bool = False
    max_seconds: float = 180.0


@dataclass(frozen=True)
class BudgetStatus:
    provider: str
    calls_in_window: int
    max_calls: int | None
    spend_usd: float
    max_spend_usd: float | None
    window_seconds: float
    exhausted: bool


@dataclass(frozen=True)
class PromptBlock:
    name: str
    text: str
    protected: bool
    tokens: int


@dataclass(frozen=True)
class AssembledContext:
    blocks: tuple[PromptBlock, ...]

    def render(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text)

    def total_tokens(self) -> int:
        return sum(b.tokens for b in self.blocks)


@dataclass(frozen=True)
class CompactedContext:
    text: str
    layers_applied: tuple[int, ...]
    tokens_before: int
    tokens_after: int
    summary_ref: str | None = None


@dataclass(frozen=True)
class ParsedOutput:
    kind: str  # tool_calls | final | non_answer | edit_blocks | verdict
    text: str
    tool_calls: tuple[dict, ...] = ()
    edit_blocks: tuple[dict, ...] = ()
    verdict: bool | None = None
    non_answer: bool = False


@runtime_checkable
class Compactor(Protocol):
    async def compact(self, ctx: AssembledContext, *, limit_tokens: int, allow_summarize: bool) -> CompactedContext: ...
