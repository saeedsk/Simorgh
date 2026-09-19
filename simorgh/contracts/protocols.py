"""The interfaces every subsystem is written against (docs/blueprint/03
section 6). Structural (`typing.Protocol`), so a backend or a test fake
conforms by shape, never by inheritance -- and a subsystem never imports
a concrete Bus or Ledger class, only these.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncContextManager, AsyncIterator, Awaitable, Callable, Mapping, Protocol, runtime_checkable

from .envelope import Event, Message

Handler = Callable[[Message], Awaitable[None]]
EventHandler = Callable[[Event], Awaitable[None]]


@runtime_checkable
class Subscription(Protocol):
    pattern: str

    async def unsubscribe(self) -> None: ...


@runtime_checkable
class Clock(Protocol):
    """Injectable time, so tests control it (05 section 2)."""

    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


@runtime_checkable
class Bus(Protocol):
    async def publish(self, message: Message) -> None: ...

    async def subscribe(
        self, pattern: str, handler: Handler, *, group: str | None = None, durable: bool = False
    ) -> Subscription: ...

    async def request(self, message: Message, *, timeout: float) -> Message: ...

    async def reply(self, request: Message, *, type: str, payload: dict) -> None: ...

    async def ack(self, message: Message) -> None: ...

    async def nack(self, message: Message, *, retry_after: float | None = None) -> None: ...


@runtime_checkable
class Ledger(Protocol):
    async def append(self, stream: str, event: Event, *, expected_seq: int | None = None) -> int: ...

    async def read(self, stream: str, *, from_seq: int = 0, limit: int | None = None) -> list[Event]: ...

    async def tail(self, stream: str, handler: EventHandler) -> Subscription: ...

    async def snapshot(self, stream: str, state: dict, at_seq: int) -> None: ...

    async def load_snapshot(self, stream: str) -> tuple[dict, int] | None: ...

    async def streams(self, prefix: str) -> list[str]: ...

    async def put_blob(self, data: bytes, *, content_type: str) -> str: ...

    async def get_blob(self, ref: str) -> bytes: ...

    async def compact(self, stream: str, *, before_seq: int, keep_snapshot: bool = True) -> int: ...


class Logger(Protocol):
    def debug(self, event: str, **fields: Any) -> None: ...

    def info(self, event: str, **fields: Any) -> None: ...

    def warning(self, event: str, **fields: Any) -> None: ...

    def error(self, event: str, **fields: Any) -> None: ...


@runtime_checkable
class Span(Protocol):
    """One timed operation inside a trace, as `Telemetry.span` yields it.
    `set` adds an attribute before the span ends (a result size, a rule
    name); the row is written when the span closes."""

    trace_id: str
    span_id: str
    parent_id: str | None
    name: str

    def set(self, key: str, value: Any) -> None: ...


@runtime_checkable
class Telemetry(Protocol):
    """Spans and samples: operational measurements that are not
    decisions, kept out of the ledger (stage 1 item 1). Writes never
    block and never raise into the caller; rows are batched and written
    off the event loop.

    - `span(name, trace_id=..., parent_id=None, attrs=None)` is an async
      context manager. It records start and end on exit with status
      `ok`, `error` when the body raised an `Exception` (re-raised), or
      `cancelled` on cancellation. A span opened inside another span of
      the same trace takes the outer span as its parent unless
      `parent_id` is given.
    - `sample(series, value, ts=None)` records one JSON-able value of a
      named series (a gauge reading, a tick's counters) at `ts`, default
      now.
    - `query(trace_id)` returns every span of the trace, oldest start
      first, as dicts with the table's columns (`attrs` decoded); rows
      still buffered are included.
    """

    def span(
        self, name: str, *, trace_id: str, parent_id: str | None = None,
        attrs: Mapping[str, Any] | None = None,
    ) -> AsyncContextManager[Span]: ...

    def sample(self, series: str, value: Any, ts: float | None = None) -> None: ...

    async def query(self, trace_id: str) -> list[dict]: ...


class NullSpan:
    """The span `NullTelemetry` yields: carries its names, records nothing."""

    def __init__(self, name: str, trace_id: str, parent_id: str | None) -> None:
        self.name = name
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.span_id = ""

    def set(self, key: str, value: Any) -> None:
        return None


class NullTelemetry:
    """A `Telemetry` that records nothing: the default on every `Context`
    built by hand (tests, tools) and what the Kernel hands out when
    `[telemetry] enabled = false`. Exceptions still propagate from a
    span's body; nothing else happens."""

    @asynccontextmanager
    async def span(
        self, name: str, *, trace_id: str, parent_id: str | None = None,
        attrs: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[NullSpan]:
        yield NullSpan(name, trace_id, parent_id)

    def sample(self, series: str, value: Any, ts: float | None = None) -> None:
        return None

    async def query(self, trace_id: str) -> list[dict]:
        return []


NULL_TELEMETRY = NullTelemetry()


@dataclass(frozen=True)
class Health:
    status: str  # ok | degraded | down
    detail: str = ""

    @classmethod
    def ok(cls, detail: str = "") -> "Health":
        return cls("ok", detail)

    @classmethod
    def degraded(cls, detail: str) -> "Health":
        return cls("degraded", detail)

    @classmethod
    def down(cls, detail: str) -> "Health":
        return cls("down", detail)


@dataclass(frozen=True)
class Context:
    """What the Kernel hands a subsystem at `start()`. `secrets` only
    contains what this subsystem declared a need for; `subsystem_token`
    is what its process authenticates to the Bus with in multi-process
    modes (03 section 10)."""

    name: str
    instance_id: str
    run_id: str
    mode: str  # single | local-multi | aws
    bus: Bus
    ledger: Ledger
    config: Mapping[str, Any]
    secrets: Mapping[str, str]
    clock: Clock
    logger: Logger
    data_dir: Path
    subsystem_token: str = ""
    # Spans and samples (stage 1 item 1). The Kernel passes its one
    # store; a Context built by hand records nothing.
    telemetry: Telemetry = NULL_TELEMETRY

    @property
    def source(self) -> str:
        return f"{self.name}@{self.instance_id}" if self.instance_id else self.name


@runtime_checkable
class Subsystem(Protocol):
    name: str
    version: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]

    async def start(self, ctx: Context) -> None: ...

    async def stop(self) -> None: ...

    async def health(self) -> Health: ...


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    # Prompt tokens served from the provider's cache, priced at its own
    # (much lower) rate. Always the part of the prompt NOT counted in
    # `input_tokens`, so the two add up to the whole prompt exactly once.
    cached_input_tokens: int = 0
    cost_usd: float | None = None  # provider-reported, when available
    tool_calls: tuple[dict, ...] = ()
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    async def complete(
        self, messages: list[dict], *, tools: list[dict] | None, max_tokens: int
    ) -> ProviderResponse: ...


@dataclass(frozen=True)
class ToolContext:
    action_id: str
    task_id: str | None
    scope: dict
    constraints: dict
    data_dir: Path
    clock: Clock
    logger: Logger
    ledger: Ledger
    bus: Bus | None = None  # composite tools (drafting loops) may request cognition via the bus
    # The tree this call's paths resolve against, when the task works in
    # its own worktree (execution/worktree.py). None means the live
    # repository, which is every call from a task that has none. Set by
    # Execution from the task id, never from the model's arguments.
    root: Path | None = None


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str = ""
    output_ref: str = ""
    error: str | None = None
    side_effects: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    read_only: bool
    reversibility: str  # read_only | reversible | irreversible
    args_schema: dict

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult: ...


__all__ = [
    "Bus", "Clock", "Context", "EventHandler", "Handler", "Health", "Ledger", "Logger",
    "NULL_TELEMETRY", "NullSpan", "NullTelemetry", "Provider", "ProviderResponse", "Span",
    "Subscription", "Subsystem", "Telemetry", "Tool", "ToolContext", "ToolResult",
]
