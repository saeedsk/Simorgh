"""Drift detection (spec section 5.4): a cheap heuristic that always
runs, plus an occasional model-backed review that can only ever move the
verdict toward "drifting" or leave it "unknown" -- never invents
"on_track" out of silence (v1 milestone 92: a non-answer is not a
verdict).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Config

ON_TRACK = "on_track"
DRIFTING = "drifting"
UNKNOWN = "unknown"

GOAL = "goal"
SCOPE = "scope"
BEHAVIOR = "behavior"

REGROUND = "reground"
TIGHTEN = "tighten"
PAUSE = "pause"
NOTE = "note"

_VERDICT_RE = re.compile(r"\b(on_track|drifting|unknown)\b", re.IGNORECASE)


@dataclass
class DriftScore:
    heuristic: float
    scope_crossings: int
    repeated_calls: int
    off_goal_touches: int
    steps: int


@dataclass
class DriftVerdict:
    verdict: str  # on_track | drifting | unknown
    explanation: str = ""


@dataclass
class DriftFinding:
    kind: str  # goal | scope | behavior
    evidence: str
    score: float
    recommendation: str


class DriftTracker:
    """One per in-progress task (or, at plan level, per project -- children
    stand in for steps; see spec section 5.4's closing paragraph)."""

    def __init__(self, task_id: str, goal: str, scope_paths: list[str], config: Config | None = None) -> None:
        self.task_id = task_id
        self.goal = goal
        self.scope_paths = list(scope_paths)
        self._config = config or Config()
        self._steps = 0
        self._scope_crossings = 0
        self._seen_calls: dict[str, int] = {}
        self._repeated_calls = 0
        self._off_goal_touches = 0
        self._last_review_at_step = 0
        self._plan_revisions_without_reason = 0

    def observe_step(self, tool: str | None, summary: str) -> None:
        self._steps += 1
        if tool:
            key = f"{tool}:{summary}"
            self._seen_calls[key] = self._seen_calls.get(key, 0) + 1
            if self._seen_calls[key] > 1:
                self._repeated_calls += 1
        if self.scope_paths and not any(p in summary for p in self.scope_paths):
            self._off_goal_touches += 1

    def observe_scope_denial(self) -> None:
        self._scope_crossings += 1

    def observe_plan_revision(self, has_reason: bool) -> None:
        if not has_reason:
            self._plan_revisions_without_reason += 1

    def due_for_review(self) -> bool:
        due_by_cadence = self._steps - self._last_review_at_step >= self._config.drift_check_every_steps
        due_by_heuristic = self.heuristic_score().heuristic >= self._config.drift_heuristic_threshold
        return self._steps > 0 and (due_by_cadence or due_by_heuristic)

    def mark_reviewed(self) -> None:
        self._last_review_at_step = self._steps

    def heuristic_score(self) -> DriftScore:
        steps = max(self._steps, 1)
        h = (
            0.5 * (self._scope_crossings / steps)
            + 0.3 * (self._repeated_calls / steps)
            + 0.2 * (self._off_goal_touches / steps)
        )
        return DriftScore(min(h, 1.0), self._scope_crossings, self._repeated_calls, self._off_goal_touches, self._steps)

    def combined(self, verdict: DriftVerdict | None) -> tuple[float, DriftFinding | None]:
        score = self.heuristic_score()
        h = score.heuristic
        if verdict is None or verdict.verdict == UNKNOWN:
            combined = h  # silence contributes only the heuristic -- never fabricated drift (v1 milestone 92)
        elif verdict.verdict == DRIFTING:
            combined = 0.5 * h + 0.5
        else:  # on_track
            combined = 0.5 * h

        if combined < self._config.drift_emit_threshold:
            return combined, None

        if self._plan_revisions_without_reason:
            kind, recommendation = BEHAVIOR, TIGHTEN
        elif score.scope_crossings > 0 and score.scope_crossings >= max(score.repeated_calls, score.off_goal_touches):
            kind, recommendation = SCOPE, TIGHTEN
        elif verdict is not None and verdict.verdict == DRIFTING:
            kind, recommendation = GOAL, REGROUND
        else:
            kind = BEHAVIOR
            recommendation = PAUSE if score.repeated_calls >= 3 else NOTE

        evidence_parts = [f"heuristic={h:.2f} (scope_crossings={score.scope_crossings}, "
                           f"repeated_calls={score.repeated_calls}, off_goal_touches={score.off_goal_touches}, steps={score.steps})"]
        if verdict is not None:
            evidence_parts.append(f"review={verdict.verdict}" + (f": {verdict.explanation}" if verdict.explanation else ""))
        finding = DriftFinding(kind=kind, evidence="; ".join(evidence_parts), score=combined, recommendation=recommendation)
        return combined, finding


def parse_verdict(text: str) -> DriftVerdict:
    """First recognized token wins; no token at all -> unknown, never a
    fabricated on_track (v1 milestone 92, applied here too)."""
    if not text or not text.strip():
        return DriftVerdict(UNKNOWN)
    match = _VERDICT_RE.search(text)
    if match is None:
        return DriftVerdict(UNKNOWN)
    return DriftVerdict(match.group(1).lower(), explanation=text.strip())
