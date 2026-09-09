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
- `lease_seconds`, `heartbeat_s`, `max_depth`, `max_children_concurrent`,
  `needs_human_timeout_s` -- declared so the config surface matches the
  full `16-orchestration.md` spec, but **no code path reads them yet**,
  in *either* single or multi-process mode. This isn't a single-mode
  limitation: lease-heartbeat renewal, wall-clock budgets, and
  delegation (fresh/fork sub-sessions with `depth`/concurrent children)
  are simply not built yet (see `orchestration/README.md`'s "What this
  build deliberately does NOT implement"). Changing these in
  `simorgh.toml` will not (yet) change any observable behaviour --
  wire them here, and note it in this docstring, the day a `Worker`
  actually renews a lease or spawns a child session.
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
    think_timeout_s: float = 120.0
    needs_human_timeout_s: float = 600.0
    metrics_interval_s: float = 3.0  # 0 disables the periodic `system.metrics` publish

    @classmethod
    def from_mapping(cls, data: dict) -> "Config":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
