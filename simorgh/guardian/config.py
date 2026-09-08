"""Guardian configuration (09-guardian.md section 3.5). A subset of the
spec's full table. `budget_pressure_tighten_at` and `max_consecutive_
failures` are live as of Phase 4 Wave 2 (`service.py` subscribes to
`cognition.provider.status`/`reflect.drift.detected`/`reflect.health.
finding`/`task.*` and feeds `Posture.tighten`); `classifier_enabled`
and `human_prompt_timeout_s` still degrade to their documented defaults
(skip, don't block) since Interface's `ui.prompt` round-trip and a real
classifier subsystem don't exist yet this phase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

# v1 PROTECTED_SUBJECTS (src/orchestrator/audit.py), extended with the
# v2 substrate per 09-guardian.md section 3.5 -- the system can evolve
# every cognitive subsystem but never the parts that decide what it may
# do (AGI-04 section 9, corrigibility).
DEFAULT_PROTECTED_SUBJECTS: tuple[str, ...] = (
    "docs/SOUL.md",
    "src/orchestrator/soul.py",
    "src/orchestrator/audit.py",
    "src/orchestrator/apply.py",
    "src/orchestrator/self_patch.py",
    "simorgh/guardian/",
    "simorgh/execution/",
    "simorgh/contracts/",
    "simorgh/kernel/",
    "simorgh.toml",
    # The bootloader and its launcher. They are the mechanism that gates
    # a change and undoes a bad one, and an observer showed on
    # 2026-09-08 that one auto-approved commit could remove it:
    # `run_python_sandboxed` rewrote simloader.py, `git_commit` (which
    # has no write-scope check) committed it, and the neutered loader
    # then printed "gate passed (totally)" and booted. Corrigibility
    # means the undo mechanism is not the system's to edit.
    "simloader.py",
    "sim.sh",
)

# Ported verbatim from src/orchestrator/audit.py's _DENYLIST_PATTERNS --
# same patterns, same directive citations. Kept here (not imported from
# src/) since simorgh/ may only import simorgh.contracts + stdlib.
DEFAULT_DENYLIST: dict[str, str] = {
    r"\bos\.system\b": "shells out via os.system instead of the sandbox (Directive 1)",
    r"\bsubprocess\.(Popen|run|call)\b": "spawns its own subprocess instead of using the sandbox (Directive 1)",
    r"\bsocket\.\b": "opens raw network sockets (Directive 1, Directive 5)",
    r"\burllib\.request\b": "makes network requests directly instead of the reviewed web_fetch tool (Directive 1, Directive 5)",
    r"\bhttp\.client\b": "makes raw HTTP requests instead of the reviewed web_fetch tool (Directive 1, Directive 5)",
    r"\brequests\.(get|post|put|delete|patch|head)\s*\(": "makes network requests via requests instead of the reviewed web_fetch tool (Directive 1, Directive 5)",
    r"\bftplib\b": "opens FTP connections (Directive 1, Directive 5)",
    r"\bsmtplib\b": "sends email (Directive 1, Directive 5)",
    r"\beval\s*\(": "uses eval on dynamic input (Directive 1)",
    r"\b__import__\s*\(\s*['\"]os['\"]": "dynamically imports os to route around static checks (Directive 1)",
    r"\bctypes\b": "loads ctypes, a common sandbox-escape vector (Directive 1)",
}


@dataclass(frozen=True)
class Config:
    mode: str = "guarded"  # observe | plan | guarded | trusted | locked
    baseline_posture: str = "guarded"
    approval_ttl_s: float = 120.0
    protected_subjects: tuple[str, ...] = DEFAULT_PROTECTED_SUBJECTS
    denylist: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_DENYLIST))
    immunity_similarity_threshold: float = 0.85
    # The creator, 2026-09-07: "more freedom in autonomously working and
    # evolving without too much gate". A hard `locked` posture that only a
    # human typing `resume` could undo turned every transient problem (a
    # budget-driven floor reply pinning valence, a short failure streak)
    # into a stall lasting the rest of the session. Three loosenings:
    # a health finding now tightens to `guarded` (still gated, still
    # working) rather than `locked`; the failure streak that does lock
    # is three times longer; and a lock expires back to baseline on its
    # own after `lock_ttl_s` (0 disables -- the old behavior).
    max_consecutive_failures: int = 15
    health_critical_tightens_to: str = "guarded"  # guarded | locked
    lock_ttl_s: float = 600.0
    budget_pressure_tighten_at: float = 0.9
    irreversible_requires_human: bool = True
    reversible_auto_in_guarded: bool = True
    classifier_enabled: bool = False  # cognition doesn't exist yet this phase (see README)
    classifier_timeout_s: float = 3.0
    human_prompt_timeout_s: float = 1800.0
    autonomous_origins: tuple[str, ...] = ("curiosity", "reflection", "research", "project")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "Config":
        """`[guardian]` table -> Config, with a `SIMORGH_GUARDIAN_AUTO_APPROVE`
        environment override (same `SIMORGH_<SECTION>_<KEY>`-after-the-file
        precedence `kernel/config.py`'s module docstring describes, and
        `bus.config`/`ledger.config` already apply) for the one field a
        human actually wants to flip from a shell without editing
        `simorgh.toml`: `irreversible_requires_human` -- ReversibilityRule's
        last-resort gate for an action nothing else in the pipeline denied,
        the "does an irreversible self-modification need my eyes on it
        first" switch (`rules.py::ReversibilityRule`). `1`/`true`/`yes`/`on`
        means auto-approve (`irreversible_requires_human=False`); anything
        else means require it. Checked whether or not the file set the
        field -- the shell is meant to win outright, not just fill a gap."""
        kwargs = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        if "protected_subjects" in kwargs:
            kwargs["protected_subjects"] = tuple(kwargs["protected_subjects"])
        if "autonomous_origins" in kwargs:
            kwargs["autonomous_origins"] = tuple(kwargs["autonomous_origins"])
        env_auto_approve = os.environ.get("SIMORGH_GUARDIAN_AUTO_APPROVE")
        if env_auto_approve is not None:
            kwargs["irreversible_requires_human"] = env_auto_approve.strip().lower() not in ("1", "true", "yes", "on")
        return cls(**kwargs)
