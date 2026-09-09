"""`simorgh.toml [persona]` (spec section 3.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    repo_root: Path = Path(".")
    soul_path: Path = Path("docs/SOUL.md")
    baseline_valence: float = 0.0
    baseline_arousal: float = 0.0
    decay_half_life_s: float = 900.0
    decay_interval_s: float = 5.0
    history_limit: int = 200
    lexicon_weight: float = 0.15
    exclamation_arousal: float = 0.10
    outcome_nudge_success: float = 0.08
    outcome_nudge_failure: float = -0.10
    # `task.blocked` is not terminal -- Planning retries a blocked task
    # up to `max_blocked_retries` times (default 9, some as fast as every
    # `continuation_delay_seconds` = 10s for a step-budget continuation)
    # before it ever becomes `task.failed`. A single failure-sized nudge
    # per retry would let one struggling task swing mood harder than an
    # outright failure; a much smaller nudge here still gives Persona a
    # real reaction to "things aren't going smoothly" on each attempt,
    # while a task that resolves after one or two blocks barely moves
    # mood at all -- and a task that blocks many times before giving up
    # still ends up worse off than a quick clean failure, which is the
    # right shape for a protracted struggle.
    outcome_nudge_blocked: float = -0.03
    growth_cooldown_s: float = 900.0
    news_cooldown_s: float = 1800.0
    quiet_when_active_s: float = 20.0
    max_shares_per_hour: int = 4
    user_model_min_confidence: float = 0.5
    voice_max_chars: int = 600

    def resolved_soul_path(self) -> Path:
        return self.soul_path if self.soul_path.is_absolute() else self.repo_root / self.soul_path

    @classmethod
    def from_mapping(cls, data: dict | None, *, default_repo_root: Path | None = None) -> "Config":
        data = data or {}
        root = Path(data.get("repo_root", default_repo_root or Path(".")))
        baseline = data.get("baseline") or {}
        share = data.get("share") or {}
        user_model = data.get("user_model") or {}
        voice = data.get("voice") or {}
        return cls(
            repo_root=root,
            soul_path=Path(data.get("soul_path", "docs/SOUL.md")),
            baseline_valence=float(baseline.get("valence", 0.0)),
            baseline_arousal=float(baseline.get("arousal", 0.0)),
            decay_half_life_s=float(data.get("decay_half_life_s", 900.0)),
            decay_interval_s=float(data.get("decay_interval_s", 5.0)),
            history_limit=int(data.get("history_limit", 200)),
            lexicon_weight=float(data.get("lexicon_weight", 0.15)),
            exclamation_arousal=float(data.get("exclamation_arousal", 0.10)),
            outcome_nudge_success=float(data.get("outcome_nudge", {}).get("success", 0.08)) if isinstance(data.get("outcome_nudge"), dict) else 0.08,
            outcome_nudge_failure=float(data.get("outcome_nudge", {}).get("failure", -0.10)) if isinstance(data.get("outcome_nudge"), dict) else -0.10,
            outcome_nudge_blocked=float(data.get("outcome_nudge", {}).get("blocked", -0.03)) if isinstance(data.get("outcome_nudge"), dict) else -0.03,
            growth_cooldown_s=float(share.get("growth_cooldown_s", 900.0)),
            news_cooldown_s=float(share.get("news_cooldown_s", 1800.0)),
            quiet_when_active_s=float(share.get("quiet_when_active_s", 20.0)),
            max_shares_per_hour=int(share.get("max_per_hour", 4)),
            user_model_min_confidence=float(user_model.get("min_confidence_to_use", 0.5)),
            voice_max_chars=int(voice.get("max_chars", 600)),
        )
