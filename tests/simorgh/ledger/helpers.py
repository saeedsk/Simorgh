"""Test-only helpers for `tests/simorgh/ledger/` -- kept local rather
than added to the shared `tests/simorgh/helpers.py` (05 section 7: don't
edit another agent's shared files while working in parallel).
"""

from __future__ import annotations

from simorgh.contracts.envelope import Event
from simorgh.ledger.api import Projection


def make_event(
    stream: str,
    *,
    type_: str = "test.event",
    payload: dict | None = None,
    idempotency_key: str | None = None,
    ts: float = 0.0,
    trace_id: str = "trace-1",
) -> Event:
    """An unassigned (`seq=0`) Event ready to `append`."""
    return Event(
        stream=stream, type=type_, ts=ts, trace_id=trace_id, causation_id=None,
        payload=dict(payload or {}), idempotency_key=idempotency_key,
    )


class Counter(Projection):
    """The simplest possible real Projection: counts events folded into
    it. Used to prove rebuild/snapshot/materialize actually work, the
    same way a real subsystem's TaskView or CompetenceTable would."""

    stream_prefix = "task:"

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def apply(self, event: Event) -> None:
        self.count += 1

    def state(self) -> dict:
        return {"count": self.count}

    def load(self, state: dict) -> None:
        self.count = state["count"]  # raises KeyError on a corrupt/empty snapshot -- deliberate


class FakeLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict]] = []

    def debug(self, event: str, **fields) -> None:
        self.records.append(("debug", event, fields))

    def info(self, event: str, **fields) -> None:
        self.records.append(("info", event, fields))

    def warning(self, event: str, **fields) -> None:
        self.records.append(("warning", event, fields))

    def error(self, event: str, **fields) -> None:
        self.records.append(("error", event, fields))


class FakeBus:
    """Just enough of `contracts.protocols.Bus` for a Service under
    test: records every published message."""

    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)

    async def subscribe(self, pattern, handler, *, group=None, durable=False):
        class _Sub:
            async def unsubscribe(self) -> None:
                return None

        return _Sub()

    async def request(self, message, *, timeout):  # pragma: no cover - unused by these tests
        raise NotImplementedError

    async def reply(self, request, *, type, payload) -> None:  # pragma: no cover
        raise NotImplementedError

    async def ack(self, message) -> None:
        return None

    async def nack(self, message, *, retry_after=None) -> None:
        return None


def make_context(*, bus, ledger, clock, name: str = "ledger", data_dir=None):
    from pathlib import Path

    from simorgh.contracts.protocols import Context

    return Context(
        name=name, instance_id="", run_id="run-1", mode="single", bus=bus, ledger=ledger,
        config={}, secrets={}, clock=clock, logger=FakeLogger(), data_dir=data_dir or Path("."),
    )


__all__ = ["Counter", "FakeBus", "FakeLogger", "make_context", "make_event"]
