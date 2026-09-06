"""The Ledger's in-package interfaces (docs/blueprint/subsystems/02-ledger.md
section 3.4): the backend protocol every storage engine implements, the
`Projection` base derived views are built on, and the error vocabulary.

`Event` is `simorgh.contracts.envelope.Event` -- the contracts package is
the single source of truth for the record shape (03 section 6), so this
module re-exports it rather than declaring a competing one. A record's
identity for dedupe is its `idempotency_key` (`Event.from_message` sets
it to the message id when the producer gave none).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Ledger, Subscription


class LedgerError(Exception):
    """Base class for every Ledger failure."""


class ConflictError(LedgerError):
    """A compare-and-swap append lost: the stream's head was not
    `expected`. Never retried by the Ledger -- the caller decides
    (usually: someone else won)."""

    def __init__(self, stream: str, expected: int, actual: int) -> None:
        super().__init__(f"{stream}: expected head {expected}, actual {actual}")
        self.stream, self.expected, self.actual = stream, expected, actual


class ValidationError(LedgerError):
    """A bad stream name, an oversized inline payload, NaN, or a
    malformed blob ref -- raised in the caller's process, before any
    write."""


class LedgerUnavailable(LedgerError):
    """The backend cannot currently persist (disk full, unwritable,
    lost connection). Callers nack and retry later; the Service reports
    health `down`."""


class BackendUnavailable(LedgerError):
    """A configured backend's optional dependency is absent (e.g. no
    `boto3` for `dynamodb`). Raised at construction time so the Kernel
    refuses to start rather than silently relocating data."""


class BlobNotFound(LedgerError):
    pass


@runtime_checkable
class LedgerBackend(Protocol):
    """What a storage engine provides. `LedgerClient` layers validation,
    idempotency, blob-threshold enforcement, tailing, and projections on
    top, so backends stay small and mechanical."""

    cross_process: bool  # True when other processes may append (tail must poll)

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def head(self, stream: str) -> int: ...

    async def append(self, event: Event, *, expected_seq: int | None) -> int: ...

    async def find_by_idempotency(self, stream: str, key: str) -> int | None: ...

    async def read(self, stream: str, *, from_seq: int, limit: int | None) -> list[Event]: ...

    async def streams(self, prefix: str) -> list[str]: ...

    async def write_snapshot(self, stream: str, state: dict, at_seq: int) -> None: ...

    async def read_snapshot(self, stream: str) -> tuple[dict, int] | None: ...

    async def delete_snapshot(self, stream: str) -> None: ...

    async def truncate_below(self, stream: str, seq: int) -> int: ...

    async def delete_stream(self, stream: str) -> None: ...

    async def put_blob(self, data: bytes, *, content_type: str) -> str: ...

    async def get_blob(self, ref: str) -> bytes: ...

    async def stat(self) -> dict: ...

    async def last_ts(self, stream: str) -> float | None: ...


class Projection:
    """Base for derived views (02-ledger section 4.5). Subclass in the
    owning subsystem; override `apply`, `state`, `load`. The Ledger
    client's `rebuild()`/`materialize()` handle snapshot + replay, and
    `applied_seq` tracks how far the view has been folded so a live
    `tail` can continue from exactly there."""

    stream_prefix: str = ""
    snapshot_every: int = 200

    def __init__(self) -> None:
        self.applied_seq = 0
        self.snapshot_seq = 0

    def apply(self, event: Event) -> None:  # pragma: no cover - abstract by convention
        raise NotImplementedError

    def state(self) -> dict:  # pragma: no cover - abstract by convention
        raise NotImplementedError

    def load(self, state: dict) -> None:  # pragma: no cover - abstract by convention
        raise NotImplementedError

    def fold(self, event: Event) -> None:
        """`apply` plus bookkeeping; the client calls this, never
        `apply` directly, so `applied_seq` can never drift."""
        if event.seq <= self.applied_seq:
            return  # duplicate delivery (a tail racing a rebuild) -- already folded
        self.apply(event)
        self.applied_seq = event.seq


__all__ = [
    "BackendUnavailable", "BlobNotFound", "ConflictError", "Event", "Ledger", "LedgerBackend",
    "LedgerError", "LedgerUnavailable", "Projection", "Subscription", "ValidationError",
]
