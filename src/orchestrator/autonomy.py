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
- `max_consecutive_failures` (a circuit breaker, see the constant's own
  docstring below): if the last `max_consecutive_failures` actions in a
  row all failed, the loop disables itself and prints a loud notice
  instead of quietly grinding through the rest of the daily cap on a
  systematically broken pipeline. Requires `autonomous on` (which resets
  the streak) to resume -- a human checkpoint, not a silent retry.

An optional `diagnostic_probe` callback lets the loop use genuinely idle
time (no pending external work found by `perform_action`) to run a
self-check instead of just waiting -- e.g. verifying the memory store is
healthy, or reviewing recent action outcomes. It shares the same
idle/cooldown pacing as real actions, but is logged under its own kind
(`PROBE_ACTION_KIND`) and deliberately excluded from `max_actions_per_day`
and the failure-streak breaker, since observing is not acting. Deciding
*what* to probe stays external (main.py) when a `diagnostic_probe` is
injected, the same separation of concerns already used for
`perform_action`. When no `diagnostic_probe` is injected at all, this
file falls back to a small, fixed, intrinsic set of read-only self-checks
(`_run_intrinsic_hypothesis_probe`) so idle time is never pure waiting
even in the minimal wiring case -- every one of those checks is local,
read-only, and stdlib-only (no network, no subprocess, no file writes
beyond the usual MemoryStore record), the same boundary every other
action in this file already respects.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from src.memory.long_term import MemoryStore
from src.orchestrator.console_style import style


@dataclass(frozen=True)
class ActionDigest:
    total: int
    succeeded: int
    failed: int
    unknown: int
    window_seconds: float

ACTION_KIND = "autonomous_action"
PROBE_ACTION_KIND = "autonomous_probe"

# Retuned three times now, all from direct creator feedback, all
# downward. First pass (300s/600s -> 60s/150s): "not acting on its own,
# sitting idle all the time" -- idle time resets on every keystroke, so
# the original defaults meant an active chat session almost never left
# a silent gap long enough to fire at all. Second pass (60s/150s ->
# 20s/30s, "hyperscale... starting after 20 seconds"). Third pass, this
# one ("increase the rate of sim thinking frequency... 10X speed up" --
# with an explicit, reasonable worry attached: "would it run out my
# claude usage? like to be cautious there"):
# - action_cooldown: 30s -> 3s, the literal 10x asked for. This is the
#   right knob for "how often does a new self-improvement action fire
#   once idle" -- it's what actually paces repeated actions.
# - poll_interval: 5s -> 1s, so the loop notices the new tighter
#   boundaries promptly.
# - idle_threshold: 20s -> 10s, only 2x rather than the full 10x on
#   purpose. Dropping this to ~2s (a literal 10x) would mean an
#   ordinary pause between reading a reply and typing the next message
#   -- completely normal during active back-and-forth -- reads as
#   "idle" and starts competing for attention constantly; that directly
#   works against every earlier fix aimed at making this feel like a
#   pleasant conversational partner, not a nervous interruption engine.
#   10s still comfortably beats the old 20s.
# - max_actions_per_day: 500 -> 2000, comfortably above Gemini's own
#   1500-call/24h BudgetGuard cap so THIS cap never becomes the binding
#   constraint before the real spend ceilings do (same reasoning as the
#   500 bump before it -- see below).
# On the subscription-safety worry specifically: this retune does NOT
# touch DEFAULT_CLAUDE_CODE_MAX_CALLS/CLAUDE_CODE_WINDOW_SECONDS (still
# 30 calls / 5h, main.py) -- that cap, not this file's timing, is what
# actually protects the creator's flat-rate Claude Code subscription.
# A faster tick rate just means that 30-call ceiling gets reached
# sooner during a genuinely idle stretch, after which CognitionRouter's
# existing fallback (Gemini, itself capped, then the free deterministic
# floor) carries the rest -- never more real Claude Code CLI usage than
# the unchanged cap already allowed.
# Every other gate (BudgetGuard, the audit gate, the isolated test
# suite, the failure-streak circuit breaker below) is completely
# unchanged -- this only changes how OFTEN those gates get a chance to
# run, never what they allow through.
DEFAULT_IDLE_THRESHOLD_SECONDS = 10.0
DEFAULT_ACTION_COOLDOWN_SECONDS = 3.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_ACTIONS_PER_DAY = 2000
# A circuit breaker, not a metric to tune finely: real-world guidance on
# self-improving agents converges on the same shape regardless of the
# exact number -- a behavioral log, a rollback path (already covered by
# revert_last_commit/revert_commits_since), and a human checkpoint
# trigger that pauses the loop and routes to review once failures start
# looking systematic rather than incidental. Every existing gate below
# already bounds a single bad action (the audit gate, the isolated test
# suite, the relaunch self-check); this bounds a *pattern* across many
# actions that individually passed rate/cost limits but kept failing --
# the daily cap alone would otherwise let a systematically broken
# pipeline burn its entire budget on failures, then quietly try again
# tomorrow, for as long as nobody happens to check `autonomous status`.
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5


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

    # A small, fixed set of read-only self-checks used as a fallback
    # when no `diagnostic_probe` is injected -- see
    # `_run_intrinsic_hypothesis_probe`. Deliberately short: this is a
    # "something rather than nothing" floor, not a substitute for the
    # richer, project-aware checks main.py's own `diagnostic_probe` can
    # run.
    _INTRINSIC_HYPOTHESES = (
        "memory_store_queryable",
        "recent_failure_rate_bounded",
    )

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
        last_action_succeeded: Callable[[], bool | None] | None = None,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        diagnostic_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._perform_action = perform_action
        self.enabled = enabled
        self.idle_threshold_seconds = idle_threshold_seconds
        self.action_cooldown_seconds = action_cooldown_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_actions_per_day = max_actions_per_day
        self._last_action_succeeded = last_action_succeeded
        self.max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self._last_action_at = 0.0
        self._diagnostic_probe = diagnostic_probe
        self._last_probe_at = 0.0
        self._hypothesis_index = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def reset_failure_streak(self) -> None:
        """Called when the creator explicitly re-enables the loop after
        a circuit-breaker pause -- a fresh start, not an immediate
        re-trip on the very next failure.
        """
        self._consecutive_failures = 0

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

    def digest(self, window_seconds: float = 86400.0) -> "ActionDigest":
        """A lightweight rollup of autonomous activity over the last
        `window_seconds` -- how many actions, how many succeeded/failed
        (per the same `succeeded` signal the circuit breaker uses), and
        how many carried no success/failure signal at all (a pure
        discovery tick, or a caller that never wired
        `last_action_succeeded`). Exists because reviewing what the
        autonomous loop actually did previously required actively
        reading `log`/`tasks` -- there was no lighter-weight summary
        surface at all.
        """
        cutoff = time.time() - window_seconds
        records = [r for r in self._store.query(kind=ACTION_KIND) if r.created_at >= cutoff]
        succeeded = sum(1 for r in records if r.metadata.get("succeeded") is True)
        failed = sum(1 for r in records if r.metadata.get("succeeded") is False)
        return ActionDigest(
            total=len(records),
            succeeded=succeeded,
            failed=failed,
            unknown=len(records) - succeeded - failed,
            window_seconds=window_seconds,
        )

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

    def _run_intrinsic_hypothesis_probe(self) -> None:
        """Fallback used by `_maybe_run_diagnostic_probe` when no
        external `diagnostic_probe` was injected: cycle through a
        small, fixed set of read-only self-checks ("hypotheses" about
        this process's own health) one at a time, log the outcome, and
        move on. Every check here is local and read-only -- no network,
        no subprocess, no file writes beyond the usual MemoryStore
        record -- the same boundary every other action in this file
        already respects. This never touches `max_actions_per_day` or
        the failure-streak breaker, same as the injected-probe path.
        """
        hypothesis = self._INTRINSIC_HYPOTHESES[self._hypothesis_index % len(self._INTRINSIC_HYPOTHESES)]
        self._hypothesis_index += 1
        passed = True
        detail = ""
        try:
            if hypothesis == "memory_store_queryable":
                self._store.query(kind=ACTION_KIND)
            elif hypothesis == "recent_failure_rate_bounded":
                recent = self.digest(window_seconds=3600.0)
                if recent.total > 0 and recent.failed / recent.total > 0.5:
                    passed = False
                    detail = f"{recent.failed}/{recent.total} recent actions failed"
        except Exception as exc:  # noqa: BLE001 -- a broken self-check
            # must never take the background loop down; record it and
            # move on, same as every other guard in this file.
            passed = False
            detail = repr(exc)
        self._store.remember(
            PROBE_ACTION_KIND,
            f"intrinsic diagnostic probe: {hypothesis}",
            hypothesis=hypothesis,
            passed=passed,
            detail=detail,
        )
        status = "ok" if passed else f"flagged ({detail})"
        print(style(f"🔎 [autonomous] intrinsic probe '{hypothesis}': {status}", "cyan", "bold"))

    def _maybe_run_diagnostic_probe(self) -> None:
        """Fallback for a genuinely idle tick where `perform_action`
        found no external work: gives an injected `diagnostic_probe`
        callback a chance to run one hypothesis-driven self-check (e.g.
        verifying memory-store integrity or reviewing recent action
        health) so idle time isn't pure waiting; when no
        `diagnostic_probe` was injected at all, falls back to
        `_run_intrinsic_hypothesis_probe` instead, so this floor exists
        even in the minimal wiring case. Paced by the same
        `action_cooldown_seconds` as real actions so it can't spam every
        poll tick; logged under its own kind (`PROBE_ACTION_KIND`) so it
        is never confused with -- or double-counted against -- the
        daily action cap or the failure-streak circuit breaker, both of
        which are about real actions only. What a probe actually checks
        is entirely the injected callback's decision when one exists,
        same as `perform_action` -- this file still never decides *what*
        external work to do, only *whether/when* it's allowed to, and
        (in the no-callback case) which of its own small fixed
        self-checks to run next.
        """
        if time.time() - self._last_probe_at < self.action_cooldown_seconds:
            return
        self._last_probe_at = time.time()
        if self._diagnostic_probe is None:
            self._run_intrinsic_hypothesis_probe()
            return
        try:
            probe_ran = self._diagnostic_probe()
        except Exception as exc:  # noqa: BLE001 -- same reasoning as
            # the perform_action guard below: a broken probe must never
            # take the background loop down.
            print(style(f"🤖 [autonomous] diagnostic probe raised {exc!r} -- will try again later", "red", "bold"))
            return
        if probe_ran:
            self._store.remember(PROBE_ACTION_KIND, "autonomous diagnostic probe run")
            print(style("🔎 [autonomous] idle diagnostic probe (no pending external work)", "cyan", "bold"))

    def tick(self) -> bool:
        """One synchronous check-and-maybe-act cycle -- what the
        background loop calls repeatedly, but also directly callable
        (and unit-testable) without any real waiting or threading.
        Returns True only if `perform_action` actually ran and reported
        real work done. When it didn't (genuinely nothing pending), an
        injected `diagnostic_probe` (or, absent one, the intrinsic
        hypothesis-cycle fallback) gets one paced chance to run instead
        -- see `_maybe_run_diagnostic_probe` -- but that never changes
        this method's return value or counts as an "action".
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
            succeeded = None
            if self._last_action_succeeded is not None:
                try:
                    succeeded = self._last_action_succeeded()
                except Exception:  # noqa: BLE001 -- a broken outcome
                    # signal must never itself take the loop down; treat
                    # it as "no signal" and keep going.
                    succeeded = None
            self._store.remember(ACTION_KIND, "autonomous action taken", succeeded=succeeded)
            if succeeded is False:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.max_consecutive_failures:
                    self.enabled = False
                    print(
                        style(
                            f"🚨 [autonomous] paused itself after {self._consecutive_failures} "
                            "consecutive failed actions -- this looks systematic, not "
                            "incidental. Review recent activity ('log'), then 'autonomous on' "
                            "to resume once the underlying issue is understood.",
                            "red",
                            "bold",
                        )
                    )
            elif succeeded is True:
                self._consecutive_failures = 0
        else:
            self._maybe_run_diagnostic_probe()
        return did_something

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_interval_seconds):
            self.tick()