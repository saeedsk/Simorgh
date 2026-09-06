"""The interfaces every subsystem is written against (docs/blueprint/03
section 6). Structural (`typing.Protocol`), so a backend or a test fake
conforms by shape, never by inheritance -- and a subsystem never imports
a concrete Bus or Ledger class, only these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable

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
    "Provider", "ProviderResponse", "Subscription", "Subsystem", "Tool", "ToolContext", "ToolResult",
]
