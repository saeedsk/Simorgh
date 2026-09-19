"""A Ledger client bound to the subsystem that holds it (stage 1 item 8).

Every subsystem's Context used to carry the one shared `LedgerClient`, so
any subsystem could append to any stream: Reflection could write
`self:model`, a tool could write `action:*`. The bus has had a topology
policy since the start; the decision log had none (evaluation B7).

`BoundLedger` wraps the shared client for one source. Reads pass through.
Writes (`append`, `snapshot`, `compact`, `delete_stream`) are checked
against `contracts.streamnames.WRITERS`: a stream whose prefix names its
writers may be written only by them. A refused write raises
`WriterViolation` -- like a bus `PolicyViolation`, a programming error,
never a runtime condition to handle.
"""

from __future__ import annotations

import os
from typing import Any

from simorgh.contracts.streamnames import writers_for


class WriterViolation(PermissionError):
    pass


class BoundLedger:
    def __init__(self, inner: Any, source: str) -> None:
        self._inner = inner
        self._source = source.split("@", 1)[0]
        self._audit = os.environ.get("SIMORGH_LEDGER_WRITER_AUDIT", "")

    @property
    def source(self) -> str:
        return self._source

    def _check(self, stream: str) -> None:
        if self._audit:
            with open(self._audit, "a") as fh:
                fh.write(f"{self._source}\t{stream}\n")
        allowed = writers_for(stream)
        if allowed is not None and self._source not in allowed:
            raise WriterViolation(f"{self._source} may not write {stream!r} (writers: {', '.join(sorted(allowed))})")

    async def append(self, stream: str, event, **kw):
        self._check(stream)
        return await self._inner.append(stream, event, **kw)

    async def snapshot(self, stream: str, state: dict, at_seq: int) -> None:
        self._check(stream)
        return await self._inner.snapshot(stream, state, at_seq)

    async def compact(self, stream: str, **kw):
        self._check(stream)
        return await self._inner.compact(stream, **kw)

    async def delete_stream(self, stream: str) -> None:
        self._check(stream)
        return await self._inner.delete_stream(stream)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


__all__ = ["BoundLedger", "WriterViolation"]
