"""Idle-triggered autonomous self-improvement -- the one piece of this
project that removes the "a human types the trigger command" boundary
every other capability in Simorgh has kept up to now, explicitly
authorized by the creator (docs/SOUL.md, "Autonomous idle loop") after
being told plainly what that trade-off means: no natural rate limit tied
to how often a human acts, and an LLM-cost profile that runs whenever
nothing else is happening rather than only when asked.

Runs as a daemon thread alongside the interactive CLI loop (src/main.py),
watching how long it's been since the last user input via `ActivityClock`.
Once idle beyond a threshold, `AutonomyController` calls an injected
`perform_action` callback -- it does not itself decide *what* to work on;
that stays main.py's job (discover new work when the queue is empty,
otherwise pick up the next pending/in-progress Task), routed through the
exact same audited propose/patch/verify/commit pipelines a human-typed
command uses. Nothing about *what* it's allowed to do changes; only *what
triggers it* does.

Bounded on top of (never instead of) every existing guard:
- `idle_threshold_seconds`: how long the CLI must sit unused before this
  considers acting at all.
- `action_cooldown_seconds`: a minimum gap between one autonomous action
  and the next, independent of idle time -- no rapid-fire loop.
- `max_actions_per_day`: a hard, durable cap (kind=ACTION_KIND records
  in the same MemoryStore), on top of the BudgetGuard LLM-spend caps
  every real provider is already wrapped in.
- Every action is clearly marked (an unmistakable printed prefix, and
  durably logged) so it is never mistaken for something a human asked
  for -- Directive 8 (Transparency), made concrete for the one capability
  class where confusing the two would matter most.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from src.memory.long_term import MemoryStore
from src.orchestrator.console_style import style

ACTION_KIND = "autonomous_action"

DEFAULT_IDLE_THRESHOLD_SECONDS = 300.0
DEFAULT_ACTION_COOLDOWN_SECONDS = 600.0
DEFAULT_POLL_INTERVAL_SECONDS = 30.0
DEFAULT_MAX_ACTIONS_PER_DAY = 20


class ActivityClock:
    """Tracks when the interactive loop last did something. The main
    loop calls `touch()` right after each `input()` returns (a user
    submitted something -- the definition of "not idle" here); the
    autonomous loop reads `idle_seconds()` to decide whether to act.
    Thread-safe: a plain float behind a lock is all this needs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_activity = time.time()

    def touch(self) -> None:
        with self._lock:
            self._last_activity = time.time()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.time() - self._last_activity


class AutonomyController:
    """Owns the enable/disable flag, the idle/cooldown timing, and the
    durable daily action cap. Does not itself decide what to work on or
    execute anything -- `perform_action` (injected) does that and
    returns True only if it genuinely did something, so a no-op check
    (queue empty, discovery found nothing) never consumes the daily
    budget or starts the cooldown.
    """

    def __init__(
        self,
        store: MemoryStore,
        clock: ActivityClock,
        perform_action: Callable[[], bool],
        enabled: bool = True,
        idle_threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS,
        action_cooldown_seconds: float = DEFAULT_ACTION_COOLDOWN_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_actions_per_day: int = DEFAULT_MAX_ACTIONS_PER_DAY,
    ) -> None:
        self._store = store
        self._clock = clock
        self._perform_action = perform_action
        self.enabled = enabled
        self.idle_threshold_seconds = idle_threshold_seconds
        self.action_cooldown_seconds = action_cooldown_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_actions_per_day = max_actions_per_day
        self._last_action_at = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="simorgh-autonomy")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def actions_today(self) -> int:
        cutoff = time.time() - 86400.0
        return sum(1 for r in self._store.query(kind=ACTION_KIND) if r.created_at >= cutoff)

    def idle_seconds(self) -> float:
        return self._clock.idle_seconds()

    def ready_to_act(self) -> bool:
        """Whether every gate (enabled, idle long enough, past cooldown,
        under the daily cap) currently allows an action -- exposed
        separately from `tick()` so a status command can report *why*
        it isn't acting, not just that it isn't.
        """
        if not self.enabled:
            return False
        if self._clock.idle_seconds() < self.idle_threshold_seconds:
            return False
        if time.time() - self._last_action_at < self.action_cooldown_seconds:
            return False
        if self.actions_today() >= self.max_actions_per_day:
            return False
        return True

    def tick(self) -> bool:
        """One synchronous check-and-maybe-act cycle -- what the
        background loop calls repeatedly, but also directly callable
        (and unit-testable) without any real waiting or threading.
        Returns True only if `perform_action` actually ran and reported
        real work done.
        """
        if not self.ready_to_act():
            return False
        try:
            did_something = self._perform_action()
        except Exception as exc:  # noqa: BLE001 -- the background loop
            # must never die from one bad action; the next tick tries
            # again after the usual cooldown, not immediately in a
            # tight failure loop.
            print(style(f"🤖 [autonomous] action raised {exc!r} -- will try again later", "red", "bold"))
            return False
        if did_something:
            self._last_action_at = time.time()
            self._store.remember(ACTION_KIND, "autonomous action taken")
        return did_something

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_interval_seconds):
            self.tick()
