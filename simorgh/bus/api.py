"""Internal interfaces of the Bus (docs/blueprint/subsystems/01-bus.md
section 3.4). Everything a backend implements and everything the public
client depends on lives here, so `memory`, `sqlite`, and `aws` are
interchangeable behind one shape and the client never knows which one
it is talking to.

Other packages must import only `simorgh.bus.client` (boundary rule,
`02` section 4); this module is for the bus itself and its tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus, Subscription  # noqa: F401 -- re-exported for convenience

Handler = Callable[[Message], Awaitable[None]]


class PolicyViolation(Exception):
    """A reserved-topology rule refused a subscribe or publish."""


class BusTimeout(TimeoutError):
    """`request()` got no reply within its timeout."""


class BusClosed(RuntimeError):
    """A non-`system.*` publish arrived while the bus is stopping."""


class BusUnavailable(RuntimeError):
    """The backend could not accept work after retries (sqlite locked,
    AWS API errors). Subsystems treat this as transient and nack."""


class BackendUnavailable(RuntimeError):
    """A configured backend cannot be constructed (e.g. `aws` without
    boto3). Raised at config time with a clear message, never lazily."""


@dataclass(frozen=True)
class SubscriptionSpec:
    pattern: str  # "task.*", "action.#", "#", or an exact "_inbox.<source>.<uuid>"
    group: str | None  # None = broadcast copy per subscription; str = competing consumers
    durable: bool  # persisted in sqlite/aws; ignored by memory
    source: str  # subscribing subsystem name (policy + metrics)
    max_inflight: int = 16  # per-subscription concurrency cap (partitions still serialized)
    max_handler_seconds: float | None = None  # per-handler timeout; None = backend default


@dataclass
class Delivery:
    message: Message
    attempt: int  # 1-based
    lease_until: float  # backend-specific visibility deadline
    group: str | None
    subscription_id: str = ""
    delivery_id: str = field(default="")


class BusPolicy(Protocol):
    """Installed by the Kernel; the bus only enforces it."""

    def check_subscribe(self, source: str, pattern: str) -> None: ...  # raise PolicyViolation

    def check_publish(self, source: str, type: str, payload: dict) -> None: ...


DeadLetterHook = Callable[[Delivery, str, str], Awaitable[None]]  # (delivery, reason, last_error)


class BusBackend(Protocol):
    """What memory/sqlite/aws implement. The public Bus (client.py) wraps a
    backend with validation, policy, tracing, metrics, and request/reply."""

    name: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def enqueue(self, message: Message) -> None: ...

    async def register(self, spec: SubscriptionSpec, handler: Handler) -> Subscription: ...

    async def ack(self, delivery: Delivery) -> None: ...

    async def nack(self, delivery: Delivery, *, retry_after: float | None) -> None: ...

    async def depth(self, group: str) -> int: ...

    def set_state(self, state: str) -> None: ...  # running | paused | stopping

    def set_dead_letter_hook(self, hook: DeadLetterHook | None) -> None: ...


@dataclass
class BusSubscription:
    """The concrete `Subscription` every backend hands back."""

    pattern: str
    id: str
    _unsubscribe: Callable[[], Awaitable[None]]

    async def unsubscribe(self) -> None:
        await self._unsubscribe()


__all__ = [
    "BackendUnavailable", "Bus", "BusBackend", "BusClosed", "BusPolicy", "BusSubscription",
    "BusTimeout", "BusUnavailable", "DeadLetterHook", "Delivery", "Handler", "PolicyViolation",
    "Subscription", "SubscriptionSpec",
]
