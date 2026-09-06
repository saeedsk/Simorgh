"""Dependency DAG (spec section 5.3): validation at creation (unknown
dependency, cycle) and readiness (`available` iff every `depends_on` id
is `completed`). v1 (`_next_task`/`next_unfinished_child`) only ever
honored creation order; this makes fan-in representable and lets
parallel Workers claim independently-ready siblings (spec section 7,
"DAG vs. creation order")."""

from __future__ import annotations

from typing import Mapping

from .model import COMPLETED, Task


class CycleError(ValueError):
    def __init__(self, task_id: str, cycle: list[str]) -> None:
        super().__init__(f"{task_id}: dependency cycle {' -> '.join(cycle)}")
        self.task_id = task_id
        self.cycle = cycle


class UnknownDependencyError(ValueError):
    def __init__(self, task_id: str, dep_id: str) -> None:
        super().__init__(f"{task_id}: unknown dependency {dep_id!r}")
        self.task_id = task_id
        self.dep_id = dep_id


def validate(task_id: str, depends_on: list[str], known: Mapping[str, Task]) -> None:
    """Raises `UnknownDependencyError`/`CycleError`; does nothing on a
    valid DAG. `known` must already contain every task except `task_id`
    itself (the one being created)."""
    for dep in depends_on:
        if dep == task_id:
            raise CycleError(task_id, [task_id, task_id])
        if dep not in known:
            raise UnknownDependencyError(task_id, dep)

    # DFS from task_id through a hypothetical graph where task_id -> depends_on,
    # and every other edge comes from `known`. A cycle exists iff we can walk
    # back to task_id.
    visiting: set[str] = set()
    path: list[str] = []

    def walk(node: str, deps: tuple[str, ...]) -> None:
        if node in visiting:
            raise CycleError(task_id, path + [node])
        visiting.add(node)
        path.append(node)
        for dep in deps:
            if dep == task_id:
                raise CycleError(task_id, path + [task_id])
            child = known.get(dep)
            walk(dep, child.depends_on if child else ())
        path.pop()
        visiting.discard(node)

    walk(task_id, tuple(depends_on))


def dependents_of(task_id: str, known: Mapping[str, Task]) -> list[str]:
    return [t.id for t in known.values() if task_id in t.depends_on]


def is_ready(task: Task, known: Mapping[str, Task]) -> bool:
    """True iff every dependency exists and is COMPLETED. An unknown
    dependency (should never happen post-validation) is treated as not
    ready rather than raising -- readiness is queried far more often
    than tasks are created, and must never crash a scheduling loop."""
    for dep_id in task.depends_on:
        dep = known.get(dep_id)
        if dep is None or dep.status != COMPLETED:
            return False
    return True


__all__ = ["CycleError", "UnknownDependencyError", "dependents_of", "is_ready", "validate"]
