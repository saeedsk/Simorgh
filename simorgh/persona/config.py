"""`simorgh.toml [persona]` (spec section 3.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # The repository this package lives in, not the process's cwd: the
    # Kernel passes no default_repo_root, so Sim booted from anywhere else
    # (the loader, a trial copy, a service manager) silently read no SOUL.md
    # and fell back to "You are Simorgh." (found writing persona's contract,
    # 2026-09-19; Reflection fixed the same thing with its own _repo_root).
    repo_root: Path = Path(__file__).resolve().parents[2]
    soul_path: Path = Path("docs/SOUL.md")
    baseline_valence: float = 0.0
    baseline_arousal: float = 0.0
    decay_half_life_s: float = 900.0
    decay_interval_s: float = 5.0
    # Decay is announced (bus + ledger) only once the mood has drifted
    # this far from the last ANNOUNCED state. It used to compare each
    # 5 s tick with the one before, so a slow drift announced every tick:
    # 44,444 of 47,784 persona:state events (2026-09-18 evaluation, V6).
    decay_announce_delta: float = 0.02
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
    voice_max_chars: int = 600

    def resolved_soul_path(self) -> Path:
        return self.soul_path if self.soul_path.is_absolute() else self.repo_root / self.soul_path

    @classmethod
    def from_mapping(cls, data: dict | None, *, default_repo_root: Path | None = None) -> "Config":
        data = data or {}
        root = Path(data.get("repo_root", default_repo_root or Path(__file__).resolve().parents[2]))
        baseline = data.get("baseline") or {}
        voice = data.get("voice") or {}
        return cls(
            repo_root=root,
            soul_path=Path(data.get("soul_path", "docs/SOUL.md")),
            baseline_valence=float(baseline.get("valence", 0.0)),
            baseline_arousal=float(baseline.get("arousal", 0.0)),
            decay_half_life_s=float(data.get("decay_half_life_s", 900.0)),
            decay_interval_s=float(data.get("decay_interval_s", 5.0)),
            decay_announce_delta=float(data.get("decay_announce_delta", 0.02)),
            history_limit=int(data.get("history_limit", 200)),
            lexicon_weight=float(data.get("lexicon_weight", 0.15)),
            exclamation_arousal=float(data.get("exclamation_arousal", 0.10)),
            outcome_nudge_success=float(data.get("outcome_nudge", {}).get("success", 0.08)) if isinstance(data.get("outcome_nudge"), dict) else 0.08,
            outcome_nudge_failure=float(data.get("outcome_nudge", {}).get("failure", -0.10)) if isinstance(data.get("outcome_nudge"), dict) else -0.10,
            outcome_nudge_blocked=float(data.get("outcome_nudge", {}).get("blocked", -0.03)) if isinstance(data.get("outcome_nudge"), dict) else -0.03,
            voice_max_chars=int(voice.get("max_chars", 600)),
        )
