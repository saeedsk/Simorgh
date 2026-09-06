"""Guardian configuration (09-guardian.md section 3.5). A subset of the
spec's full table -- budget/classifier/human-prompt-timeout knobs are
present but the subsystems they'd talk to (cognition, interface) don't
exist yet this phase, so those paths degrade to their documented
defaults (skip, don't block) rather than doing nothing at all.
"""

from __future__ import annotations

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
    max_consecutive_failures: int = 5
    budget_pressure_tighten_at: float = 0.9
    irreversible_requires_human: bool = True
    reversible_auto_in_guarded: bool = True
    classifier_enabled: bool = False  # cognition doesn't exist yet this phase (see README)
    classifier_timeout_s: float = 3.0
    human_prompt_timeout_s: float = 1800.0
    autonomous_origins: tuple[str, ...] = ("curiosity", "reflection", "research", "project")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "Config":
        if not data:
            return cls()
        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if "protected_subjects" in kwargs:
            kwargs["protected_subjects"] = tuple(kwargs["protected_subjects"])
        if "autonomous_origins" in kwargs:
            kwargs["autonomous_origins"] = tuple(kwargs["autonomous_origins"])
        return cls(**kwargs)
