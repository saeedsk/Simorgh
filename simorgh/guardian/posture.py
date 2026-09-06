"""Trust posture (09-guardian.md section 5.3): a projection over the
`guardian:trust` Ledger stream that only ever tightens by message --
loosening is exclusively a human editing config (`baseline_posture`) or
`system.resume` returning to it. There is deliberately no message type
that loosens posture (harness-06: "graduated trust... should go through
a human decision explicitly").
"""

from __future__ import annotations

from dataclasses import dataclass, field

_RANK = {"trusted": 2, "guarded": 1, "locked": 0}


@dataclass
class Posture:
    level: str = "guarded"
    baseline: str = "guarded"
    reasons: list[str] = field(default_factory=list)

    def tighten(self, to: str, reason: str) -> "Posture":
        """Never raises the level -- only lowers it (or leaves it
        unchanged if `to` isn't actually tighter than the current one)."""
        if _RANK.get(to, 0) < _RANK.get(self.level, 2):
            self.level = to
        self.reasons.append(reason)
        return self

    def reset_to_baseline(self) -> "Posture":
        self.level = self.baseline
        self.reasons.clear()
        return self

    def apply_event(self, event_type: str, payload: dict) -> None:
        if event_type == "tightened":
            if _RANK.get(payload["to"], 0) < _RANK.get(self.level, 2):
                self.level = payload["to"]
            self.reasons.append(payload["reason"])
        elif event_type == "reset_to_baseline":
            self.level = self.baseline
            self.reasons.clear()
