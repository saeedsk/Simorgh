# kernel -- contract

One-line status: layer 0 · 4,140 lines · 20 test files · lock: `kernel` in docs/modules/locks.toml

## Purpose

The Kernel is the composition root and the process's owner: it loads `simorgh.toml`, builds the one Ledger client, the one telemetry store and the one bus backend, installs the reserved-topology policy, builds each subsystem's `Context` (its own `BusClient`, its config section, scoped secrets, a data directory), boots the subsystems in `registry.LAYERS` order waiting on each layer's health, and then runs the state machine, the tick scheduler, the status server, the health ticker and the signal handling. It holds no policy about work: ticks are unconditional (`scheduler.py` docstring) and it never decides whether to act on one. `registry.py` is the only module in the codebase allowed to import another subsystem's `Service`; everything else here depends only on contracts, the bus client and the ledger client. The shaping decision: every subsystem, the bus and the ledger included, is a `Subsystem` with `start(ctx)/stop()/health()` started by one `Supervisor`, so restart, pause-on-Guardian-down and ordered shutdown are one mechanism. It must never boot with an invalid `[runtime]` (a bad `mode` is a `ConfigError`, not a fallback) and never let a stuck thread keep the process alive after a stop (`cli.py` hard exit).

## Files

| File | For |
|---|---|
| `simorgh/kernel/__init__.py` | exports `Kernel`, `KernelBootError`, `VERSION` |
| `simorgh/kernel/api.py` | `RuntimeConfig`, `Supervised`, `SecretStore` protocol, `MissingSecret` |
| `simorgh/kernel/bootprogress.py` | boot stage progress bar on an interactive TTY |
| `simorgh/kernel/cli.py` | `python -m simorgh` subcommands, logging setup, signal `Stopper` and hard exit |
| `simorgh/kernel/config.py` | config file search, `[runtime]` parsing, `SIMORGH_RUNTIME_*` overrides, `LoadedConfig` |
| `simorgh/kernel/configcheck.py` | boot warnings for config sections and keys that change nothing; known dead fields |
| `simorgh/kernel/context.py` | `ContextFactory` (one `Context` per subsystem) and the stdlib logger |
| `simorgh/kernel/metrics.py` | `MetricsTable`, `StatusServer`, process gauges, `MetricsHistoryWriter` |
| `simorgh/kernel/migrate_v1.py` | `simorgh migrate-v1`: replays v1 records into the Ledger |
| `simorgh/kernel/registry.py` | `LAYERS`, `build_factories`, `NEEDS_HMAC_SECRET`, `DEFAULT_SECRETS` |
| `simorgh/kernel/scheduler.py` | second/idle/sleep ticks, activity clock, durable schedules |
| `simorgh/kernel/secrets.py` | env and file secret stores, per-subsystem scoping |
| `simorgh/kernel/selfcheck.py` | `--self-check`: proves the action path with stub Guardian/Execution on a private bus |
| `simorgh/kernel/service.py` | `Kernel` (boot, handlers, shutdown) and `WorkerKernel` (local-multi worker process) |
| `simorgh/kernel/state.py` | the system state machine |
| `simorgh/kernel/statusread.py` | `simorgh status` without booting: `GET /api/status` on the running instance, else the last `system.state` read straight from the ledger files |
| `simorgh/kernel/supervisor.py` | start by layer, health polling, restart with backoff, pause on safety-critical down |
| `simorgh/kernel/vault.py` | encrypted multi-field credential vault and `vault:` lookups |

## Consumes

`Kernel.consumes` (`service.py:111-116`) is authoritative. Subscriptions are spread over the Kernel and the objects it owns:

| Topic | Schema | Where | Does |
|---|---|---|---|
| `system.pause` | `messages/system.py::SystemPause` | simorgh/kernel/service.py:294 | state machine to `paused` (or scoped autonomous pause), `system` stream, `system.state.changed` |
| `system.resume` | `messages/system.py::SystemResume` | simorgh/kernel/service.py:295 | the reverse of pause |
| `system.stop` | `messages/system.py::SystemStop` | simorgh/kernel/service.py:296 | to `stopping`; releases `wait_for_stop` |
| `system.restart` | `messages/system.py::SystemRestart` | simorgh/kernel/service.py:297 | as stop, and sets `restart_requested` so the CLI exits 75 for the loader to relaunch |
| `system.status.request` | `messages/system.py::SystemStatusRequest` | simorgh/kernel/metrics.py (`StatusServer`) | replies with state, subsystems, health and metrics from memory |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/kernel/metrics.py (`StatusServer`) | records per-subsystem health for status |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/kernel/metrics.py (`StatusServer`) | records per-subsystem gauges for status and `metrics:history` |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | simorgh/kernel/scheduler.py:189 | marks human activity (resets the idle clock) |
| `system.schedule.add` | `messages/system.py::SystemScheduleAdd` | simorgh/kernel/scheduler.py:190 | records a durable schedule and arms it |
| `system.schedule.cancel` | `messages/system.py::SystemScheduleCancel` | simorgh/kernel/scheduler.py:191 | records the cancel and disarms it |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/kernel/service.py:335 (`_on_sleep_tick`) | one telemetry retention pass (`TelemetryService.on_sleep_tick`, skipped within `[telemetry] maintain_min_interval_s` of the last); only when telemetry is enabled |

`selfcheck.py` subscribes to `action.proposed`, `action.approved`, `system.pause`, `system.resume` and publishes `action.*`/`system.pause|resume`, but only on its own private in-memory bus with stub `guardian`/`execution` sources during `--self-check`; nothing it does reaches the live bus.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `system.started` | `messages/system.py::SystemStarted` | simorgh/kernel/service.py:311 | once, after every layer is up and the scheduler started |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/kernel/service.py | after boot (with `autonomous_paused` only when true), on pause, resume, stop, restart |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/kernel/scheduler.py | every second, also while paused |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/kernel/scheduler.py | while running, when no percept for `idle_threshold_s`, at most every `idle_tick_cooldown_s` |
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/kernel/scheduler.py | every `sleep_every_s` (6 h) while running; the first one 6 h after boot |
| `percept.time.scheduled` | `messages/percept.py::PerceptTimeScheduled` | simorgh/kernel/scheduler.py:279 | a durable schedule fires |
| `system.schedule.added` | `messages/system.py::SystemScheduleAdded` | simorgh/kernel/scheduler.py | a valid `system.schedule.add` was recorded |
| `system.health` | `messages/system.py::SystemHealth` | simorgh/kernel/service.py:464, 538 | a supervised service's status changed (health ticker), or a safety-critical service went down and the system paused |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/kernel/metrics.py (`ProcessMetricsPublisher`) | every `metrics_every_s`: process memory/CPU/threads |
| `system.status.reply` | `messages/system.py::SystemStatusReply` | simorgh/kernel/metrics.py | reply to `system.status.request` |
| `system.stop` | `messages/system.py::SystemStop` | simorgh/kernel/cli.py:168 | first SIGINT/SIGTERM (priority 9) |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `system` | simorgh/kernel/service.py:400 (`system.state` events) | the Kernel at boot (`_restore_autonomous_pause`); `simorgh status` when nothing answers (`statusread.py`, the files read directly, read-only) | forever |
| `schedule` | simorgh/kernel/scheduler.py:33 (`schedule.added/cancelled/fired`) | the Scheduler at start (`materialize`) | forever |
| `config:effective` | simorgh/kernel/service.py:473 | simorgh/interface/dispatch.py (`config` command) | forever |
| `metrics:history` | simorgh/kernel/metrics.py, only when there is no telemetry store; otherwise each snapshot is the telemetry sample series `metrics.history` (stage 1 item 3) | simorgh/interface/httpapi.py, simorgh/execution/tools.py, `simorgh status` offline (`statusread.py`, last sample only) | 7d in DEFAULT_RETENTION, but not applied while written (see ledger/CONTRACT.md) |
| `trace:<id>` | read only, `simorgh trace`, after the telemetry store (`telemetry.store.read_trace`) finds nothing | written by bus/trace.py only with `[bus] trace_backend = "ledger"` | 2d |

Not a ledger stream: the Kernel opens `<data_dir>/telemetry.sqlite` (spans and samples, `simorgh/telemetry/CONTRACT.md`) at boot, after the ledger, and closes it at shutdown after the subsystems stop and before the bus backend and ledger.

The Kernel also appends v1 records through `migrate_v1.py` (routes in ledger/migrate_v1.py). The `vault:`, `env:`, `bw:`, `ssm:` strings in `vault.py` are credential-reference prefixes, not ledger streams; the vault is an encrypted file (`vault.py::default_vault_path`).

## Config

`[runtime]` in simorgh.toml; dataclass `RuntimeConfig` in `simorgh/kernel/api.py`, parsed by `kernel/config.py::load_runtime_config`. Every key is overridable by `SIMORGH_RUNTIME_<KEY>`. The Kernel also passes `[bus]`, `[ledger]`, `[telemetry]`, `[execution]` and `[guardian]` to those packages (`[telemetry]` keys are listed in `simorgh/telemetry/CONTRACT.md`; `enabled = false` hands every Context the no-op), and every other section to its subsystem's `Context.config`.

| Key | Default | Read in the package |
|---|---|---|
| `mode` | `'single'` | yes (`single`, `local-multi`, `aws`; anything else is a `ConfigError`) |
| `data_dir` | `'~/.simorgh'` | yes |
| `deployment` | `'local'` | NO (declared, never read) |
| `subsystems` | `('all',)` | yes (since 2026-09-19; `bus`, `ledger`, `guardian` always boot) |
| `disabled` | `()` | yes (since 2026-09-19; unknown names are logged) |
| `idle_threshold_s` | `10.0` | yes |
| `idle_tick_cooldown_s` | `3.0` | yes |
| `sleep_every_s` | `21600` | yes |
| `metrics_every_s` | `10.0` | yes |
| `health_every_s` | `5.0` | yes (since 2026-09-18, `service.py:302`) |
| `supervisor_backoff_s` | `(1, 2, 4, 8, 16, 32, 60)` | yes |
| `supervisor_max_restarts_per_10m` | `5` | yes |
| `stop_grace_s` | `15.0` | yes |
| `allow_backend_fallback` | `False` | yes (ledger fallback) |
| `log_level` | `'info'` | yes (`cli.py::_configure_logging`, from the raw section) |
| `log_to_ledger` | `True` | NO (declared, never read) |
| `schedules.max_duration_s` | `86400.0` | yes |
| `schedules.persist` | `True` | NO (declared, never read; schedules always persist) |

Other environment the package reads: `SIMORGH_CONFIG`, `SIMORGH_RUNTIME_DATA_DIR`, `SIMORGH_EXECUTION_REPO_ROOT` (via `_with_env_overrides`, service.py:32), `SIMORGH_VAULT_PATH`, `SIMORGH_VAULT_NO_KEYRING`. Config search order (`config.py:38-51`): `--config`, `$SIMORGH_CONFIG`, `./simorgh.toml`, `${data_dir}/simorgh.toml`.

## Public Python surface

- `simorgh.kernel.Kernel` (`service.py:108`): implements `Subsystem` with `name="kernel"`; `Kernel(config: LoadedConfig, *, secrets=None, clock=None, interactive=False)`, `boot()`, `wait_for_stop()`, `shutdown()`, `health()`, `status_snapshot()`, attributes `bus`, `ledger`, `telemetry` (the `TelemetryService`, or None when `[telemetry] enabled = false`), `state`, `run_id`, `restart_requested`. `KernelBootError` when a layer fails or times out.
- `WorkerKernel` (`service.py:595`): one orchestration Worker per process in `local-multi` mode; unused live.
- `kernel.config.load_config`, `LoadedConfig`, `ConfigError`; `kernel.api.RuntimeConfig`.
- `kernel.registry.LAYERS`, `build_factories`, `known_layers`.
- `kernel.selfcheck.run()` (the `--self-check` proof) and `kernel.vault.Vault`.
- `kernel.statusread.read_status(config, *, timeout=2.0) -> (snapshot, source_line)`: what `simorgh status` prints. Never constructs a `Kernel`, never starts a Ledger client, never appends. It asks `GET /api/status` at `[interface] http_host`/`http_port` (a wildcard bind is asked on `127.0.0.1`) with `SIM_API_TOKEN` from the Kernel's secret chain, within `--timeout`; if nothing usable answers it reads the last `system.state` on `system` and the last `metrics:history` sample from the ledger files (`jsonl` read backwards, `sqlite` opened `immutable=1`, or `mode=ro` when a `-wal` is present; `memory`/`dynamodb` cannot be read offline and the command exits 1). The JSON on stdout carries `source: "live"` or `source: "ledger"` with `as_of`; the ledger form has `state`, `autonomous_paused`, `previous`/`reason`/`requested_by`, `mode` (from config) and `metrics`, and leaves out `run_id`, `uptime_seconds` and `subsystems`, which nothing records. One line on stderr says which source was used (`status: live, from <url>` or `status: from the ledger, as of <time> (<why not live>)`).
- `kernel.context.ContextFactory(..., telemetry=None)`: the store every `Context.telemetry` gets; None means `contracts.protocols.NULL_TELEMETRY` (tests, `WorkerKernel`).
- Other packages see the Kernel only through `simorgh.contracts.protocols` (`Context`, `Subsystem`, `Health`, `Clock`, `Logger`, `Telemetry`) and the topics above.
- Module-level mutable state: `registry.DEFAULT_SECRETS` (a dict; mutating it changes every later boot in the process), `cli._HARD_EXIT` (patched by tests), `configcheck.KNOWN_DEAD_FIELDS`/`EFFECTIVE_DEFAULTS` (dicts read as tables). Process-wide side effect: `cli._configure_logging` installs a root logging handler.

## Invariants

- The Kernel is the only non-`guardian` publisher allowed for `action.approved` and one of the allowed publishers of `system.pause`, `system.resume`, `system.stop`, `system.restart`, `system.reload` (`contracts/topics.py` `PUBLISH_ONLY_BY`); the policy that enforces the whole table (`bus.enforcement.ReservedTopologyPolicy`) is installed by the Kernel on every client it builds.
- Layers start in `LAYERS` order and a layer starts only after the previous layer is healthy; a boot failure records `failed` on the `system` stream and raises `KernelBootError`.
- Shutdown appends `stopped` to the `system` stream before any layer is stopped, then stops layers in reverse order, then flushes and closes the telemetry store, then the bus backend, then the ledger.
- Every `Context` the Kernel builds carries the same `telemetry` (the Kernel's `TelemetryService`, or `NULL_TELEMETRY` when disabled); the store is not a supervised subsystem and is not in `LAYERS`.
- Every state transition is appended to the `system` stream before `system.state.changed` is published.
- A scoped autonomous pause survives a restart: it is read back from the `system` stream before the boot `system.state.changed`, and the boot event asserts `autonomous_paused` only when true.
- If `guardian` or `execution` is still `down` after its restart budget is spent, the system pauses (`supervisor.SAFETY_CRITICAL`, `supervisor.py:109`).
- A service reporting `down` is stopped and started again with a fresh `Context`, with backoff, up to `supervisor_max_restarts_per_10m`.
- Each subsystem's `Context.bus` is its own `BusClient` with a fixed `source`; `Context.secrets` returns only names the subsystem declared or `DEFAULT_SECRETS` grants; only `guardian` and `execution` get the per-run HMAC secret.
- Idle and sleep ticks are not published while paused; the second tick is.
- The first signal publishes `system.stop`; a second signal, or a shutdown that overruns `stop_grace_s + 10` s, exits the process with `os._exit`.
- A `[runtime] mode = "local-multi"` with a `memory` bus or ledger backend is refused at boot.
- The test suite never inherits `SIMORGH_*` from the operator's environment (`conftest.py`).

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract kernel`.

- `tests/simorgh/kernel/test_service.py` -- boot order, pause/resume/stop/restart handling, state events, `system.started`, shutdown order.
- `tests/simorgh/kernel/test_registry.py` -- `LAYERS`, the factories, secret scoping tables.
- `tests/simorgh/kernel/test_config.py` -- search order, `[runtime]` parsing, env overrides, `ConfigError` on bad values.
- `tests/simorgh/kernel/test_context.py` -- one client per subsystem with its own source, scoped secrets, data dirs, shared metrics.
- `tests/simorgh/telemetry/test_kernel_wiring.py` -- a booted Kernel puts its one telemetry store on every Context, the sleep tick runs retention, shutdown flushes, `enabled = false` hands out the no-op.
- `tests/simorgh/kernel/test_scheduler.py` -- tick cadence and conditions, activity clock, durable schedules replayed at start.
- `tests/simorgh/kernel/test_state.py` -- legal transitions, idempotent pause/resume, scoped autonomous pause.
- `tests/simorgh/kernel/test_supervisor_restarts.py` -- a `down` service is restarted with a fresh Context; the ticker drives it (B10).
- `tests/simorgh/kernel/test_status_reads_never_boots.py` -- `simorgh status` with nothing running reads the ledger and leaves every file unchanged; with an instance answering it prints live data and never reads the ledger; `Kernel` is never constructed.
- `tests/simorgh/kernel/test_selfcheck.py` -- the self-check proves approval with a verified token, rejects a forged one, and enforces the reserved topics.

## Known issues (2026-09-18 evaluation)

- S1 (critical): `service.py:203` still defaults `[guardian] irreversible_requires_human` to false. The physical half was fixed 2026-09-18 (stage 0 item 2, `PhysicalRule` and `[guardian.physical]`, commit `8916e82`, in guardian); non-physical irreversible actions are still auto-approved by this default.
- B10 (high): the Supervisor never supervised. Fixed 2026-09-18, commit `3beb2a5` (`Supervisor.run_ticker`, a restart that restarts, `system.health` on change).
- B21 (low): logging was never configured. Fixed 2026-09-18, commit `3beb2a5` (`cli._configure_logging`). `log_to_ledger` is still inert.
- B11 (high): a cwd-relative `simorgh.toml` could shadow the real config. The writer side was fixed 2026-09-18 in commit `3beb2a5` (`mcp approve` writes `contracts.settings.config_path()`); the Kernel still prefers `./simorgh.toml` over `${data_dir}/simorgh.toml` (`config.py:45`).
- B15 (medium): four config mechanisms; the documented `SIMORGH_<SECTION>_<KEY>` override exists for `[runtime]` and `[execution]` only. Open; stage 0 item 26.
- B19 (low): `MetricsHistoryWriter` appends a ~2.3 KB snapshot every 10 s. A 7d retention entry was added 2026-09-18 but does not truncate a stream that is still written (ledger/CONTRACT.md). Open; stage 1 item 3 makes it a telemetry sample.
- B7 (medium): one unbound `LedgerClient` handed to every Context (`context.py:141`). Open; stage 1 item 8.
- B14 (low): three deployment modes, `WorkerKernel`, the identity registry and `--self-check` cover a topology that has never run. Open; stage 1 item 10.
- B17 (low): `simorgh status` booted a second Kernel against the live data dir and appended `config:effective` and `system.state` to its ledger. Fixed 2026-09-19 (stage 1 item 9): `statusread.py` asks the running instance or reads the ledger files, read-only (`tests/simorgh/kernel/test_status_reads_never_boots.py`).
- B18 (low): no registry or cancellation of blocking work; `os._exit` in `cli.py` is the backstop. Open.
- B16 (medium): the loader killed Sim 250 ms after SIGINT. Fixed 2026-09-18 in `simloader.py` (commit `fd27fc7`); the Kernel side (`Stopper`) was already correct.

Found while writing this contract (not in the catalogue): `[runtime] subsystems` and `disabled` were parsed and never applied (fixed 2026-09-19, `service._wanted_subsystems`); `since_last_idle_tick` was always 0 (fixed 2026-09-19); and the Scheduler docstring says schedule firing stops while paused, but `_fire_after` (`scheduler.py:268`) never checks `is_running`.

## Planned changes (roadmap)

- Stage 1 item 3 done 2026-09-19: `MetricsHistoryWriter(telemetry=...)` writes the sample series `metrics.history`; `simorgh status` offline reads its last sample read-only (`telemetry.store.last_sample`) before the old stream.
- Stage 1 item 8: `ContextFactory` builds a `LedgerClient` bound to each subsystem's `source`.
- Stage 1 item 10: `WorkerKernel` (plan calls it `kernel/worker.py`; it lives in `service.py`) and the identity registry move under `simorgh/_frozen/`.
- Stage 4 item 4: the Kernel injects in-process reader interfaces (persona, self, memory) for the ContextBuilder.
- Stage 6 item 6 and stage 7 item 5: reminder delivery moves to `initiative/`; the scheduler publishes `task.wake` at a waiting task's `until` or matching event.
- Stage 8 items 1 and 8: `LAYERS` layer 4 becomes `("growth",)`; the nightly loop runs on `system.tick.sleep`.

## Working on this module

Lock it first (`python tools/modlock.py claim kernel --by <you> --task "..."`), commit the lock, edit only `simorgh/kernel/`, `tests/simorgh/kernel/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py kernel` before committing; commit subject `kernel: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.

- `ContextFactory.build` gives each subsystem a `BoundLedger` for its name (stage 1 item 8); the Kernel's own client is unbound.

- Logging (2026-09-19): when stderr is a terminal, the root log goes to `<data_dir>/logs/sim.log` (rotating, 5 MB x 3), never under the TUI; without a terminal it stays on stderr (`cli._log_handler`).

- Config check (2026-09-19): a section is reported only when it holds a key nothing reads, found by perturbing each key (`configcheck.unread_keys`); the warning names the keys. A correct key set to its default is no longer reported as a typo.
