# `simorgh.kernel`

The composition root: the only package allowed to import another
subsystem's `Service` (`02` §4 rule 4). Boots config → secrets → Ledger →
Bus(policy) → every layer in order, health-gated; owns the state
machine, the Scheduler, and the status server; enforces the structural
safety proof (`--self-check`) before any real work is allowed to run.
Spec: [`docs/blueprint/subsystems/03-kernel.md`](../../docs/blueprint/subsystems/03-kernel.md).

| Module | What |
|---|---|
| `service.py` | `Kernel` — the composition root itself: `boot()`, `shutdown()`, `wait_for_stop()`, `health()`, `status_snapshot()`, pause/resume/stop handlers, auto-pause on a `SAFETY_CRITICAL` subsystem going `down`. |
| `cli.py` | `python -m simorgh …`: `run` (default), `status`, `trace <id>`, `migrate-v1`, `--self-check`, `--config`. |
| `selfcheck.py` | The structural safety proof: a stub Guardian/Execution speak the real `contracts.security` token contract over a real Bus/Ledger, proving a valid approval executes, a forged token is rejected before the tool runs, a paused system denies new proposals, and a non-Guardian source cannot subscribe to `action.proposed`. |
| `config.py` | `[runtime]` load/merge, `SIMORGH_<SECTION>_<KEY>` env overrides, `LoadedConfig.section(name)` per-subsystem slices. |
| `secrets.py` | `EnvSecretStore` / `FileSecretStore` (refuses group/world-readable files) / `ChainedSecretStore` / `ScopedSecretStore` — a subsystem sees only the secret names its own config section declared. |
| `context.py` | `ContextFactory.build(name)` — one `BusClient`, one `ScopedSecretStore` (plus the per-run HMAC secret for `guardian`/`execution` only), a `data_dir`, per subsystem. |
| `state.py` | `SystemStateMachine`: `booting → running ↔ paused → stopping → stopped`, terminal `failed`, idempotent pause/resume, a `scope="autonomous"` pause distinct from a full pause. |
| `scheduler.py` | `parse_duration`, `ActivityClock` (v1's `autonomy.py` ported onto an injected `Clock`), `Scheduler` — the three tick loops plus durable `system.schedule.*` timers, re-armed from the Ledger on every boot. |
| `supervisor.py` | `Supervisor` — concurrent layer boot gated on health, restart backoff table, a 10-minute restart-budget window, `SAFETY_CRITICAL` auto-pause callback. |
| `registry.py` | `LAYERS` (the full seven-layer target), `build_factories()` (bus/ledger today; a one-line entry per Phase 1+ package), `known_layers()`. |
| `metrics.py` | `MetricsTable`, `StatusServer` — `system.status.request/reply`, `system.health`/`system.metrics` aggregation. |
| `migrate_v1.py` | `migrate(ledger, path)` — idempotent replay of v1's `~/.simorgh/memory.jsonl`, routed through `simorgh.ledger.migrate_v1`. |
| `api.py` | `RuntimeConfig`, `SecretStore` protocol, `Supervised`, `KernelContext` (a plain alias for `contracts.protocols.Context` — a frozen-dataclass subclass fights its own parent's `frozen=True`). |

## Using it

```bash
python -m simorgh --self-check      # prove the guarded action path works, then exit
python -m simorgh run               # boot and run until SIGINT/SIGTERM or system.stop
python -m simorgh status            # print the system.status snapshot
python -m simorgh migrate-v1        # import ~/.simorgh/memory.jsonl into the Ledger
```

```python
from simorgh.kernel.config import load_config
from simorgh.kernel.service import Kernel

kernel = Kernel(load_config(None))
await kernel.boot()      # -> running, once every layer is healthy
await kernel.wait_for_stop()
await kernel.shutdown()  # reverse-layer-order teardown -> stopped
```

## Tests

`python3 -m unittest discover -s tests/simorgh/kernel -t .` (139 tests:
config, secrets, state, scheduler, supervisor, registry, context
scoping, self-check, CLI, and `Kernel` itself). Four cross-package
integration tests live in `tests/simorgh/integration/`: booting toy
Phase 1 stand-ins through the real Supervisor, pause/resume suspending
and restoring the Scheduler's own ticks, a schedule surviving a
simulated crash into a second `Kernel` on the same Ledger, and a toy
`guardian` exhausting its restart budget auto-pausing the system through
the real `Supervisor` accounting.

## Build log

- 2026-09-06 — Phase 0, the last package: built to the spec.
  `--self-check` passes all four proofs for the first time. Doc fix
  noted in `00-README.md`'s changelog: `03`'s self-check walkthrough
  named step 2 as a bus publish-policy test; the Kernel is itself an
  allowed publisher of `action.approved` (`PUBLISH_ONLY_BY`), so a
  forged one is a token-verification failure Execution catches
  downstream, not a policy violation — step 4 (a throwaway source
  subscribing to `action.proposed`) is the real policy-violation proof.
  1336 tests passing (v1 + contracts + bus + ledger + 148 new for the
  kernel).

## Open questions

See spec §12. Phase 0 has no periodic health-poll driver wired into
`boot()` yet — `Supervisor.poll_once()` exists and is exercised directly
by `test_guardian_down_autopauses.py`, standing in for that future
ticker (`runtime.health_every_s` is parsed but not yet consumed).
