# 03 — Kernel (`simorgh/kernel/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). This spec refines those; it may not
> contradict them.

**Layer:** 0 Substrate
**Owner (build):** built, Phase 0 (2026-09-06)
**Status:** built
**Depends on (contracts only):** `contracts.protocols.Subsystem/Bus/Ledger/Clock/Context/Health`, `contracts.messages.system`, `contracts.messages.percept` (`percept.time.scheduled`), `contracts.messages.action` (self-check only), `contracts.topics`
**v1 code that migrates here:** `src/orchestrator/autonomy.py` (`ActivityClock`, idle threshold/cooldown/daily-cap *timing* — not the action policy), `src/orchestrator/reminders.py` (`parse_duration`, one-shot timers → durable schedules), `src/main.py::self_check` and `__main__` arg handling, `main.py`'s `build_cognition_router`/`run_cli` *composition* role (not their logic), config constants scattered through `main.py` (`DEFAULT_*`, `SIMORGH_*` env vars).

## 1. Purpose and responsibilities

The Kernel is the composition root and supervisor: the only package
allowed to know every subsystem by name. It loads configuration and
secrets, constructs the Ledger and the Bus, installs the reserved-topic
policy, instantiates each subsystem's `Service` with a scoped `Context`,
starts them in dependency order, supervises them (health polling,
restart with backoff, degradation reporting), runs the scheduler that
turns time into messages (`system.tick.*`, `percept.time.scheduled`),
owns the system state machine (`running/paused/stopping/stopped`) and
the corrigibility commands that drive it, collects and publishes metrics,
and provides the operator CLI (`python -m simorgh …`) including the
`--self-check` that proves the structural safety path works before any
real work is allowed. It contains no cognition and takes no actions.

**Responsibilities (owns):**
- Configuration (`simorgh.toml` + env overrides), validation, per-subsystem sections.
- Secrets store; the per-run HMAC secret and its distribution to exactly `guardian` and `execution`.
- Subsystem registry, `Context` construction, lifecycle (`start/stop/health`), dependency-ordered startup, supervision/backoff.
- The `BusPolicy` implementation for reserved topics (`02` §3, `03` §3).
- System state machine; handling `system.pause/resume/stop`; `system.state.changed`.
- Scheduler: `system.tick.second`, idle detection → `system.tick.idle`, `system.tick.sleep`, durable schedules → `percept.time.scheduled`.
- Metrics aggregation → `system.metrics`; `system.status.request/reply`.
- CLI: `run`, `worker`, `status`, `trace <id>`, `migrate-v1`, `ledger compact`, `--self-check`, `--config`.
- Process modes `single` / `local-multi` / `aws`.
- The boundary test's rule set (`tests/simorgh/test_module_boundaries.py`).

**Explicit non-responsibilities (belongs elsewhere):**
- Deciding whether to act on an idle tick — `curiosity`/`planning`; the Kernel only emits the tick.
- Approving or executing actions — `guardian`/`execution` (the Kernel *tests* that path in self-check, never uses it).
- Rendering anything to a terminal — `interface`. The Kernel's CLI subcommands are thin: they publish a message or read the Ledger and print plain text; the interactive session is Interface.
- Budget accounting — `cognition`/`guardian`. The Kernel passes config through.

**Principles this subsystem is the primary enforcer of:** 4.3 (installs the topology policy and the HMAC secret), 4.5 (supervision = graceful degradation), 4.11 (corrigibility via the state machine), 4.12 (file-based config), 4.14 (mode/backends as configuration).

## 2. Position in the architecture

Layer 0; the process entry point. Boot order: config → secrets → Ledger
→ Bus (policy installed) → subsystems by layer (0 services: bus, ledger;
then 1: cognition, memory, worldmodel; 2: guardian, execution,
verification, planning; 3: learning, reflection, curiosity; 4: persona,
interface; then orchestration last, so no Worker can claim a task before
Guardian and Execution are up). Stop order is the reverse. The Kernel
originates Flow 5 (pause/stop), Flow 7 (restart/resume), Flow 8 (sleep
tick), and the tick that starts Flow 2/9.

Imports: as the composition root it may import every subsystem's
`Service` (`02` §4 rule 4) — but only in `registry.py`; every other
Kernel module imports contracts, bus/ledger clients, and stdlib.

## 3. Interfaces

### 3.1 Messages consumed
| Type | Pattern | Semantics | What this subsystem does with it |
|---|---|---|---|
| `system.pause` | exact | command (prio 9) | `running → paused`; emit `system.state.changed`; scheduler suspends idle/sleep ticks (second ticks continue) |
| `system.resume` | exact | command (prio 9) | `paused → running`; emit state change |
| `system.stop` | exact | command (prio 9) | `→ stopping`: stop orchestration first (workers checkpoint), then layers 4→0; emit `stopped`; exit |
| `system.status.request` | exact | request | Reply with the status snapshot (§3.3) |
| `system.health` | `system.health` | event | Update the health table; trigger supervision (restart/degrade) |
| `system.metrics` | `system.metrics` | event | Aggregate into the metrics table |
| `percept.text.received` | exact | event | `ActivityClock.touch()` — a human spoke; idle clock resets |
| `task.started` / `task.completed` / `task.failed` | `task.*` | event | Autonomous-activity counters for the daily cap gauge and digest |
| `system.schedule.add` / `system.schedule.cancel` | exact | command | Append to the `schedule` stream; arm/disarm timer (see §12 Q1 — proposed types) |

### 3.2 Messages produced
| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `system.started` | event | `{mode, subsystems:[name@version], data_dir, run_id}` | all |
| `system.state.changed` | event | `{state, reason, requested_by}` | all (guardian gates on it) |
| `system.tick.second` | event | `{n}` — sampled out of trace | anyone needing a heartbeat |
| `system.tick.idle` | event | `{idle_seconds, since_last_idle_tick}` — only when idle ≥ `idle_threshold` and cooldown elapsed | curiosity, planning |
| `system.tick.sleep` | event | `{window_seconds}` | memory, reflection, learning, ledger |
| `percept.time.scheduled` | event | `{schedule_id, label, payload?}` | interface (reminders), planning (scheduled goals) |
| `system.health` | event | `{subsystem:"kernel", …}` for its own state (config reload, supervisor actions) | interface |
| `system.metrics` | event | aggregated per-subsystem counters/gauges, plus `kernel.uptime_s`, `kernel.idle_s`, `kernel.state` | interface |
| `system.status.reply` | reply | see §3.3 | requester |

### 3.3 Request/reply APIs served
`system.status.request {}` → `system.status.reply`:

```json
{"ok": true, "run_id": "…", "mode": "single", "state": "running", "uptime_s": 1234.5,
 "idle_s": 42.0, "subsystems": {"guardian": {"version":"2.0.0","status":"ok","restarts":0,"last_health_ts":…}, …},
 "bus": {"backend":"memory","queue_depth":{…}}, "ledger": {"backend":"jsonl","bytes_total":…},
 "schedules": 3, "budget": {"claude_code_cli": {...}, "gemini": {...}}}
```
Timeout expectation: 2 s (answered from in-memory tables, no Ledger read).

### 3.4 Python protocol (`api.py`)

```python
# simorgh/kernel/api.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol
from simorgh.contracts.protocols import Bus, Ledger, Clock, Subsystem, Health, Context

@dataclass(frozen=True)
class RuntimeConfig:
    mode: str                     # single | local-multi | aws
    data_dir: Path
    deployment: str               # name used in aws resource prefixes
    subsystems: tuple[str, ...]   # enabled, in registry order
    idle_threshold_s: float = 10.0
    idle_tick_cooldown_s: float = 3.0
    sleep_every_s: float = 6 * 3600
    metrics_every_s: float = 10.0
    health_every_s: float = 5.0
    supervisor_backoff_s: tuple[float, ...] = (1, 2, 4, 8, 16, 32, 60)
    supervisor_max_restarts_per_10m: int = 5
    stop_grace_s: float = 15.0
    allow_backend_fallback: bool = False

class SecretStore(Protocol):
    def get(self, name: str) -> str | None
    def require(self, name: str) -> str          # raises MissingSecret

@dataclass
class KernelContext(Context):                    # concrete Context handed to Service.start()
    bus: Bus                                     # a BusClient bound to this subsystem's source name
    ledger: Ledger
    config: Mapping[str, Any]                    # this subsystem's [name] section, defaults applied
    secrets: SecretStore                         # scoped: only names the Service declared in `needs_secrets`
    clock: Clock
    logger: Any                                  # structured; routes to ledger `activity`/stdout per config
    data_dir: Path                               # ${runtime.data_dir}/<name>/
    name: str
    instance_id: str                             # "w3" for the 3rd worker; "0" otherwise
    mode: str
    run_id: str

class Supervised(Protocol):                      # what the supervisor tracks per subsystem
    name: str
    service: Subsystem
    task: Any                                    # asyncio.Task running start()
    status: str                                  # starting|ok|degraded|down|stopped
    restarts: int
    last_health: Health | None

class KernelPolicy:                              # implements bus.api.BusPolicy
    RESERVED_SUBSCRIBE = {"action.proposed": {"guardian"}, "action.approved": {"execution"}}
    RESERVED_PUBLISH  = {"system.pause": {"interface","kernel"}, "system.stop": {"interface","kernel"},
                         "system.resume": {"interface","kernel"}, "action.approved": {"guardian","kernel"}}
    def check_subscribe(self, source, pattern) -> None: ...   # exact or wildcard pattern that could match a reserved topic
    def check_publish(self, source, type) -> None: ...
```

Registry:

```python
# simorgh/kernel/registry.py — the ONLY place subsystems are named
from simorgh.bus.service import Service as BusService
from simorgh.ledger.service import Service as LedgerService
from simorgh.cognition import Service as CognitionService
# … one import per subsystem …
LAYERS: tuple[tuple[str, ...], ...] = (
    ("bus", "ledger"),
    ("cognition", "memory", "worldmodel"),
    ("guardian", "execution", "verification", "planning"),
    ("learning", "reflection", "curiosity"),
    ("persona", "interface"),
    ("orchestration",),
)
FACTORIES: dict[str, type[Subsystem]] = {...}
```

### 3.5 Configuration

`simorgh.toml` (searched: `--config`, `$SIMORGH_CONFIG`, `./simorgh.toml`,
`${data_dir}/simorgh.toml`; missing → defaults). Every key overridable
by `SIMORGH_<SECTION>_<KEY>` (uppercased, dots → `_`).

```toml
[runtime]
mode = "single"
data_dir = "~/.simorgh"
deployment = "local"
subsystems = ["all"]              # or an explicit list; "all" minus [runtime.disabled]
disabled = []
idle_threshold_s = 10.0           # v1: AutonomyController idle threshold
idle_tick_cooldown_s = 3.0        # v1: action cooldown (now paces the tick, not the action)
sleep_every_s = 21600
stop_grace_s = 15.0
log_level = "info"
log_to_ledger = true

[secrets]
file = "${runtime.data_dir}/secrets.toml"   # 0600; keys: GEMINI_API_KEY, …; env vars take precedence
hmac_secret_bytes = 32                      # per-run; never persisted

[schedules]
max_duration_s = 86400            # v1 reminders MAX_DURATION_SECONDS
persist = true                    # v1 reminders were session-only; v2 default durable

[bus]  …see 01-bus.md
[ledger] …see 02-ledger.md
[cognition] [memory] [guardian] …            # passed through as each Service's ctx.config
```

## 4. Data model and Ledger streams

- **`system`** stream: `system.started`, `system.state.changed`,
  `system.stopped`, `kernel.config.loaded {hash}`, `kernel.supervisor
  {subsystem, action: restart|degrade|down, attempt}`. Rebuilding the
  system stream yields uptime/continuity history for the Self Model
  (`06-worldmodel.md` reads it via Reflection's `self.observation`).
- **`schedule`** stream: `schedule.added {schedule_id, fire_at, label,
  recurrence?: {every_s | cron}, payload, requested_by}`,
  `schedule.fired`, `schedule.cancelled`. Projection `ScheduleView` →
  the armed timers. This is the durable replacement for v1's
  session-only reminders (a restart no longer forgets a reminder).
- **In-memory only (justified caches):** health table, metrics
  accumulators, `ActivityClock.last_activity`, the HMAC secret (must
  never be persisted — a fresh run means fresh tokens, so no approval
  survives a restart).
- Files owned: `${data_dir}/simorgh.toml` (optional), `secrets.toml`,
  `run.lock` (single-instance guard per data dir in `single` mode).

## 5. Internal design

```
simorgh/kernel/
  __main__.py     argparse → cli.py
  cli.py          run | worker | status | trace <id> | migrate-v1 | ledger compact | --self-check | --config
  config.py       load/merge/validate; env overrides; ${var} interpolation; hash
  secrets.py      FileSecretStore (0600 check), EnvSecretStore, ScopedSecretStore; new_hmac_secret()
  context.py      KernelContext factory per subsystem
  registry.py     LAYERS, FACTORIES (imports every Service)
  policy.py       KernelPolicy (reserved topics)
  supervisor.py   start/stop ordering, health polling, restart with backoff, degrade/down
  state.py        SystemState machine; pause/resume/stop handlers
  scheduler.py    second ticks; ActivityClock; idle ticks; sleep ticks; durable schedules → percept.time.scheduled
  metrics.py      aggregation + system.metrics publisher; status reply
  selfcheck.py    the structural safety proof (see §5.4)
  migrate_v1.py   thin: calls ledger.migrate_v1.read_v1 → ledger.append, reports counts
  boundaries.py   the import-rule checker used by tests/simorgh/test_module_boundaries.py (also `simorgh check-boundaries`)
  service.py      Service(Subsystem) name="kernel": consumes/produces per §3; wraps scheduler/metrics/state
  config.py
```

### 5.1 Boot sequence (`run`)
```
parse args → load config → take run.lock (single) → open Ledger → open Bus(backend, policy=KernelPolicy)
→ hmac = os.urandom(32) → for layer in LAYERS: for name in layer: ctx = KernelContext(...);
     if name in ("guardian","execution"): ctx.secrets = scoped(+"hmac")
     service = FACTORIES[name](); await supervisor.start(service, ctx)   # waits for health ok or timeout 30s
→ publish system.started → state=running → scheduler.start() → await stop event → shutdown sequence
```
Startup of a layer waits for every service in the previous layer to
report `health == ok` (or `degraded` with `boot_ok=True`), so Guardian
is verified up before any Worker exists.

### 5.2 System state machine
```
   booting ──all layers ok──▶ running ◀──resume── paused
      │                          │   └──pause───────▲
      │                          └──stop──▶ stopping ──drained──▶ stopped ──▶ process exit 0
      └──boot failure──▶ failed ──▶ exit 2
```
`pause` and `resume` are idempotent. `stop` while `paused` proceeds
directly. Transitions append to the `system` stream *before* the
`system.state.changed` event is published, so a crash between the two
is recovered on restart (the last recorded state is re-announced).

### 5.3 Supervisor
Each service runs as an `asyncio.Task` wrapping `start()`. Health is
polled every `health_every_s`; three consecutive non-`ok` polls →
`degraded` (published); an exception escaping `start()` or `health()`
raising → restart with the next backoff delay; more than
`supervisor_max_restarts_per_10m` → `down`, no further restarts, a
`system.health{critical}` to Interface. Guardian and Execution are
special: if either is `down`, the Kernel transitions to `paused`
automatically (nothing may execute without the safety path) and
announces why. In `local-multi`, Worker processes are supervised by the
OS-level `worker` command with the same backoff (a crashed Worker's
task lease simply expires — Flow 7).

### 5.4 Self-check (`--self-check`)
Boots the full registry on the `memory` bus and `memory` ledger in a
temp data dir with providers disabled (cognition reports floor-only),
then:
1. Publishes `action.proposed{tool:"noop", read_only:true}` as source
   `kernel` → expects `action.approved` (with a valid token) →
   `action.result{ok:true}` within 5 s.
2. Publishes a forged `action.approved` with a random token directly →
   expects Execution to emit `action.result{ok:false, error.code:
   "invalid_token"}` and *no* `tool.invoked`.
3. Publishes `system.pause` → a second `noop` proposal must yield
   `action.denied{layer:"paused"}`; `system.resume`.
4. Attempts `bus.subscribe("action.proposed")` from a throwaway source
   → expects `PolicyViolation`.
5. `system.stop` → exits 0 if all four passed, else prints the failing
   step and exits 1.
This replaces v1's `self_check()` (import-and-construct) with a
behavioral proof; `learning`'s relaunch tool calls it before `execv`.

### 5.5 Scheduler
- `second` loop: `await clock.sleep(1)`; publish `system.tick.second{n}` (trace-sampled to 0).
- Idle: `ActivityClock` (ported) touched on `percept.text.received`; when
  `idle_seconds ≥ idle_threshold_s` and `now - last_idle_tick ≥
  idle_tick_cooldown_s` and state is `running`, publish
  `system.tick.idle`. The tick is *unconditional* on backlog state —
  Curiosity/Planning decide what to do; the Kernel never inspects tasks.
- Sleep: every `sleep_every_s` while `running` (and at `stop` if
  `sleep_on_stop`), publish `system.tick.sleep`.
- Schedules: `ScheduleView` projection over the `schedule` stream; an
  `asyncio` timer per armed entry; on fire: append `schedule.fired`,
  publish `percept.time.scheduled`, re-arm if recurring. `parse_duration`
  ported from v1 for the CLI/Interface convenience of "1m", "2h".

### 5.6 Modes
- `single`: everything above in one process.
- `local-multi`: `simorgh run` starts the Kernel with all subsystems
  *except* `orchestration`; `simorgh worker --id w1` starts a Kernel in
  worker mode: config, Ledger (`sqlite`), Bus (`sqlite`), and only the
  `orchestration` Service (with `guardian`/`execution` still in the main
  process — actions cross the bus). The secret: workers never need it
  (they propose; they do not approve or execute). Interface may also run
  as its own process (`simorgh ui`) for a detached terminal.
- `aws`: identical wiring with `aws` backends; the HMAC secret is
  distributed by the Kernel to guardian/execution processes via the
  secrets file (rotated per deployment, not per run).

## 6. Key behaviors — worked scenarios

**S1 — Cold boot to first autonomous tick (Flow 2 start).** `simorgh run`:
config hash logged; Ledger opens (rebuilds index); Bus opens with
`KernelPolicy`; layers start (guardian health ok at t+0.4 s; execution
registers 11 tools; orchestration starts 1 Worker). `system.started`
published; state `running`. No `percept.text.received` arrives; at
t+10 s `idle_seconds=10 ≥ 10` → `system.tick.idle{10.0}`. Planning
replies to nobody (it just consults its projection); with an empty
backlog Curiosity runs Flow 9; 3 s later the next idle tick is eligible.

**S2 — Pause, then a human command (Flow 5).** Interface publishes
`system.pause{requested_by:"human"}`. Kernel: append `system.state.changed`
(seq 41) → publish. Guardian denies the next proposal (`layer:paused`).
Scheduler suspends idle/sleep ticks. The human types a message: Interface
publishes `percept.text.received`; the clock touches; Orchestration
opens a turn; its `cognition.think` proceeds (thinking is not an
action), but any tool call it proposes is denied with a clear
`ui.notice` — the human sees "paused: I can answer but not act." `system.resume`
restores everything.

**S3 — Failure: Guardian crashes at runtime.** Guardian's task raises
(bug). Supervisor: restart after 1 s → healthy. It raises again 4 more
times within 10 min → `down`. Kernel auto-transitions to `paused`,
publishes `system.health{severity:critical, detail:"guardian down —
system paused"}` and a `ui.notice`; every Worker's next proposal is
denied by… nobody (no Guardian) — so it times out; Orchestration treats
a proposal timeout as denial (`16-orchestration.md`), checkpoints the
task (`task.paused`), and parks. When a human runs `simorgh run` again
(or fixes and `system.resume` after a manual restart), work resumes from
the Ledger.

**S4 — Durable reminder across a restart.** Interface publishes
`system.schedule.add{fire_at: now+3600, label:"call the vet"}`. Kernel
appends `schedule.added`, arms a timer. The process is stopped and
restarted after 20 min. On boot `ScheduleView` rebuilds; the timer is
re-armed for the remaining 40 min; it fires `percept.time.scheduled`;
Interface prints the reminder. v1 would have forgotten it.

## 7. Design considerations and tradeoffs

- **A composition root, not a framework.** The Kernel wires concrete
  services; it does not provide dependency-injection magic. This keeps
  the boot sequence readable and the boundary rule enforceable
  (harness-02 "when (not) to reach for a framework").
- **Layered startup waits on health** (slower boot, ~2–3 s) versus
  starting everything at once and letting messages queue. Chosen because
  a Worker that claims a task before Guardian is up would time out and
  park — correct but noisy; and because the self-check's guarantee
  ("nothing runs before the safety path is proven") is only meaningful
  if ordinary boot honors the same order.
- **Ticks are unconditional and dumb.** The Kernel does not know whether
  there is work; it only knows time and human activity. Every decision
  about acting lives in Curiosity/Planning/Guardian. This removes v1's
  `AutonomyController` decision logic from the timing layer — the
  circuit breaker becomes Guardian's trust posture, the daily cap a
  Guardian budget rule — so timing can be retuned without touching
  policy (v1 needed three retunes; EVOLUTION milestones 56/72/80).
- **Per-run HMAC secret, never persisted.** A restart invalidates every
  outstanding approval. Cost: a task mid-flight must re-propose its
  next action after a restart (cheap). Benefit: no stale approval can
  ever execute against changed code (harness-01 "reversibility-weighted
  risk"; SOUL Directive 4).
- **Auto-pause when the safety path is down** rather than "keep going
  read-only": simpler to reason about, and read-only proposals still
  need Guardian to *classify* them as read-only. (harness-01 "deny-first
  with human escalation".)
- **Durable schedules** replace v1's ephemeral reminders — a small scope
  increase justified by Flow 7's promise that nothing that matters is
  lost on restart (harness-05 §7).

## 8. Safety, degradation, and failure modes

| Condition | Behavior |
|---|---|
| Config invalid | Exit 2 with the offending key; never start with defaults silently |
| Secrets file world-readable | Refuse to load it; exit 2 (mirrors ssh) |
| Configured backend unavailable | Exit 2 unless `allow_backend_fallback=true` (then `jsonl`/`memory` with a critical notice) |
| Ledger `down` at runtime | Kernel → `paused` (Guardian also denies independently); resumes automatically when Ledger health returns `ok` and state was auto-paused |
| Guardian or Execution `down` | Kernel → `paused` (S3); manual resume after fix |
| Subsystem crash loop | Backoff → `down` → critical notice; other subsystems continue |
| Second `simorgh run` on the same data dir (`single`) | `run.lock` refuses; message tells the operator |
| `system.stop` with a hung handler | Grace `stop_grace_s`, then cancel; leases released; exit 0 with a warning; the stuck task resumes next run |
| SIGINT/SIGTERM | Treated as `system.stop{requested_by:"signal"}`; second SIGINT → immediate exit 130 |
| Clock jumps backwards | `ActivityClock` uses monotonic time for idle; wall time only for schedules (re-armed on resume with clamping) |

Corrigibility: `system.pause/stop` are the highest-priority messages in
the system, handled by the Kernel without consulting any other
subsystem; the Kernel itself never proposes actions, so there is no
path by which the system's own goals can defer a stop. Guaranteed floor:
`simorgh run` with no config, no secrets, and no providers boots to a
running system that can converse on the deterministic floor and cannot
act (no tools approved beyond read-only noop).

## 9. Testing strategy

- **Contract tests**: every `system.*` and `percept.time.scheduled` payload validates; `system.status.reply` schema.
- **Unit tests** (`tests/simorgh/kernel/`): config merge/interpolation/env override/validation; secrets scoping (a service not declaring `hmac` cannot read it); registry layer order; supervisor backoff table and `down` threshold with `FakeClock`; state machine transitions (all edges, idempotent pause); scheduler idle/cooldown math (port v1 `test_autonomy.py` timing cases), sleep cadence, schedule persistence/re-arm; `KernelPolicy` accept/deny matrix including wildcard patterns (`action.*` from `curiosity` must be refused); `parse_duration` (v1 tests).
- **Boundary test** (`tests/simorgh/test_module_boundaries.py`): walks `simorgh/**/*.py` with `ast`, collects `import`/`from … import` targets, and asserts exactly the rules of `02` §4: (1) a subsystem package imports only `simorgh.contracts.*`, `simorgh.bus.client`/`simorgh.bus.api`, `simorgh.ledger.client`/`simorgh.ledger.api`, stdlib, itself; (2) `simorgh.contracts` imports stdlib only; (3) `simorgh.bus`/`simorgh.ledger` import only contracts + stdlib (+ lazy `boto3` inside `aws.py`/`dynamodb.py`, checked as function-level imports); (4) only `simorgh.kernel.registry` may import other subsystems; (5) no third-party top-level import anywhere in `simorgh/` except inside an explicit `try/except ImportError` in an adapter module. Failure messages name the file, line, and rule.
- **Self-check test**: runs `selfcheck.run()` in-process with fake Guardian/Execution that implement the token contract; asserts steps 1–4 and that a broken fake (accepts forged tokens) makes the check fail.
- **Integration**: `test_kernel_boot_two_toy_subsystems.py` (Phase 0 acceptance; each bus/ledger backend); `test_flow_5_pause_resume_stop.py`; `test_flow_7_restart_resumes_schedule_and_state.py`; `test_guardian_down_autopauses.py`.
- **Mocks**: `FakeClock` for all timing; toy services in `tests/simorgh/helpers.py`.

## 10. Build steps (an agent picks this up here)

1. Skeleton; `config.py` (+ tests) ; `secrets.py` (+ scoping tests); `api.py`. *Accept:* config/secrets tests; boundary test (add `boundaries.py` now — the Phase 0 deliverable everyone else needs).
2. `policy.py` + tests against the Bus's `AllowAllPolicy` interface. *Accept:* matrix test.
3. `registry.py` with only `bus`/`ledger` + a `NullSubsystem`; `context.py`; `supervisor.py` (start order, health poll, backoff, down); `state.py`. *Accept:* supervisor/state unit tests with fakes.
4. `service.py` + `scheduler.py` (ticks, `ActivityClock`, sleep, durable schedules) + `metrics.py` (+ status reply). *Accept:* scheduler tests; status reply contract test.
5. `cli.py`/`__main__.py`: `run`, `status`, `trace`, `--config`. *Accept:* `python -m simorgh --self-check` exits 0 with zero real subsystems (self-check steps 1–3 skipped with "no guardian/execution registered" when absent, step 4 still enforced); integration boot test on `memory` + `sqlite`.
6. `selfcheck.py` full behavior (needs Guardian/Execution fakes now; real ones in Phase 1B). *Accept:* self-check unit test.
7. `migrate-v1` and `ledger compact` subcommands (thin over the Ledger). *Accept:* fixture test.
8. `worker` mode (Phase 5): orchestration-only Kernel over `sqlite`. *Accept:* two-process crash/resume drill.
9. README build log, config table, EVOLUTION milestone.

Size: **M**. Parallelizable: steps 1–2 vs. 3–4 by two agents; steps 7–8 independent.

## 11. Migration notes

- `autonomy.py::ActivityClock` → `scheduler.py` verbatim (monotonic clock, `touch()` on `percept.text.received`). `AutonomyController`'s idle threshold / cooldown → `[runtime]` keys; its `enabled` flag → `system.pause/resume` scoped to autonomous work (Interface's `autonomous off` publishes a pause with `scope:"autonomous"`; Guardian honors the scope — proposals from human turns still pass; see `09-guardian.md`); its daily action cap → Guardian budget rule; its failure-streak circuit breaker → Guardian trust tightening; `digest()` → Interface projection over `task.*`.
- `reminders.py::parse_duration` → `scheduler.py` (with its tests); `schedule_reminder` → `system.schedule.add` + `percept.time.scheduled`; the print → Interface's `ui.notice`.
- `main.py::self_check` → `selfcheck.py` (behavioral); `main.py` `__main__` arg parsing → `cli.py`; `sim.sh` → `python -m simorgh run` at cutover.
- Config constants (`DEFAULT_DAILY_BUDGET_USD`, `DEFAULT_CLAUDE_CODE_MAX_CALLS`, `CLAUDE_CODE_WINDOW_SECONDS`, `DEFAULT_VITALS_IDLE_SECONDS`, `HISTORY_LENGTH`, …) → `simorgh.toml` sections owned by the respective subsystems; the Kernel only loads and routes them.
- v1 tests: `tests/test_autonomy.py` timing cases → `tests/simorgh/kernel/test_scheduler.py`; `tests/test_reminders.py` → `test_scheduler.py`; `tests/test_e2e_cli.py::TestSelfCheckFlag` → `test_selfcheck.py`.

## 12. Open questions

1. **Schedule message types are missing from the `03` catalog** (`system.schedule.add/added/cancel`). *Default:* add them under `system.*` in Phase 0 (flagged to the parent).
2. **`Context` fields.** `03` §6 lists `bus, ledger, config, secrets, clock, logger, data_dir`; this spec adds `name, instance_id, mode, run_id`. *Default:* extend the contracts `Context` (flagged).
3. **Scoped pause (`scope:"autonomous"`)** to preserve v1's `autonomous off` semantics is not in the `system.pause` payload. *Default:* add optional `scope: all|autonomous` (flagged); Guardian honors it.
4. **Auto-resume after an auto-pause** (Ledger/Guardian recovered): resume automatically or require a human? *Default:* auto-resume only if the pause was auto and the outage < 10 min; otherwise require `system.resume`.
5. **Where does `/status` HTTP live?** `02` §7 says "Kernel exposes … local HTTP /status (Interface)". *Default:* Kernel answers `system.status.request`; Interface serves HTTP/CLI — the Kernel has no network listener.
