"""`make_backend(config)` / `make_bus(config, ...)` -- backend selection is
configuration, never code (docs/blueprint/03 section 7). The Kernel
calls `make_backend` once and then `make_client` once per subsystem so
every client shares the one backend."""

from __future__ import annotations

import time
from typing import Any, Callable

from simorgh.contracts.protocols import Ledger

from .api import BackendUnavailable, BusBackend, BusPolicy
from .backends.memory import InMemoryBackend
from .backends.sqlite import SqliteBackend
from .client import BusClient
from .config import Config
from .metrics import Metrics
from .trace import TraceWriter

Clock = Callable[[], float]


def make_backend(config: Config, *, clock: Clock | None = None, session: Any | None = None) -> BusBackend:
    clock = clock or time.time
    if config.backend == "memory":
        return InMemoryBackend(clock=clock, max_deliveries=config.max_deliveries,
                               handler_timeout=config.handler_timeout_seconds, dedupe_window=config.dedupe_window)
    if config.backend == "sqlite":
        return SqliteBackend(config.sqlite.path, clock=clock, max_deliveries=config.max_deliveries,
                             lease_seconds=config.default_lease_seconds, poll_interval_ms=config.sqlite.poll_interval_ms,
                             busy_timeout_ms=config.sqlite.busy_timeout_ms, dedupe_window=config.dedupe_window)
    if config.backend == "aws":
        from .backends.aws import AwsBackend  # lazy: its module guards boto3

        return AwsBackend(clock=clock, region=config.aws.region, topic_prefix=config.aws.topic_prefix,
                          queue_prefix=config.aws.queue_prefix, max_deliveries=config.max_deliveries,
                          wait_time_seconds=config.aws.wait_time_seconds, session=session)
    raise BackendUnavailable(f"unknown bus backend {config.backend!r} (memory | sqlite | aws)")


def make_client(
    backend: BusBackend, *, source: str, config: Config | None = None, ledger: Ledger | None = None,
    clock: Clock | None = None, policy: BusPolicy | None = None, trace: TraceWriter | None = None,
    metrics: Metrics | None = None,
) -> BusClient:
    return BusClient(backend, source=source, config=config, ledger=ledger, clock=clock, policy=policy,
                     trace=trace, metrics=metrics)


def make_bus(config: Config | None = None, *, source: str = "kernel", ledger: Ledger | None = None,
             clock: Clock | None = None, policy: BusPolicy | None = None, session: Any | None = None) -> BusClient:
    """One-call convenience: a backend plus a first client (the Kernel's)."""
    config = config or Config()
    backend = make_backend(config, clock=clock, session=session)
    return make_client(backend, source=source, config=config, ledger=ledger, clock=clock, policy=policy)


__all__ = ["make_backend", "make_bus", "make_client"]
