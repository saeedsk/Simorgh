"""Internal interfaces of the Kernel (docs/blueprint/subsystems/03-kernel.md
section 3.4/5). The Kernel is the composition root -- the one package
`02-system-architecture.md` section 4 rule 4 permits to import every
subsystem's `Service` -- but that import happens only in `registry.py`;
every other module here depends on nothing but `simorgh.contracts`,
`simorgh.bus.client`/`api`, `simorgh.ledger.client`/`api`, and stdlib,
exactly like any other subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from simorgh.contracts.protocols import Bus, Clock, Context, Health, Ledger, Logger, Subsystem


class MissingSecret(RuntimeError):
    """A subsystem asked for a secret it was not scoped to, or that was
    never configured. Raised at `require()` time, never silently None."""


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def require(self, name: str) -> str: ...


@dataclass(frozen=True)
class RuntimeConfig:
    """`[runtime]` (docs/blueprint/subsystems/03-kernel.md section 3.5)."""

    mode: str = "single"  # single | local-multi | aws
    data_dir: Path = field(default_factory=lambda: Path("~/.simorgh").expanduser())
    deployment: str = "local"
    subsystems: tuple[str, ...] = ("all",)  # "all" minus `disabled`, or an explicit list
    disabled: tuple[str, ...] = ()
    idle_threshold_s: float = 10.0
    idle_tick_cooldown_s: float = 3.0
    sleep_every_s: float = 6 * 3600
    metrics_every_s: float = 10.0
    health_every_s: float = 5.0
    supervisor_backoff_s: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0)
    supervisor_max_restarts_per_10m: int = 5
    stop_grace_s: float = 15.0
    allow_backend_fallback: bool = False
    log_level: str = "info"
    log_to_ledger: bool = True
    schedule_max_duration_s: float = 86400.0
    schedule_persist: bool = True


# `Context` (simorgh.contracts.protocols) is already exactly what a
# `Service.start()` receives -- `bus, ledger, config, secrets, clock,
# logger, data_dir, name, instance_id, mode, run_id, subsystem_token`.
# `KernelContext` is a plain alias so kernel modules have a name for "the
# thing this package constructs," without a frozen-dataclass subclass
# fighting the parent's own `frozen=True`.
KernelContext = Context


@dataclass
class Supervised:
    """What the supervisor tracks per subsystem (mutable -- one instance
    lives for the process lifetime, updated in place)."""

    name: str
    service: Subsystem
    task: Any = None  # asyncio.Task running .start(); None before boot
    status: str = "starting"  # starting | ok | degraded | down | stopped
    restarts: int = 0
    last_health: Health | None = None
    restart_times: list = field(default_factory=list)  # monotonic clock times, for the 10-minute window
    boot_ok: bool = False


__all__ = [
    "KernelContext",
    "MissingSecret",
    "RuntimeConfig",
    "SecretStore",
    "Supervised",
]
