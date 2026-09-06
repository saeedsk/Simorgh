"""In-process projections Curiosity keeps of task/project lifecycle
(spec section 4). Deciding "is the backlog empty" is *shared*: Planning
owns the task streams; Curiosity only ever watches the events go by on
the bus and keeps its own running counters -- never reads Planning's
Ledger streams directly, so the two stay decoupled (spec section 1,
"explicit non-responsibilities"). A restart starts these at zero and
they re-converge from the next few ticks' worth of events; this is
acceptable because emptiness only ever gates *whether* to explore this
tick, never anything durable.
"""

from __future__ import annotations

import time
from collections import deque


class BacklogCounter:
    """Unfinished-task count, from `task.created`/`task.completed`/
    `task.failed{terminal}`/`task.blocked`. A `blocked` task with
    `retry_after` in the future counts as *not* blocking exploration
    (spec open question 2: "treat as empty for exploration")."""

    def __init__(self) -> None:
        self._open: set[str] = set()
        self._blocked_with_future_retry: set[str] = set()

    def on_created(self, task_id: str) -> None:
        self._open.add(task_id)

    def on_completed(self, task_id: str) -> None:
        self._open.discard(task_id)
        self._blocked_with_future_retry.discard(task_id)

    def on_failed(self, task_id: str, *, terminal: bool) -> None:
        if terminal:
            self._open.discard(task_id)
        self._blocked_with_future_retry.discard(task_id)

    def on_blocked(self, task_id: str, *, retry_after: float | None, now: float) -> None:
        if retry_after is not None and retry_after > now:
            self._blocked_with_future_retry.add(task_id)
        else:
            self._blocked_with_future_retry.discard(task_id)

    @property
    def effective_count(self) -> int:
        return len(self._open - self._blocked_with_future_retry)

    @property
    def raw_count(self) -> int:
        return len(self._open)


class AreaStaleness:
    """Seconds since an area was last touched, from `task.completed{subject}`
    and `learn.self_patch.applied{subject}`."""

    def __init__(self) -> None:
        self._last_touched: dict[str, float] = {}

    def touch(self, area: str, at: float) -> None:
        self._last_touched[area] = max(self._last_touched.get(area, 0.0), at)

    def age(self, area: str, now: float) -> float | None:
        last = self._last_touched.get(area)
        return None if last is None else max(0.0, now - last)

    def snapshot(self, areas: list[str], now: float) -> dict[str, float | None]:
        return {a: self.age(a, now) for a in areas}


class ActiveProject:
    """Whether a curiosity-proposed project is currently in flight, so
    the rare project-proposal path never fires twice concurrently. Set
    optimistically on proposal, cleared by `task.created{kind: project}`
    echo or by a 60s timeout (spec section 5.4)."""

    def __init__(self, confirm_timeout: float = 60.0) -> None:
        self._confirm_timeout = confirm_timeout
        self._proposed_at: float | None = None
        self._confirmed = False

    def mark_proposed(self, now: float) -> None:
        self._proposed_at = now
        self._confirmed = False

    def confirm(self) -> None:
        self._confirmed = True

    def on_project_finished(self) -> None:
        self._proposed_at = None
        self._confirmed = False

    def is_active(self, now: float) -> bool:
        if self._proposed_at is None:
            return False
        if not self._confirmed and (now - self._proposed_at) > self._confirm_timeout:
            self._proposed_at = None
            return False
        return True


class RecentCandidates:
    """A short ring of recently-proposed (subject, description) pairs --
    session-local, not the backlog dedupe (that's Planning's job): just
    enough to avoid an obviously wasteful immediate resend (spec
    section 7)."""

    def __init__(self, maxlen: int = 30, similarity_threshold: float = 0.6) -> None:
        self._ring: deque[tuple[str, str]] = deque(maxlen=maxlen)
        self._threshold = similarity_threshold

    def add(self, subject: str, description: str) -> None:
        self._ring.append((subject, description))

    def recent_subjects(self, limit: int) -> list[str]:
        return [s for s, _ in list(self._ring)[-limit:]]

    def similar(self, description: str) -> bool:
        import difflib

        return any(
            difflib.SequenceMatcher(None, description, existing).ratio() >= self._threshold
            for _, existing in self._ring
        )
