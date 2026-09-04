"""In-memory task scheduler for one-off and recurring jobs."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import heapq
import itertools
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass(order=True)
class ScheduledTask:
    run_at: datetime
    priority: int
    task_id: int
    func: Callable = field(compare=False)
    args: Tuple[Any, ...] = field(compare=False, default_factory=tuple)
    kwargs: Dict[str, Any] = field(compare=False, default_factory=dict)
    interval: Optional[timedelta] = field(compare=False, default=None)
    max_runs: Optional[int] = field(compare=False, default=None)
    run_count: int = field(compare=False, default=0)
    cancelled: bool = field(compare=False, default=False)


class Scheduler:
    """A lightweight, deterministic in-memory task scheduler."""

    def __init__(self) -> None:
        self._counter = itertools.count()
        self._heap: List[ScheduledTask] = []
        self._tasks: Dict[int, ScheduledTask] = {}

    def schedule(
        self,
        run_at: datetime,
        func: Callable,
        *args: Any,
        priority: int = 0,
        interval: Optional[timedelta] = None,
        max_runs: Optional[int] = None,
        **kwargs: Any,
    ) -> int:
        """Schedule a function to run at a specific datetime."""
        if interval is not None and interval <= timedelta(0):
            raise ValueError("interval must be a positive timedelta")
        if max_runs is not None and max_runs <= 0:
            raise ValueError("max_runs must be greater than 0")

        task_id = next(self._counter)
        task = ScheduledTask(
            run_at=run_at,
            priority=priority,
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            interval=interval,
            max_runs=max_runs,
        )
        self._tasks[task_id] = task
        heapq.heappush(self._heap, task)
        return task_id

    def schedule_after(
        self,
        delay: timedelta,
        func: Callable,
        *args: Any,
        base_time: Optional[datetime] = None,
        priority: int = 0,
        interval: Optional[timedelta] = None,
        max_runs: Optional[int] = None,
        **kwargs: Any,
    ) -> int:
        """Schedule a function to run after a delay from base_time (or now)."""
        now = base_time or datetime.now()
        return self.schedule(
            now + delay,
            func,
            *args,
            priority=priority,
            interval=interval,
            max_runs=max_runs,
            **kwargs,
        )

    def schedule_interval(
        self,
        interval: timedelta,
        func: Callable,
        *args: Any,
        start_time: Optional[datetime] = None,
        priority: int = 0,
        max_runs: Optional[int] = None,
        **kwargs: Any,
    ) -> int:
        """Schedule a function to run periodically at fixed intervals."""
        first_run = start_time or datetime.now()
        return self.schedule(
            first_run,
            func,
            *args,
            priority=priority,
            interval=interval,
            max_runs=max_runs,
            **kwargs,
        )

    def cancel(self, task_id: int) -> bool:
        """Cancel a scheduled task. Returns True if task existed and was cancelled."""
        task = self._tasks.get(task_id)
        if task and not task.cancelled:
            task.cancelled = True
            del self._tasks[task_id]
            return True
        return False

    def is_scheduled(self, task_id: int) -> bool:
        """Check if a task is active and scheduled."""
        task = self._tasks.get(task_id)
        return bool(task and not task.cancelled)

    def get_task(self, task_id: int) -> Optional[ScheduledTask]:
        """Get the scheduled task by ID, or None if not found/cancelled."""
        task = self._tasks.get(task_id)
        if task and not task.cancelled:
            return task
        return None

    def peek_next_run_time(self) -> Optional[datetime]:
        """Return the next scheduled run time without executing tasks."""
        self._purge_cancelled()
        return self._heap[0].run_at if self._heap else None

    def _purge_cancelled(self) -> None:
        """Remove cancelled tasks from top of heap."""
        while self._heap and self._heap[0].cancelled:
            heapq.heappop(self._heap)

    def run_due(
        self, current_time: Optional[datetime] = None
    ) -> List[Tuple[int, Any]]:
        """Run all tasks due by current_time and return results as (task_id, result) tuples."""
        if current_time is None:
            if self._heap and self._heap[0].run_at.tzinfo is not None:
                now = datetime.now(self._heap[0].run_at.tzinfo)
            else:
                now = datetime.now()
        else:
            now = current_time

        results: List[Tuple[int, Any]] = []

        while self._heap:
            self._purge_cancelled()
            if not self._heap:
                break
            if self._heap[0].run_at > now:
                break

            task = heapq.heappop(self._heap)
            if task.cancelled:
                continue

            result = task.func(*task.args, **task.kwargs)
            task.run_count += 1
            results.append((task.task_id, result))

            if not task.cancelled and task.interval is not None:
                if task.max_runs is None or task.run_count < task.max_runs:
                    task.run_at = task.run_at + task.interval
                    heapq.heappush(self._heap, task)
                    continue

            self._tasks.pop(task.task_id, None)

        return results

    def run_all(self, max_runs: Optional[int] = None) -> List[Tuple[int, Any]]:
        """Run all tasks currently scheduled, optionally bounded by max_runs."""
        results: List[Tuple[int, Any]] = []
        runs = 0
        while self._heap:
            if max_runs is not None and runs >= max_runs:
                break
            self._purge_cancelled()
            if not self._heap:
                break
            due_results = self.run_due(self._heap[0].run_at)
            results.extend(due_results)
            runs += len(due_results)
        return results

    def clear(self) -> None:
        """Cancel and remove all scheduled tasks."""
        for task in self._tasks.values():
            task.cancelled = True
        self._tasks.clear()
        self._heap.clear()

    def __len__(self) -> int:
        return len(self._tasks)

    def __contains__(self, task_id: int) -> bool:
        return self.is_scheduled(task_id)