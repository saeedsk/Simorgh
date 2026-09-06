"""`[verification]` config (docs/blueprint/subsystems/10-verification.md
section 3.5). Defaults match the spec table exactly, including the v1
constants (`docstring.*`) ported verbatim from `src/orchestrator/self_patch.py`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from .api import Rigor

_DEFAULT_RIGOR_BY_KIND = {
    "chat": "NONE",
    "research": "LIGHT",
    "project_child_readonly": "LIGHT",
    "skill": "FULL",
    "patch": "FULL",
    "self_patch": "FULL",
    "plan": "STANDARD",
}
_DEFAULT_RIGOR_BY_REVERSIBILITY = {
    "read_only": "LIGHT",
    "reversible": "STANDARD",
    "irreversible": "FULL",
}
_DEFAULT_INVARIANTS = {
    "src/main.py": ["AuditGate(", "audit_gate.review(", "apply_proposal("],
    "simorgh/execution/": ["verifier.verify("],
    "simorgh/guardian/": ["Pipeline("],
}


def _rigor(name: str) -> Rigor:
    return Rigor[name.upper()]


@dataclass(frozen=True)
class VerificationConfig:
    rigor_by_kind: dict[str, Rigor] = field(
        default_factory=lambda: {k: _rigor(v) for k, v in _DEFAULT_RIGOR_BY_KIND.items()}
    )
    rigor_by_reversibility: dict[str, Rigor] = field(
        default_factory=lambda: {k: _rigor(v) for k, v in _DEFAULT_RIGOR_BY_REVERSIBILITY.items()}
    )
    checklist_max_items: int = 6
    checklist_min_answered_fraction: float = 0.67
    docstring_min_chars_to_protect: int = 80
    docstring_shrink_threshold: float = 0.3
    invariants: dict[str, list[str]] = field(default_factory=lambda: dict(_DEFAULT_INVARIANTS))
    test_suite_require_count_not_below_baseline: bool = True
    sandbox_smoke_kinds: tuple[str, ...] = ("skill",)
    trajectory_wasted_step_ratio_warn: float = 0.5
    review_require_real_provider: bool = True
    plan_review_max_steps: int = 8
    action_timeout_seconds: float = 5.0
    isolated_suite_timeout_seconds: float = 120.0
    max_denied_actions: int = 2
    forced_rigor: Rigor | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "VerificationConfig":
        data = dict(data or {})
        kwargs: dict[str, Any] = {}
        if "rigor" in data:
            rigor = data["rigor"]
            if "by_kind" in rigor:
                merged = dict(_DEFAULT_RIGOR_BY_KIND) | dict(rigor["by_kind"])
                kwargs["rigor_by_kind"] = {k: _rigor(v) for k, v in merged.items()}
            if "by_reversibility" in rigor:
                merged = dict(_DEFAULT_RIGOR_BY_REVERSIBILITY) | dict(rigor["by_reversibility"])
                kwargs["rigor_by_reversibility"] = {k: _rigor(v) for k, v in merged.items()}
        if "checklist" in data:
            c = data["checklist"]
            if "max_items" in c:
                kwargs["checklist_max_items"] = int(c["max_items"])
            if "min_answered_fraction" in c:
                kwargs["checklist_min_answered_fraction"] = float(c["min_answered_fraction"])
        if "docstring" in data:
            d = data["docstring"]
            if "min_chars_to_protect" in d:
                kwargs["docstring_min_chars_to_protect"] = int(d["min_chars_to_protect"])
            if "shrink_threshold" in d:
                kwargs["docstring_shrink_threshold"] = float(d["shrink_threshold"])
        if "invariants" in data:
            kwargs["invariants"] = dict(_DEFAULT_INVARIANTS) | dict(data["invariants"])
        if "test_suite" in data and "require_count_not_below_baseline" in data["test_suite"]:
            kwargs["test_suite_require_count_not_below_baseline"] = bool(
                data["test_suite"]["require_count_not_below_baseline"]
            )
        if "sandbox_smoke" in data and "kinds" in data["sandbox_smoke"]:
            kwargs["sandbox_smoke_kinds"] = tuple(data["sandbox_smoke"]["kinds"])
        if "trajectory" in data and "wasted_step_ratio_warn" in data["trajectory"]:
            kwargs["trajectory_wasted_step_ratio_warn"] = float(data["trajectory"]["wasted_step_ratio_warn"])
        if "review" in data and "require_real_provider" in data["review"]:
            kwargs["review_require_real_provider"] = bool(data["review"]["require_real_provider"])
        if "plan_review" in data and "max_steps" in data["plan_review"]:
            kwargs["plan_review_max_steps"] = int(data["plan_review"]["max_steps"])
        env_rigor = os.environ.get("SIMORGH_VERIFICATION_RIGOR")
        if env_rigor:
            kwargs["forced_rigor"] = _rigor(env_rigor)
        return cls(**kwargs)
