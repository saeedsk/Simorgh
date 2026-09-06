"""Subsystem lifecycle: start in dependency order, poll health, restart
crashed services with backoff, and give up (`down`) past a restart
budget (docs/blueprint/subsystems/03-kernel.md sections 5.1/5.3). Guardian
and Execution are special: if either goes `down`, the whole system
auto-pauses (section 5.3, S3) -- "nothing may execute without the safety
path" is enforced here, not hoped for.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from simorgh.contracts.protocols import Clock, Context, Health, Logger, Subsystem

from .api import Supervised

SAFETY_CRITICAL = frozenset({"guardian", "execution"})
_RESTART_WINDOW_S = 600.0  # 10 minutes (section 5.3)


class BootTimeout(RuntimeError):
    pass


class BootFailed(RuntimeError):
    pass


class Supervisor:
    def __init__(
        self,
        *,
        clock: Clock,
        logger: Logger,
        backoff_s: tuple[float, ...],
        max_restarts_per_window: int,
        on_critical_down: Callable[[str], Awaitable[None]] | None = None,
        boot_timeout_s: float = 30.0,
    ) -> None:
        self._clock = clock
        self._logger = logger
        self._backoff = backoff_s or (1.0,)
        self._max_restarts = max_restarts_per_window
        self._on_critical_down = on_critical_down
        self._boot_timeout_s = boot_timeout_s
        self.services: dict[str, Supervised] = {}
        self._health_task: asyncio.Task | None = None

    async def start_layer(self, layer: tuple[str, ...], make_context: Callable[[str], Context],
                          factories: dict[str, Callable[[], Subsystem]]) -> None:
        """Start every service in one layer concurrently, then wait for
        all of them to report healthy (or `boot_ok`-degraded) before
        returning -- the next layer never starts on top of a layer that
        isn't actually up (section 5.1)."""
        starts = []
        for name in layer:
            service = factories[name]()
            supervised = Supervised(name=name, service=service)
            self.services[name] = supervised
            ctx = make_context(name)
            starts.append(self._boot_one(supervised, ctx))
        await asyncio.gather(*starts)

    async def _boot_one(self, supervised: Supervised, ctx: Context) -> None:
        try:
            await asyncio.wait_for(supervised.service.start(ctx), timeout=self._boot_timeout_s)
        except asyncio.TimeoutError as exc:
            raise BootTimeout(f"{supervised.name} did not start within {self._boot_timeout_s}s") from exc
        except Exception as exc:  # noqa: BLE001 -- a boot failure must name the service, not crash the process
            raise BootFailed(f"{supervised.name} failed to start: {exc!r}") from exc
        health = await supervised.service.health()
        supervised.last_health = health
        supervised.boot_ok = health.status in ("ok", "degraded")
        supervised.status = health.status if supervised.boot_ok else "down"
        if not supervised.boot_ok:
            raise BootFailed(f"{supervised.name} reported {health.status}: {health.detail}")
        supervised.task = asyncio.current_task()

    async def poll_once(self) -> list[Supervised]:
        """One health-poll pass. Returns the services whose status
        changed this pass (for the caller to publish `system.health`)."""
        changed = []
        for supervised in self.services.values():
            try:
                health = await supervised.service.health()
            except Exception as exc:  # noqa: BLE001
                health = Health.down(f"health() raised: {exc!r}")
            if supervised.last_health is None or health.status != supervised.last_health.status:
                changed.append(supervised)
            supervised.last_health = health
            if health.status == "down" and supervised.status != "down":
                await self._restart(supervised)
            else:
                supervised.status = health.status
        return changed

    async def _restart(self, supervised: Supervised) -> None:
        now = self._clock.now()
        supervised.restart_times = [t for t in supervised.restart_times if now - t < _RESTART_WINDOW_S]
        if len(supervised.restart_times) >= self._max_restarts:
            supervised.status = "down"
            self._logger.error("kernel.supervisor.down", subsystem=supervised.name,
                              restarts=len(supervised.restart_times))
            if supervised.name in SAFETY_CRITICAL and self._on_critical_down is not None:
                await self._on_critical_down(supervised.name)
            return
        delay = self._backoff[min(supervised.restarts, len(self._backoff) - 1)]
        supervised.restarts += 1
        supervised.restart_times.append(now)
        supervised.status = "degraded"
        self._logger.warning("kernel.supervisor.restart", subsystem=supervised.name,
                            attempt=supervised.restarts, delay_s=delay)
        await self._clock.sleep(delay)
        try:
            await supervised.service.stop()
        except Exception:  # noqa: BLE001 -- best-effort; the service is already unhealthy
            pass
        # The concrete restart (re-`start()`) is driven by the caller
        # (Kernel service loop), which owns the Context and can rebuild
        # one if a subsystem's own state needs a fresh start; this method
        # marks the intent and paces the backoff, since Context
        # construction is subsystem-specific and lives in `context.py`.

    async def stop_all(self, layers_reversed: list[tuple[str, ...]], *, grace_s: float) -> None:
        for layer in layers_reversed:
            stops = [self.services[name].service.stop() for name in layer if name in self.services]
            if not stops:
                continue
            try:
                await asyncio.wait_for(asyncio.gather(*stops, return_exceptions=True), timeout=grace_s)
            except asyncio.TimeoutError:
                self._logger.warning("kernel.stop.grace_exceeded", layer=layer)
            for name in layer:
                if name in self.services:
                    self.services[name].status = "stopped"


__all__ = ["BootFailed", "BootTimeout", "SAFETY_CRITICAL", "Supervisor"]
