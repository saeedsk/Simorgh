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
- `max_depth` -- read by `SessionRunner` when `delegation` is on: a
  helper task may not be delegated deeper than this.
- `max_children_concurrent`, `needs_human_timeout_s` -- declared so the
  config surface matches the original spec, but **no code path reads
  them**: nothing bounds concurrent helpers, and nothing times out a
  `needs_human` wait here. Changing them changes nothing.
- There is no `lease_seconds` here. The lease is Planning's: `[planning]
  lease_seconds` goes out on every `task.available`, and the Worker reads
  it from that payload. This section's copy was never read and was
  removed on 2026-09-19; writing it now is reported by
  `kernel/configcheck.py` as a section that changed nothing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    workers: int = 1
    # Whether Verification reviews a benchmark case's answer. On by default.
    # A benchmark wave turns it off to measure the reviewer: on 2026-09-14
    # it rejected 111 correct and 111 wrong answers alike, and on patch
    # tasks each rejection spends a revision in the same context.
    review_benchmark: bool = True
    # Re-grounding (orchestration/progress.py): every N steps a task session
    # writes a progress note and its transcript is replaced by the note and
    # the last `keep_recent_steps` steps. 0 is off, the default until its
    # benchmark arm wins (docs/plans/long-run-context-design.md).
    reground_every_steps: int = 0
    keep_recent_steps: int = 2
    # A patch revision after a rejected answer starts from the progress note
    # and the last `keep_recent_steps` steps instead of the whole transcript.
    clean_revisions: bool = False
    # Helper tasks: the `delegate` tool, offered to patch and research sessions
    # below `max_depth`. Off until its benchmark arm wins.
    delegation: bool = False
    delegate_max_steps: int = 12
    # From this attempt on, a task's THINKs ask Cognition for the strong tier
    # ([cognition] routes.strong). 0 is off.
    escalate_from_attempt: int = 0
    # Escalate to the strong tier when Sim's own record at this kind of
    # work is below this, and rests on at least `escalate_min_samples`
    # outcomes (stage 6 item 2: a consumer of `self.estimate`). A flat
    # prior is 0.5 with nothing recorded, so the sample floor is what
    # stops a new task type escalating on no evidence. 0 turns it off.
    escalate_below_posterior: float = 0.45
    escalate_min_samples: int = 8
    # Read-only tools one reply asks for together run together, up to this
    # many per step (docs/plans/long-run-context-design.md, change H). 1 is off.
    parallel_read_tools: int = 1
    # Agent Skills (docs/plans/agent-skills-design.md). Off until its benchmark
    # arm: the catalog is paid on every THINK, so an unused menu is a tax on
    # every task. `skills_roots` is searched in order and the first folder with
    # a name wins; "~" is expanded.
    # On since 2026-09-16, once the catalog stopped being charged where it
    # cannot be used (`skills_channels`): a voice turn carries none of it,
    # and a typed one pays 157 tokens for the two bundled skills -- about
    # $0.008 a day at the creator's 332 calls. Until the scoping existed
    # this was off precisely because every THINK paid for it (design
    # section 5.2).
    skills_enabled: bool = True
    skills_catalog_max_chars: int = 3000
    skills_roots: tuple[str, ...] = ("skills", "~/.simorgh/skills")
    # Which channels carry the skill catalog at all. The catalog rides in
    # `task_rules` on EVERY think call, and a spoken turn will never use
    # "create new skills" or "build an MCP server" -- so voice pays
    # nothing rather than a little. The creator, 2026-09-16: "our system
    # should have the concept of being frugal where ever it is possible".
    # "" is the typed/CLI channel. Empty tuple: no catalog anywhere.
    skills_channels: tuple[str, ...] = ("", "cli", "http")
    heartbeat_s: int = 30
    # An attempt's budget beside its steps (stage 4 item 6); 0 is no limit.
    # Running out ends the attempt "budget exhausted: <which>", which --
    # unlike the step cap -- is not retried with a fresh budget.
    attempt_max_tokens: int = 0
    attempt_max_usd: float = 0.0
    attempt_max_wall_s: float = 0.0
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
