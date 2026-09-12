"""Cognition configuration (docs/blueprint/subsystems/04-cognition.md
section 3.5). Every field has a working default so `[cognition]` may be
absent entirely -- the floor provider always answers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from .api import Budget
from .providers import together as together_provider

DEFAULT_PURPOSE_BUDGETS: dict[str, Budget] = {
    "chat": Budget(12_000, 1_000, 0.05),
    "draft": Budget(40_000, 8_000, 0.5),
    "plan": Budget(24_000, 2_000, 0.2, require_real=False),
    "review": Budget(12_000, 1_000, 0.05, require_real=False),
    "research": Budget(24_000, 2_000, 0.2),
    "decompose": Budget(16_000, 1_000, 0.1),
    "reground": Budget(8_000, 512, 0.02, require_real=False),
    "consolidate": Budget(16_000, 2_000, 0.1),
    "ensemble": Budget(24_000, 2_000, 0.5, require_real=True),
}


@dataclass(frozen=True)
class ProviderConfig:
    max_calls: int = 500
    window_seconds: float = 18_000.0
    max_spend_usd: float | None = None
    timeout_seconds: float = 180.0
    model: str = ""
    # Per 1M tokens. `price_cached_in` defaults to `price_in` when left at
    # 0 (see `RollingWindowBudget.estimate_cost`) -- a provider with no
    # cache tier prices every prompt token the same way.
    price_in: float = 0.0
    price_out: float = 0.0
    price_cached_in: float = 0.0


@dataclass(frozen=True)
class Config:
    # The creator, 2026-09-07: Together is Sim's LLM now, GLM-5.3-Flash the
    # default model. It leads the order, so it is what answers unless it is
    # unavailable (no TOGETHER_API_KEY) or out of budget; the Claude Code
    # CLI and Gemini stay behind it as failover, and the floor behind them.
    provider_order: tuple[str, ...] = ("together", "claude_code_cli", "gemini", "floor")
    providers: Mapping[str, ProviderConfig] = field(default_factory=lambda: {
        "together": ProviderConfig(
            # 1500 until 2026-09-11, when a spoken conversation reached
            # it at 20:32 with 86 cents of the $2 spent, and every turn
            # after that silently went to the Claude Code CLI: five
            # times slower and two hundred times the reported cost. A
            # voice session is a hundred calls an hour; the dollar cap
            # below is the real guard.
            max_calls=int(os.environ.get("SIMORGH_LLM_DAILY_MAX_CALLS", "6000")),
            window_seconds=86_400.0,
            max_spend_usd=float(os.environ.get("SIMORGH_LLM_DAILY_BUDGET_USD", "2.0")),
            timeout_seconds=180.0,
            # Published GLM-5.3-Flash pricing, per 1M tokens. These drive
            # the Router's *pre-call* estimate; the real bill comes from
            # the provider's own cache-aware arithmetic on the response.
            model=together_provider.DEFAULT_MODEL,
            price_in=together_provider.PRICE_IN,
            price_out=together_provider.PRICE_OUT,
            price_cached_in=together_provider.PRICE_CACHED_IN,
        ),
        "claude_code_cli": ProviderConfig(
            max_calls=int(os.environ.get("SIMORGH_CLAUDE_CODE_MAX_CALLS", "500")),
            window_seconds=18_000.0, timeout_seconds=180.0,
        ),
        "gemini": ProviderConfig(
            max_calls=int(os.environ.get("SIMORGH_LLM_DAILY_MAX_CALLS", "1500")),
            window_seconds=86_400.0,
            max_spend_usd=float(os.environ.get("SIMORGH_LLM_DAILY_BUDGET_USD", "2.0")),
            model="gemini-3.8-flash", price_in=0.75, price_out=3.75,
        ),
    })
    purposes: Mapping[str, Budget] = field(default_factory=lambda: dict(DEFAULT_PURPOSE_BUDGETS))
    # Compaction thresholds (04-cognition.md section 3.5's `compaction.thresholds`
    # table): L1 at 100% of the per-tool-result cap, L2 at 90%, L3 at 95%,
    # L4 always, L5 at 100% (and only when the caller sets allow_summarize).
    tool_result_max_tokens: int = 2_000
    snip_trigger_fraction: float = 0.90
    snip_target_fraction: float = 0.85
    snip_keep_last_segments: int = 4
    microcompact_trigger_fraction: float = 0.95
    collapse_keep_full_segments: int = 4
    # Layer 4 collapses every older turn to a one-line headline. It used
    # to run at any fill level, which is what the spec's "read-time
    # projection" reads like -- and at 10% of budget it throws away the
    # file the model read two steps ago for no gain at all. Observed
    # 2026-09-10: 25 think calls of 3.1k-6.5k tokens against a 40k
    # limit, `compaction=['4']` on nearly all of them, and the task
    # re-read the same two documents five times before blocking with
    # nothing written.
    #
    # The threshold keeps the blueprint's own worked example intact: S1
    # (04-cognition.md section 12) assembles 5,800 tokens against a 12k
    # limit -- 0.483 -- and is described as collapsing turns 1-2, so any
    # trigger at or below that still behaves as specified. Below it,
    # there is room to spare and nothing to gain by forgetting.
    collapse_trigger_fraction: float = 0.45
    availability_poll_seconds: float = 30.0
    assembly_request_timeout: float = 2.0  # persona.voice / self.summary -- omitted on timeout, not fatal

    @classmethod
    def from_mapping(cls, raw: Mapping) -> "Config":
        if not raw:
            return cls()
        kwargs = {}
        if "providers" in raw:
            order = list(cls().provider_order)
            kwargs["providers"] = {**cls().providers, **{
                k: ProviderConfig(**v) for k, v in raw["providers"].items() if isinstance(v, Mapping)
            }}
        if "provider_order" in raw:
            kwargs["provider_order"] = tuple(raw["provider_order"])
        if "purposes" in raw:
            kwargs["purposes"] = {**cls().purposes, **{
                k: Budget(**v) for k, v in raw["purposes"].items() if isinstance(v, Mapping)
            }}
        for key in (
            "tool_result_max_tokens", "snip_trigger_fraction", "snip_target_fraction",
            "snip_keep_last_segments", "microcompact_trigger_fraction", "collapse_keep_full_segments",
            "collapse_trigger_fraction",
            "availability_poll_seconds", "assembly_request_timeout",
        ):
            if key in raw:
                kwargs[key] = raw[key]
        return cls(**kwargs)


__all__ = ["Config", "ProviderConfig", "DEFAULT_PURPOSE_BUDGETS"]
