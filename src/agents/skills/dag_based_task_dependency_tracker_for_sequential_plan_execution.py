"""DAG-based task dependency tracker for sequential plan execution."""

from enum import Enum
import inspect
from typing import Any, Callable, Dict, List, Optional, Set, Union


class TaskState(str, Enum):
    """Execution states for tasks in a DAG."""
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CycleError(ValueError):
    """Raised when task dependencies contain a cycle."""
    pass


class TaskDependencyTracker:
    """Tracks tasks and their dependencies in a Directed Acyclic Graph (DAG)

    for sequential plan execution workflows.
    """

    def __init__(self, tasks: Optional[Dict[str, List[str]]] = None) -> None:
        self.dependencies: Dict[str, Set[str]] = {}  # task -> set of dependencies (upstream)
        self.dependents: Dict[str, Set[str]] = {}    # task -> set of dependents (downstream)
        self.states: Dict[str, TaskState] = {}
        self.results: Dict[str, Any] = {}
        self.errors: Dict[str, Any] = {}
        self.metadata: Dict[str, Dict[str, Any]] = {}

        if tasks:
            for task_id, deps in tasks.items():
                self.add_task(task_id, dependencies=deps)

    def add_task(
        self,
        task_id: str,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a task with its upstream dependencies.

        Raises CycleError if the dependency creates a cycle.
        """
        if task_id not in self.dependencies:
            self.dependencies[task_id] = set()
            self.dependents[task_id] = set()
            self.states[task_id] = TaskState.PENDING
            self.metadata[task_id] = metadata or {}
        elif metadata:
            self.metadata[task_id].update(metadata)

        if dependencies:
            for dep in dependencies:
                if dep not in self.dependencies:
                    self.dependencies[dep] = set()
                    self.dependents[dep] = set()
                    self.states[dep] = TaskState.PENDING
                    self.metadata[dep] = {}

                self.dependencies[task_id].add(dep)
                self.dependents[dep].add(task_id)

        # Ensure no cycles were introduced
        self._validate_acyclic()

    def _validate_acyclic(self) -> None:
        """Validate DAG acyclicity using DFS."""
        visited: Dict[str, int] = {}  # 0: visiting, 1: visited

        def visit(node: str, path: List[str]) -> None:
            visited[node] = 0
            for neighbor in self.dependencies.get(node, ()):
                if neighbor in visited:
                    if visited[neighbor] == 0:
                        cycle_path = " -> ".join(path + [neighbor])
                        raise CycleError(f"Cycle detected in task dependencies: {cycle_path}")
                else:
                    visit(neighbor, path + [neighbor])
            visited[node] = 1

        for task in self.dependencies:
            if task not in visited:
                visit(task, [task])

    def get_ready_tasks(self, mark_ready: bool = False) -> List[str]:
        """Return task IDs that are ready to run (PENDING or READY with all dependencies COMPLETED)."""
        ready = []
        for task_id, state in self.states.items():
            if state in (TaskState.PENDING, TaskState.READY):
                deps = self.dependencies[task_id]
                if all(self.states.get(d) == TaskState.COMPLETED for d in deps):
                    ready.append(task_id)
                    if mark_ready:
                        self.states[task_id] = TaskState.READY
        return sorted(ready)

    def mark_running(self, task_id: str) -> None:
        """Mark a task as currently RUNNING."""
        if task_id not in self.states:
            raise KeyError(f"Task '{task_id}' not found.")
        if self.states[task_id] not in (TaskState.PENDING, TaskState.READY):
            raise ValueError(f"Cannot run task '{task_id}' in state {self.states[task_id]}.")
        self.states[task_id] = TaskState.RUNNING

    def mark_completed(self, task_id: str, result: Any = None) -> None:
        """Mark a task as COMPLETED and record its result."""
        if task_id not in self.states:
            raise KeyError(f"Task '{task_id}' not found.")
        self.states[task_id] = TaskState.COMPLETED
        self.results[task_id] = result

    def mark_failed(self, task_id: str, error: Any = None, cascade_skip: bool = True) -> List[str]:
        """Mark a task as FAILED.

        If cascade_skip is True, all downstream tasks depending on this task
        are marked as SKIPPED. Returns list of newly skipped tasks.
        """
        if task_id not in self.states:
            raise KeyError(f"Task '{task_id}' not found.")
        self.states[task_id] = TaskState.FAILED
        self.errors[task_id] = error

        skipped: List[str] = []
        if cascade_skip:
            queue = list(self.dependents.get(task_id, ()))
            visited: Set[str] = set()
            while queue:
                current = queue.pop(0)
                if current not in visited:
                    visited.add(current)
                    if self.states[current] in (TaskState.PENDING, TaskState.READY):
                        self.states[current] = TaskState.SKIPPED
                        skipped.append(current)
                    queue.extend(self.dependents.get(current, ()))
        return sorted(skipped)

    def is_finished(self) -> bool:
        """Return True if all tasks are in a terminal state (COMPLETED, FAILED, or SKIPPED)."""
        terminal_states = {TaskState.COMPLETED, TaskState.FAILED, TaskState.SKIPPED}
        return all(state in terminal_states for state in self.states.values())

    def has_failures(self) -> bool:
        """Return True if any task has FAILED."""
        return any(state == TaskState.FAILED for state in self.states.values())

    def get_execution_order(self) -> List[str]:
        """Return a valid topological sort order for executing all tasks."""
        in_degrees = {task: len(deps) for task, deps in self.dependencies.items()}
        zero_in_degree = sorted([task for task, deg in in_degrees.items() if deg == 0])
        order: List[str] = []

        while zero_in_degree:
            node = zero_in_degree.pop(0)
            order.append(node)
            for downstream in sorted(self.dependents.get(node, ())):
                in_degrees[downstream] -= 1
                if in_degrees[downstream] == 0:
                    zero_in_degree.append(downstream)
                    zero_in_degree.sort()

        if len(order) != len(self.dependencies):
            raise CycleError("Graph contains a cycle; cannot determine execution order.")
        return order

    def reset(self) -> None:
        """Reset all task states to PENDING and clear results/errors."""
        for task_id in self.states:
            self.states[task_id] = TaskState.PENDING
        self.results.clear()
        self.errors.clear()

    def execute_sequentially(
        self,
        task_handlers: Union[Dict[str, Callable[..., Any]], Callable[..., Any]],
        pass_results: bool = True,
        stop_on_failure: bool = False,
    ) -> Dict[str, Any]:
        """Execute all tasks sequentially.

        `task_handlers` can be a mapping from task_id to a callable handler,
        or a single callable taking (task_id, dependency_results).
        """
        while not self.is_finished():
            ready_tasks = self.get_ready_tasks()
            if not ready_tasks:
                break

            for task_id in ready_tasks:
                self.mark_running(task_id)

                if callable(task_handlers) and not isinstance(task_handlers, dict):
                    handler: Optional[Callable[..., Any]] = task_handlers
                    is_generic = True
                else:
                    handler = task_handlers.get(task_id)
                    is_generic = False

                if handler is None:
                    self.mark_failed(task_id, error="No handler provided for task")
                    if stop_on_failure:
                        return self.results
                    continue

                dep_results = {dep: self.results.get(dep) for dep in sorted(self.dependencies[task_id])}

                try:
                    if is_generic:
                        res = handler(task_id, dep_results) if pass_results else handler(task_id)
                    else:
                        sig = inspect.signature(handler)
                        param_count = len(sig.parameters)
                        if param_count == 0 or not pass_results:
                            res = handler()
                        else:
                            res = handler(dep_results)
                    self.mark_completed(task_id, result=res)
                except Exception as exc:
                    self.mark_failed(task_id, error=str(exc))
                    if stop_on_failure:
                        return self.results

        return self.results


def run_sequential_plan(
    plan: Dict[str, List[str]],
    handlers: Union[Dict[str, Callable[..., Any]], Callable[..., Any]],
    pass_results: bool = True,
    stop_on_failure: bool = False,
) -> Dict[str, Any]:
    """Execute a sequential plan defined by a dependency dictionary.

    Args:
        plan: Mapping of task_id -> list of prerequisite task_ids.
        handlers: Task callable(s).
        pass_results: If True, passes completed dependency results into each task.
        stop_on_failure: If True, halts immediately when a task fails.

    Returns:
        Mapping of task_id -> execution result.
    """
    tracker = TaskDependencyTracker(plan)
    return tracker.execute_sequentially(handlers, pass_results=pass_results, stop_on_failure=stop_on_failure)