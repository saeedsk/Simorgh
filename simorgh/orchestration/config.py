"""`simorgh.toml [orchestration]` (16 section 3.5).

`Service.start()` adopts this section via `from_mapping` the same way
`persona.service.Service` does (observer, 2026-09-08: the config
existed, `from_mapping` existed, and nothing ever called it, so editing
`[orchestration]` changed nothing in `single` mode -- the mode `sim.sh`
actually runs).

What each field really does once adopted:

- `workers` -- genuinely applies in `single` mode. One *process* is not
  one *Worker*: `Service.start()` loops `range(config.workers)` and
  starts that many `Worker` instances sharing the `workers` consumer
  group inside this one process, so raising it gives real additional
  in-process concurrency (competing consumers of `task.available`).
  It is not meaningless just because there's a single process.
- `think_timeout_s`, `metrics_interval_s` -- read by `Service`/`Worker`
  directly (see `service.py`).
- `heartbeat_s` -- read by `Worker._heartbeat_loop` (2026-09-08 fix):
  how often a claimed task's lease is renewed with `task.
  lease_heartbeat` while a single step is still in flight, so a step
  slower than `[planning] lease_seconds` (a full `run_tests`, a stuck
  `web_fetch`, a cold-start `cognition.think`) can no longer let
  `Scheduler.scan_leases` treat the task as abandoned and hand it to a
  second worker mid-step. The Worker never waits longer than a third of
  the task's own `lease_seconds` regardless of this value, so a short
  lease (a test, a tight deployment) is never outrun by a `heartbeat_s`
  sized for the 600s default.
- `lease_seconds`, `max_depth`, `max_children_concurrent`,
  `needs_human_timeout_s` -- declared so the config surface matches the
  full `16-orchestration.md` spec, but **no code path reads them yet**,
  in *either* single or multi-process mode (`[planning]`'s own
  `lease_seconds` is the value that actually sets lease length; this
  section's copy is unread). Wall-clock budgets and delegation
  (fresh/fork sub-sessions with `depth`/concurrent children) are simply
  not built yet (see `orchestration/README.md`'s "What this build
  deliberately does NOT implement"). Changing these in `simorgh.toml`
  will not (yet) change any observable behaviour -- wire them here, and
  note it in this docstring, the day a `Worker` actually spawns a child
  session.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    workers: int = 1
    lease_seconds: int = 600
    heartbeat_s: int = 30
    max_depth: int = 3
    max_children_concurrent: int = 4
    # Above Cognition's own `Budget.max_seconds` (180s), with room to
    # spare. It used to sit BELOW it: Cognition allowed each provider
    # 180 seconds while the caller here waited 120, so a merely slow
    # primary killed the task as "no real provider" while that provider
    # was still answering, and the failover chain behind it could never
    # be reached (observer, 2026-09-10 -- a task died at 121s with one
    # `think.completed` on record and no trace of a second call).
    # Cognition bounds the whole chain now; this waits for it.
    think_timeout_s: float = 200.0
    needs_human_timeout_s: float = 600.0
    # A patch or skill task works in its own git worktree and lands on
    # main through `worktree_land` (execution/worktree.py) instead of
    # editing the live checkout. Needs Execution's worktree tools; a
    # session that cannot open one says so and edits the live tree.
    worktrees: bool = True
    metrics_interval_s: float = 3.0  # 0 disables the periodic `system.metrics` publish

    @classmethod
    def from_mapping(cls, data: dict) -> "Config":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
