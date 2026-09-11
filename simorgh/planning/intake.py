"""Maps external sources into tasks (spec section 5.6): `intent.goal.stated`,
`curiosity.candidate`, `reflect.patterns.found`, and a research task's
`FOLLOW-UP`. Every path goes through the same fuzzy dedupe against every
known task description, regardless of status -- an already-done idea
must never resurface just because its own record still exists (v1
lesson, `discovery.py`'s own docstring)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from .dedupe import is_duplicate
from .model import Scope, Task
from .store import TaskStore


_WAITING = frozenset({"pending", "available", "blocked"})


@dataclass
class IntakeResult:
    task: Task | None
    duplicate_of: str | None = None
    # Why an autonomous candidate was NOT created: the backlog is at
    # `max_backlog`. Never set for a human's request.
    deferred: str | None = None
    # How much work was already waiting when this was accepted, so the
    # reply can say "queued behind N" instead of nothing.
    backlog: int = 0


class Intake:
    def __init__(self, store: TaskStore, *, dedupe_threshold: float, max_backlog: int = 0,
                 autonomous_origins: tuple[str, ...] = ("curiosity", "reflection", "research", "project", "assistant")) -> None:
        self._store = store
        self._threshold = dedupe_threshold
        self._max_backlog = max(0, int(max_backlog))
        self._autonomous = frozenset(autonomous_origins)

    def backlog(self) -> int:
        """Tasks waiting for a worker: pending, available, or blocked."""
        return sum(1 for t in self._store.index.tasks.values() if t.status in _WAITING)

    def _deferral(self, origin: str) -> str | None:
        """Why a candidate from `origin` must wait, or None.

        Only Sim's own origins are held back. A human (or a benchmark
        driving Sim on a human's behalf) asked for the work; deferring
        it would be refusing them for the sake of a queue they may not
        even know about. Live-caught 2026-09-10: 330 tasks queued, three
        workers, and nothing anywhere asking whether adding a 331st made
        sense."""
        if not self._max_backlog or origin not in self._autonomous:
            return None
        waiting = self.backlog()
        if waiting < self._max_backlog:
            return None
        return (f"backlog full: {waiting} tasks already waiting, at the [planning] max_backlog of "
                f"{self._max_backlog} -- a {origin} candidate waits until the queue drains")

    def _find_duplicate(
        self, description: str, *, origin: str = "curiosity", distinguish: str | None = None,
        subject: str | None = None,
    ) -> str | None:
        """Live-caught (the creator, 2026-09-07): three different `improve`
        requests -- different paths, different wording -- each came back
        as the *first* one's id, and the later two never ran. The 45%
        fuzzy match here exists for the autonomous streams (curiosity
        candidates, reflection patterns, research follow-ups), where the
        same idea genuinely does resurface in slightly different words. A
        human typing a request is authoritative: if they ask again, or
        ask something merely similar, they get a new task, always.

        `benchmark` is exempt for the same reason (observer, 2026-09-08,
        GAIA deep dive): every case is a distinct, deliberately chosen
        question, not a resurfacing idea -- but `Runner.prompt()` appends
        the same ~330-char answer-format boilerplate to every question,
        which alone pushed unrelated GAIA questions (e.g. Kipchoge's
        marathon and Mercedes Sosa's albums) over this threshold, so
        5 of 7 cases in one run silently got handed back an unrelated,
        already-completed task_id and were never actually asked.

        `distinguish`, when given, is a substring the *matched* existing
        description must also contain for the match to count -- the same
        boilerplate problem as `benchmark` above, but on the other side:
        Reflection's own `reflect.patterns.found` proposals for two
        genuinely different `task_type`s ("'patch' tasks failed 5/5
        recent outcomes (100%) -- worth reviewing..." vs the same
        sentence for `'unknown'`) differ by one quoted word inside a
        long shared template, which alone measured ~0.93 similarity --
        well past this threshold -- so the second pattern silently
        collapsed into the first's task and was never surfaced
        (observer, 2026-09-08, w8-04, reproduced against a real Kernel).
        Passing the pattern's own `task_type` here keeps the fuzzy match
        but requires it actually be about the same task_type.

        `subject`, when given, narrows the same way but by exact field
        equality rather than substring: Curiosity's own `TargetedIdeaProposer`
        prompt (`curiosity/idea.py`) forces the model to reply with ONLY a
        one-line `PATCH ::`/`RESEARCH ::` description and explicitly forbids
        it from stating the file path in that line ("not even the file
        path, that part is already decided") -- so the description the
        model returns for two *genuinely different* target files is often
        near-identical common phrasing ("Add type hints to the public
        functions in this file/module for a clearer interface."), which
        measured ~0.96 similarity here for two different real files, well
        past this threshold, and `on_candidate` never passed the sampled
        `Target`'s own subject to distinguish them -- so the second
        candidate silently collapsed into the first's task (observer,
        2026-09-08, w8-06, reproduced against a real TaskStore/Ledger).
        `subject` requires the matched existing task's own subject to be
        exactly the same file for the match to count."""
        if origin in ("human", "benchmark"):
            return None
        for tid, desc, existing_subject in self._store.descriptions():
            if distinguish is not None and distinguish not in desc:
                continue
            if subject is not None and existing_subject != subject:
                continue
            if difflib.SequenceMatcher(None, description, desc).ratio() >= self._threshold:
                return tid
        return None

    async def on_goal_stated(
        self, *, goal: str, origin: str, wants_project: bool, priority: int = 0, risk: str | None = None,
        max_steps: int | None = None,
    ) -> IntakeResult:
        dup = self._find_duplicate(goal, origin=origin)
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
                priority=priority, initial_status="available", max_steps=max_steps,  # no depends_on -> available, not pending (spec section 5.1's state diagram)
            )
        else:
            task = await self._store.create(
                kind="chat" if origin == "human" else "patch", description=goal, origin=origin,
                mode="execute", risk=risk or "low", priority=priority, initial_status="available",
                max_steps=max_steps,
            )
        return IntakeResult(task)

    async def on_candidate(
        self, *, kind: str, description: str, subject: str | None, area: str, origin: str = "curiosity",
        risk: str | None = None, max_steps: int | None = None,
    ) -> IntakeResult:
        dup = self._find_duplicate(description, origin=origin, subject=subject)
        if dup:
            return IntakeResult(None, duplicate_of=dup)
        deferred = self._deferral(origin)
        if deferred:
            return IntakeResult(None, deferred=deferred)
        waiting = self.backlog()
        scope = Scope(paths=(subject,) if subject else (), network=kind == "research") if (subject or kind == "research") else None
        task = await self._store.create(
            kind=kind, description=description, subject=subject, origin=origin, mode="execute",
            risk=risk or "low", scope=scope, initial_status="available", max_steps=max_steps,
        )
        return IntakeResult(task, backlog=waiting)

    async def on_patterns_found(self, *, patterns: list[dict]) -> list[Task]:
        """Port of v1 `discover_improvements`: each pattern's own
        proposal text becomes a `patch` task (deduped)."""
        created: list[Task] = []
        for pattern in patterns:
            proposal = pattern.get("proposal", "")
            if not proposal:
                continue
            if self._find_duplicate(proposal, distinguish=pattern.get("task_type")):
                continue
            if self._deferral("reflection"):
                break  # the queue is full; the patterns will be found again
            task = await self._store.create(
                kind="patch", description=proposal, origin="reflection", mode="execute",
                risk="low", initial_status="available",
            )
            created.append(task)
        return created

    async def on_research_follow_up(self, *, research_task_id: str, subject: str, description: str) -> Task | None:
        if self._find_duplicate(description, subject=subject):
            return None
        if self._deferral("research"):
            return None
        return await self._store.create(
            kind="patch", description=description, subject=subject, origin="research",
            parent_id=research_task_id, mode="execute", risk="low",
            scope=Scope(paths=(subject,), network=False), initial_status="available",
        )


__all__ = ["Intake", "IntakeResult"]
