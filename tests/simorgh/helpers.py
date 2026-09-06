"""Shared test helpers for the v2 suite (docs/blueprint/05 section 5):
a controllable clock, a message builder that fills a valid payload for
any catalog type, and `assert_valid`. No test in `tests/simorgh/` may
touch the network or a real LLM; these fakes are how."""

from __future__ import annotations

import asyncio
from typing import Any

from simorgh.contracts import Message, get_spec, validate
from simorgh.contracts.fields import Field, Node


class FakeClock:
    """A `Clock` whose time only moves when a test says so."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    async def sleep(self, seconds: float) -> None:
        self._now += seconds
        await asyncio.sleep(0)

    # `Message.new(clock=...)` takes a plain callable
    def __call__(self) -> float:
        return self._now


def example_value(node: Node) -> Any:
    """A value satisfying `node`'s schema -- the smallest sensible one."""
    if node.kind == "string":
        return "x"
    if node.kind == "integer":
        return 1
    if node.kind == "number":
        return 1.5
    if node.kind == "boolean":
        return True
    if node.kind == "any":
        return {"k": "v"}
    if node.kind == "enum":
        return node.enum[0]
    if node.kind == "list":
        return [example_value(node.item)] if node.item is not None else []
    if node.kind == "nullable":
        return None
    if node.kind == "object":
        return example_payload(node.props)
    raise ValueError(node.kind)


def example_payload(fields: tuple[Field, ...], *, include_optional: bool = False) -> dict:
    out = {}
    for f in fields:
        if f.required or include_optional:
            out[f.name] = example_value(f.node)
    return out


def make_message(type_name: str, *, source: str = "test", include_optional: bool = False,
                 clock: FakeClock | None = None, **routing: Any) -> Message:
    """A valid message of `type_name` with an example payload; replies get
    a correlation_id automatically so `validate()` passes."""
    spec = get_spec(type_name)
    payload = routing.pop("payload", None)
    if payload is None:
        payload = example_payload(spec.fields, include_optional=include_optional)
        if spec.is_reply:  # the auto-added ok/error are optional; drop them from examples
            payload.pop("ok", None)
            payload.pop("error", None)
    if spec.is_reply:
        routing.setdefault("correlation_id", "req-1")
    if clock is not None:
        routing.setdefault("clock", clock)
    return Message.new(type_name, source=source, payload=payload, **routing)


def assert_valid(message: Message) -> Message:
    return validate(message)
