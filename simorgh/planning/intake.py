"""Maps external sources into tasks (spec section 5.6): `intent.goal.stated`,
`curiosity.candidate`, `reflect.patterns.found`, and a research task's
`FOLLOW-UP`. Every path goes through the same fuzzy dedupe against every
known task description, regardless of status -- an already-done idea
must never resurface just because its own record still exists (v1
lesson, `discovery.py`'s own docstring)."""

from __future__ import annotations

from dataclasses import dataclass

from .dedupe import is_duplicate
from .model import Scope, Task
from .store import TaskStore


@dataclass
class IntakeResult:
    task: Task | None
    duplicate_of: str | None = None


class Intake:
    def __init__(self, store: TaskStore, *, dedupe_threshold: float) -> None:
        self._store = store
        self._threshold = dedupe_threshold

    def _find_duplicate(self, description: str) -> str | None:
        for tid, desc in self._store.descriptions():
            import difflib

            if difflib.SequenceMatcher(None, description, desc).ratio() >= self._threshold:
                return tid
        return None

    async def on_goal_stated(
        self, *, goal: str, origin: str, wants_project: bool, priority: int = 0, risk: str | None = None,
    ) -> IntakeResult:
        dup = self._find_duplicate(goal)
        if dup:
            return IntakeResult(None, duplicate_of=dup)
        if wants_project:
            task = await self._store.create(
                # `risk` is caller-supplied (task.create.v1.json already has the
                # field; a request omitting it keeps the previous "medium"
                # default) -- without this override a project can never be
                # created above "medium", so Plan Mode's `risk >= high ->
                # human approval` branch (07-planning.md section 5.4) would be
                # unreachable through any real message, not just untested.
                kind="project", description=goal, origin=origin, mode="plan", risk=risk or "medium",
                priority=priority, initial_status="available",  # no depends_on -> available, not pending (spec section 5.1's state diagram)
            )
        else:
            task = await self._store.create(
                kind="chat" if origin == "human" else "patch", description=goal, origin=origin,
                mode="execute", risk=risk or "low", priority=priority, initial_status="available",
            )
        return IntakeResult(task)

    async def on_candidate(
        self, *, kind: str, description: str, subject: str | None, area: str, origin: str = "curiosity",
        risk: str | None = None,
    ) -> IntakeResult:
        dup = self._find_duplicate(description)
        if dup:
            return IntakeResult(None, duplicate_of=dup)
        scope = Scope(paths=(subject,) if subject else (), network=kind == "research") if (subject or kind == "research") else None
        task = await self._store.create(
            kind=kind, description=description, subject=subject, origin=origin, mode="execute",
            risk=risk or "low", scope=scope, initial_status="available",
        )
        return IntakeResult(task)

    async def on_patterns_found(self, *, patterns: list[dict]) -> list[Task]:
        """Port of v1 `discover_improvements`: each pattern's own
        proposal text becomes a `patch` task (deduped)."""
        created: list[Task] = []
        for pattern in patterns:
            proposal = pattern.get("proposal", "")
            if not proposal or self._find_duplicate(proposal):
                continue
            task = await self._store.create(
                kind="patch", description=proposal, origin="reflection", mode="execute",
                risk="low", initial_status="available",
            )
            created.append(task)
        return created

    async def on_research_follow_up(self, *, research_task_id: str, subject: str, description: str) -> Task | None:
        if self._find_duplicate(description):
            return None
        return await self._store.create(
            kind="patch", description=description, subject=subject, origin="research",
            parent_id=research_task_id, mode="execute", risk="low",
            scope=Scope(paths=(subject,), network=False), initial_status="available",
        )


__all__ = ["Intake", "IntakeResult"]
