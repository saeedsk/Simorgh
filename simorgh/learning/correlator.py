"""`action.proposed`->`action.result`/`action.denied` and
`verify.requested`->`verify.result` are plain events, not `request/reply`
pairs (Guardian/Execution/Verification publish independently, on their
own time) -- so a pipeline that needs to *await* one correlates by id
itself. One `Correlator` per id-bearing field, shared by every in-flight
pipeline in this process.
"""

from __future__ import annotations

import asyncio
from typing import Any


class Correlator:
    def __init__(self, *, id_field: str) -> None:
        self._id_field = id_field
        self._pending: dict[str, asyncio.Future] = {}

    def wait_for(self, id_value: str) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[id_value] = fut
        return fut

    def resolve(self, payload: dict[str, Any]) -> bool:
        id_value = payload.get(self._id_field)
        fut = self._pending.pop(id_value, None) if id_value else None
        if fut is None or fut.done():
            return False
        fut.set_result(payload)
        return True

    def cancel_all(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
