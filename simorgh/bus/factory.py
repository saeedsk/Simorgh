"""`make_backend(config)` / `make_bus(config, ...)` -- backend selection is
configuration, never code (docs/blueprint/03 section 7). The Kernel
calls `make_backend` once and then `make_client` once per subsystem so
every client shares the one backend."""

from __future__ import annotations

import sys
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


def default_handler_error(message, exc: BaseException) -> None:
    """Say that a subscriber raised, on stderr, always.

    Both backends have taken an `on_handler_error` hook since they were
    written and NOTHING HAS EVER SET IT. A handler that raises is
    dropped in complete silence, and that silence is the single most
    expensive thing in this codebase's history:

    - a stale-cursor ConflictError in `refresh_lease` meant no project
      ever produced a child task, and it went unfound through three
      rounds of observers (2026-09-08)
    - a Planning handler published through an attribute that does not
      exist; the AttributeError vanished and the handler still looked
      like it worked (2026-09-08)
    - a cancel on a queued task attempted an illegal transition, raised,
      and left the task on the queue with nothing said (observer,
      2026-09-08)

    Every one of those presents as a pipeline that stops partway with no
    error anywhere. Printing is deliberately unconditional and does not
    go through a logger: a subsystem's logger may be exactly what is
    broken, and this is the last line of defence.
    """
    import traceback

    kind = getattr(message, "type", "?")
    print(f"[bus] handler for {kind} raised {type(exc).__name__}: {exc}", file=sys.stderr)
    traceback.print_exception(type(exc), exc, exc.__traceback__, limit=8, file=sys.stderr)


def make_backend(config: Config, *, clock: Clock | None = None, session: Any | None = None,
                 on_handler_error: Callable[[Any, BaseException], None] | None = None) -> BusBackend:
    clock = clock or time.time
    on_handler_error = default_handler_error if on_handler_error is None else on_handler_error
    if config.backend == "memory":
        return InMemoryBackend(clock=clock, max_deliveries=config.max_deliveries,
                               handler_timeout=config.handler_timeout_seconds, dedupe_window=config.dedupe_window,
                               on_handler_error=on_handler_error)
    if config.backend == "sqlite":
        return SqliteBackend(config.sqlite.path, clock=clock, max_deliveries=config.max_deliveries,
                             lease_seconds=config.default_lease_seconds, poll_interval_ms=config.sqlite.poll_interval_ms,
                             busy_timeout_ms=config.sqlite.busy_timeout_ms, dedupe_window=config.dedupe_window,
                             on_handler_error=on_handler_error)
    if config.backend == "aws":
        from .backends.aws import AwsBackend  # lazy: its module guards boto3

        return AwsBackend(clock=clock, region=config.aws.region, topic_prefix=config.aws.topic_prefix,
                          queue_prefix=config.aws.queue_prefix, max_deliveries=config.max_deliveries,
                          wait_time_seconds=config.aws.wait_time_seconds, session=session,
                          on_handler_error=on_handler_error)
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


__all__ = ["default_handler_error", "make_backend", "make_bus", "make_client"]
