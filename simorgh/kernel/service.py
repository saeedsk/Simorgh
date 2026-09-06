"""`Kernel`: the composition root itself, wired up (docs/blueprint/
subsystems/03-kernel.md section 5.1). Boots config -> secrets -> Ledger
-> Bus(policy) -> layers in order, waiting for each layer's health before
starting the next (so no Worker can ever claim a task before Guardian and
Execution are up); owns the state machine, the scheduler, and the status
server; handles `system.pause/resume/stop`; shuts down in reverse layer
order on `stop`.

Also implements `Subsystem` itself (`name="kernel"`) so its own
lifecycle is symmetric with every other package's, even though the
Kernel is what constructs everyone else -- there is no special case in
`supervisor.py` for "the thing running the supervisor."
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from pathlib import Path

from simorgh.bus.enforcement import IdentityRegistry, ReservedTopologyPolicy
from simorgh.bus.factory import make_backend as make_bus_backend, make_client as make_bus_client
from simorgh.contracts import security, topics
from simorgh.contracts.envelope import Message, validate
from simorgh.contracts.protocols import Health
from simorgh.ledger.factory import make_ledger

from .api import RuntimeConfig
from .config import ConfigError, LoadedConfig
from .context import ContextFactory, make_logger
from .metrics import MetricsHistoryWriter, MetricsTable, ProcessMetricsPublisher, StatusServer
from .registry import NEEDS_HMAC_SECRET, build_factories, known_layers
from .scheduler import Scheduler
from .secrets import SecretStore, build_secret_store
from .state import PAUSED, RUNNING, STOPPED, STOPPING, SystemStateMachine

VERSION = "0.1.0"


class KernelBootError(RuntimeError):
    pass


def _bus_config_for(config: LoadedConfig, runtime: RuntimeConfig):
    """Shared by `Kernel` and `WorkerKernel` so both processes derive the
    same `${data_dir}` -> sqlite path expansion (`bus.config.Config.
    from_mapping`'s own docstring) from the *same* `simorgh.toml`/env --
    the one thing that makes `local-multi` a config change, not a code
    change (`bus/backends/sqlite.py`'s module docstring)."""
    from simorgh.bus.config import Config as BusConfig

    return BusConfig.from_mapping(config.section("bus"), data_dir=str(runtime.data_dir))


def _ledger_mapping_for(config: LoadedConfig, runtime: RuntimeConfig) -> dict:
    section = dict(config.section("ledger"))
    section.setdefault("data_dir", str(runtime.data_dir / "ledger"))
    section.setdefault("allow_fallback", runtime.allow_backend_fallback)
    return section


def _require_cross_process_backends(config: LoadedConfig, runtime: RuntimeConfig) -> None:
    """`local-multi`'s entire premise is one shared backend every process
    on the host opens (02-system-architecture.md section 6's deployment
    table: "one WAL file"). `memory` is an in-process Python structure a
    second process cannot see at all -- a worker configured against it
    would just poll forever and silently never see a single message, the
    quietest possible failure mode. Fail loud at boot instead."""
    if runtime.mode != "local-multi":
        return
    bus_backend = _bus_config_for(config, runtime).backend
    if bus_backend == "memory":
        raise ConfigError(
            "[runtime] mode = \"local-multi\" requires a cross-process [bus] backend "
            f"(sqlite recommended -- 02-system-architecture.md section 6), not {bus_backend!r}"
        )
    from simorgh.ledger.config import Config as LedgerConfig

    ledger_backend = LedgerConfig.from_mapping(_ledger_mapping_for(config, runtime)).backend
    if ledger_backend == "memory":
        raise ConfigError(
            "[runtime] mode = \"local-multi\" requires a cross-process [ledger] backend "
            f"(sqlite or jsonl -- 02-ledger.md section 4.3), not {ledger_backend!r}"
        )


class Kernel:
    name = "kernel"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.SYSTEM_PAUSE, topics.SYSTEM_RESUME, topics.SYSTEM_STOP, topics.SYSTEM_STATUS_REQUEST,
        topics.SYSTEM_HEALTH, topics.SYSTEM_METRICS, topics.PERCEPT_TEXT_RECEIVED,
        topics.SYSTEM_SCHEDULE_ADD, topics.SYSTEM_SCHEDULE_CANCEL,
    )
    produces: tuple[str, ...] = (
        topics.SYSTEM_STARTED, topics.SYSTEM_STATE_CHANGED, topics.SYSTEM_TICK_SECOND,
        topics.SYSTEM_TICK_IDLE, topics.SYSTEM_TICK_SLEEP, topics.PERCEPT_TIME_SCHEDULED,
        topics.SYSTEM_HEALTH, topics.SYSTEM_METRICS, topics.SYSTEM_STATUS_REPLY,
        topics.SYSTEM_SCHEDULE_ADDED,
    )

    def __init__(
        self, config: LoadedConfig, *, secrets: SecretStore | None = None, clock=None, interactive: bool = False,
    ) -> None:
        self.config = config
        self.runtime: RuntimeConfig = config.runtime
        self._interactive = interactive
        self.run_id = uuid.uuid4().hex[:12]
        self._clock = clock or _WallClock()
        self.state = SystemStateMachine()
        self._secrets = secrets or build_secret_store(config, self.runtime.data_dir)
        self._hmac_secret = security.new_run_secret()
        self._boot_time = self._clock.now()
        self._stop_event = asyncio.Event()
        self._supervisor = None
        self._scheduler: Scheduler | None = None
        self._status: StatusServer | None = None
        self._metrics_table = MetricsTable()
        self._process_metrics: ProcessMetricsPublisher | None = None
        self._metrics_history: MetricsHistoryWriter | None = None
        self._subs = []
        self._bus_backend = None
        self.ledger = None
        self.bus = None  # the Kernel's own BusClient

    async def boot(self) -> None:
        from .supervisor import BootFailed, BootTimeout, Supervisor

        _require_cross_process_backends(self.config, self.runtime)
        self.runtime.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = make_ledger(self._ledger_mapping(), clock=self._clock)
        await self.ledger.start()

        # Reuses the same per-run secret for subsystem-identity tokens
        # (multi-process modes) as for approval tokens: both are HMAC
        # outputs, and deriving one secret from HMAC(secret, ...) outputs
        # is computationally infeasible (HMAC is a PRF) -- not a
        # vulnerability, just not textbook key separation. Worth two
        # independent secrets if `local-multi`/`aws` harden further.
        identities = IdentityRegistry(self._hmac_secret, self.run_id) if self.runtime.mode != "single" else None
        policy = ReservedTopologyPolicy(identities)
        self._bus_backend = make_bus_backend(self._bus_config(), clock=self._clock.now)
        await self._bus_backend.start()
        if identities is not None:
            # The Kernel's own client is built directly (not through
            # `ContextFactory.build`, which self-authenticates every other
            # subsystem) -- it needs the same treatment or its first
            # publish/subscribe below raises `PolicyViolation`.
            policy.authenticate("kernel", identities.issue("kernel"))
        self.bus = make_bus_client(self._bus_backend, source="kernel", ledger=self.ledger, clock=self._clock.now,
                                   policy=policy)

        factories = build_factories(bus_client=self.bus, ledger_client=self.ledger, run_repl=self._interactive)
        ctx_factory = ContextFactory(
            bus_backend=self._bus_backend, ledger=self.ledger, config=self.config, secrets=self._secrets,
            clock=self._clock, runtime=self.runtime, run_id=self.run_id, hmac_secret=self._hmac_secret,
            needs_hmac_secret=NEEDS_HMAC_SECRET, bus_policy=policy, identity_registry=identities,
        )
        self._supervisor = Supervisor(
            clock=self._clock, logger=make_logger("kernel"), backoff_s=self.runtime.supervisor_backoff_s,
            max_restarts_per_window=self.runtime.supervisor_max_restarts_per_10m,
            on_critical_down=self._on_critical_down,
        )
        started: list[tuple[str, ...]] = []
        try:
            for layer in self._own_layers(factories):
                if not layer:
                    continue
                await self._supervisor.start_layer(layer, lambda name: ctx_factory.build(name), factories)
                started.append(layer)
        except (BootFailed, BootTimeout) as exc:
            await self._append_state(self.state.boot_failed(str(exc)))
            raise KernelBootError(str(exc)) from exc

        self._scheduler = Scheduler(
            bus=self.bus, ledger=self.ledger, clock=self._clock, logger=make_logger("kernel"),
            idle_threshold_s=self.runtime.idle_threshold_s, idle_tick_cooldown_s=self.runtime.idle_tick_cooldown_s,
            sleep_every_s=self.runtime.sleep_every_s, max_schedule_duration_s=self.runtime.schedule_max_duration_s,
            is_running=lambda: self.state.state == RUNNING,
        )
        await self._scheduler.start()
        self._status = StatusServer(
            bus=self.bus, clock=self._clock, run_id=self.run_id, mode=self.runtime.mode, state=self.state,
            supervisor=self._supervisor, metrics=self._metrics_table, boot_time=self._boot_time,
        )
        await self._status.start()
        # Observe-tier additions (02-system-architecture.md section 6.2):
        # process resource gauges and a low-frequency metrics-history
        # snapshot, both on `metrics_every_s` -- a `[runtime]` knob that
        # already existed (read into `RuntimeConfig`/`load_runtime_config`)
        # but had no consumer until now.
        self._process_metrics = ProcessMetricsPublisher(
            bus=self.bus, clock=self._clock, interval_s=self.runtime.metrics_every_s,
        )
        await self._process_metrics.start()
        self._metrics_history = MetricsHistoryWriter(
            ledger=self.ledger, clock=self._clock, metrics=self._metrics_table,
            interval_s=self.runtime.metrics_every_s,
        )
        await self._metrics_history.start()
        self._subs.append(await self.bus.subscribe(topics.SYSTEM_PAUSE, self._on_pause))
        self._subs.append(await self.bus.subscribe(topics.SYSTEM_RESUME, self._on_resume))
        self._subs.append(await self.bus.subscribe(topics.SYSTEM_STOP, self._on_stop))

        change = self.state.boot_complete()
        await self._append_state(change)
        await self.bus.publish(validate(Message.new(
            topics.SYSTEM_STARTED, source="kernel",
            payload={"mode": self.runtime.mode, "subsystems": self._subsystem_versions(),
                     "data_dir": str(self.runtime.data_dir)},
            clock=self._clock.now,
        )))
        await self.bus.publish(validate(Message.new(
            topics.SYSTEM_STATE_CHANGED, source="kernel", payload={"state": RUNNING}, clock=self._clock.now,
        )))

    def _subsystem_versions(self) -> list[str]:
        return [f"{s.name}@{getattr(s.service, 'version', '0')}" for s in self._supervisor.services.values()]

    def _own_layers(self, factories: dict) -> tuple[tuple[str, ...], ...]:
        """`registry.LAYERS`, filtered to what `factories` can build (as
        `known_layers` already does) and, in `local-multi` mode, further
        filtered to exclude `orchestration` (03-kernel.md section 5.6):
        `simorgh run` boots every subsystem *except* orchestration, whose
        Workers instead run as separate `simorgh worker --id wN` processes
        (`WorkerKernel`, below). `aws` mode is untouched here -- its
        process topology is a different track's concern."""
        layers = known_layers(factories)
        if self.runtime.mode == "local-multi":
            layers = tuple(tuple(name for name in layer if name != "orchestration") for layer in layers)
        return layers

    def _bus_config(self):
        return _bus_config_for(self.config, self.runtime)

    def _ledger_mapping(self) -> dict:
        return _ledger_mapping_for(self.config, self.runtime)

    async def _append_state(self, change) -> None:
        from simorgh.contracts.envelope import Event

        await self.ledger.append("system", Event(
            stream="system", type="system.state", ts=self._clock.now(), trace_id=str(uuid.uuid4()),
            causation_id=None, payload={"state": change.state, "previous": change.previous,
                                        "reason": change.reason, "requested_by": change.requested_by,
                                        "scope": change.scope},
        ))

    async def _on_pause(self, message: Message) -> None:
        change = self.state.pause(reason=message.payload["reason"], requested_by=message.payload["requested_by"],
                                  scope=message.payload.get("scope"))
        if change is None:
            return
        await self._append_state(change)
        await self.bus.publish(validate(Message.new(
            topics.SYSTEM_STATE_CHANGED, source="kernel",
            payload={"state": self.state.state, "reason": change.reason}, clock=self._clock.now,
        )))

    async def _on_resume(self, message: Message) -> None:
        change = self.state.resume(reason=message.payload["reason"], requested_by=message.payload["requested_by"],
                                   scope=message.payload.get("scope"))
        if change is None:
            return
        await self._append_state(change)
        await self.bus.publish(validate(Message.new(
            topics.SYSTEM_STATE_CHANGED, source="kernel",
            payload={"state": self.state.state, "reason": change.reason}, clock=self._clock.now,
        )))

    async def _on_stop(self, message: Message) -> None:
        change = self.state.stop(reason=message.payload["reason"], requested_by=message.payload["requested_by"])
        await self._append_state(change)
        await self.bus.publish(validate(Message.new(
            topics.SYSTEM_STATE_CHANGED, source="kernel", payload={"state": STOPPING}, clock=self._clock.now,
        )))
        self._stop_event.set()

    async def _on_critical_down(self, name: str) -> None:
        if self.state.state == RUNNING:
            change = self.state.pause(reason=f"{name} is down", requested_by="kernel")
            if change is not None:
                await self._append_state(change)
                await self.bus.publish(validate(Message.new(
                    topics.SYSTEM_HEALTH, source="kernel",
                    payload={"subsystem": "kernel", "status": "degraded",
                            "detail": f"{name} down -- system paused"},
                    clock=self._clock.now,
                )))

    async def wait_for_stop(self) -> None:
        await self._stop_event.wait()

    async def shutdown(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        if self._process_metrics is not None:
            await self._process_metrics.stop()
        if self._metrics_history is not None:
            await self._metrics_history.stop()
        if self._status is not None:
            await self._status.stop()
        if self._scheduler is not None:
            await self._scheduler.stop()
        # Append the final `stopped` state *before* `stop_all` below tears
        # down the "ledger" layer -- `ledger.service.Service.stop()`
        # closes the very backend connection `_append_state` needs
        # (`ledger`/`bus` are ordinary layers here too, stopped last by
        # `stop_all`'s `reversed()`). With a backend that actually enforces
        # "not started" once closed (`sqlite`; `memory`/`jsonl` happened
        # to tolerate the stale order silently), appending afterward raised
        # `LedgerUnavailable` on every clean shutdown -- reproducible in
        # plain `single` mode with `[ledger] backend = "sqlite"`, not
        # something `local-multi` introduced.
        change = self.state.stopped()
        await self._append_state(change)
        if self._supervisor is not None:
            await self._supervisor.stop_all(list(reversed(known_layers(
                build_factories(bus_client=self.bus, ledger_client=self.ledger)))), grace_s=self.runtime.stop_grace_s)
        if self._bus_backend is not None:
            await self._bus_backend.stop()
        if self.ledger is not None:
            await self.ledger.stop()

    async def health(self) -> Health:
        if self._supervisor is None:
            return Health.down("not booted")
        down = [s.name for s in self._supervisor.services.values() if s.status == "down"]
        if down:
            return Health.degraded(f"down: {', '.join(down)}")
        return Health.ok()

    def status_snapshot(self) -> dict:
        return self._status.snapshot() if self._status is not None else {}


class WorkerKernel:
    """`local-multi` mode's `simorgh worker --id wN` process
    (docs/blueprint/subsystems/03-kernel.md section 5.6): a standalone
    process holding only Ledger/Bus clients and exactly one `orchestration`
    `Worker`, sharing the cross-process backend(s) (`sqlite` bus, `sqlite`/
    `jsonl` ledger) the main `simorgh run` process -- and every sibling
    worker process -- also opens against the same `simorgh.toml`/`--config`
    (`_bus_config_for`/`_ledger_mapping_for` derive the same `${data_dir}`
    path from it that `Kernel` does).

    It never touches the per-run HMAC *approval* secret: guardian/execution
    keep that (`registry.NEEDS_HMAC_SECRET`), and a Worker only proposes
    actions, it never approves or runs one (16-orchestration.md section 2)
    -- "the secret: workers never need it" (03-kernel.md section 5.6). It
    also never boots any subsystem but `orchestration`; guardian/execution/
    everything else stays in whichever process runs `simorgh run`, reached
    only through the shared bus.

    Its own `IdentityRegistry` still self-issues and self-authenticates a
    subsystem token so `ReservedTopologyPolicy` (built with `identities`
    set, since this only ever runs in a multi-process mode) does not
    refuse this process's own publishes/subscribes -- see `ContextFactory.
    build`. That secret is generated fresh in this process and is *not*,
    and today cannot be, the same secret the main process's own
    `IdentityRegistry` holds: policy is enforced client-side, per process
    (`bus/enforcement.py`'s own docstring already flags this as unfinished
    hardening, not a regression introduced here), so self-consistency
    within this one process is all that is required for it to work.
    """

    name = "kernel-worker"
    version = VERSION

    def __init__(
        self, config: LoadedConfig, *, worker_id: str, secrets: SecretStore | None = None, clock=None,
    ) -> None:
        if config.runtime.mode != "local-multi":
            raise KernelBootError(
                f"a worker process only makes sense under [runtime] mode = \"local-multi\" "
                f"(got {config.runtime.mode!r}); run `simorgh run` for every other mode"
            )
        self.config = config
        self.runtime: RuntimeConfig = config.runtime
        self.worker_id = worker_id
        self._clock = clock or _WallClock()
        self.run_id = uuid.uuid4().hex[:12]
        self._secrets = secrets or build_secret_store(config, self.runtime.data_dir)
        self._stop_event = asyncio.Event()
        self._bus_backend = None
        self.ledger = None
        self.bus = None
        self._service = None
        self._ctx = None

    async def boot(self) -> None:
        from simorgh.orchestration.config import Config as OrchestrationConfig
        from simorgh.orchestration.service import Service as OrchestrationService

        _require_cross_process_backends(self.config, self.runtime)
        self.runtime.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = make_ledger(_ledger_mapping_for(self.config, self.runtime), clock=self._clock)
        await self.ledger.start()

        identities = IdentityRegistry(security.new_run_secret(), self.run_id)
        policy = ReservedTopologyPolicy(identities)
        self._bus_backend = make_bus_backend(_bus_config_for(self.config, self.runtime), clock=self._clock.now)
        await self._bus_backend.start()

        ctx_factory = ContextFactory(
            bus_backend=self._bus_backend, ledger=self.ledger, config=self.config, secrets=self._secrets,
            clock=self._clock, runtime=self.runtime, run_id=self.run_id, hmac_secret=b"",
            needs_hmac_secret=frozenset(), bus_policy=policy, identity_registry=identities,
        )
        self._ctx = ctx_factory.build("orchestration", instance_id=self.worker_id)
        self.bus = self._ctx.bus

        orch_config = OrchestrationConfig.from_mapping(self.config.section("orchestration"))
        # One process is exactly one Worker, regardless of what
        # `[orchestration] workers` says -- that key still governs how
        # many Workers a `single`-mode Kernel starts in-process.
        self._service = OrchestrationService(dataclasses.replace(orch_config, workers=1))
        try:
            await self._service.start(self._ctx)
        except Exception as exc:  # noqa: BLE001 -- name the failure, mirroring Kernel.boot's BootFailed handling
            raise KernelBootError(f"worker {self.worker_id!r} failed to start: {exc!r}") from exc

    def request_stop(self) -> None:
        self._stop_event.set()

    async def wait_for_stop(self) -> None:
        await self._stop_event.wait()

    async def shutdown(self) -> None:
        if self._service is not None:
            await self._service.stop()
            self._service = None
        if self._bus_backend is not None:
            await self._bus_backend.stop()
            self._bus_backend = None
        if self.ledger is not None:
            await self.ledger.stop()
            self.ledger = None

    async def health(self) -> Health:
        if self._service is None:
            return Health.down("not booted")
        return await self._service.health()


class _WallClock:
    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


__all__ = ["Kernel", "KernelBootError", "VERSION", "WorkerKernel"]
