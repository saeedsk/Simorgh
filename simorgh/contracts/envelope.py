"""The message envelope (docs/blueprint/03-contracts-and-messaging.md
section 2) and the Ledger `Event` shape (section 6), plus canonical
JSON so hashes are stable across every backend.

Validation runs at publish time in the producer's process (section 9):
a malformed message fails where it was written, not where it was read.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable

from .registry import ContractError, get_spec
from .topics import PREEMPT_PRIORITY, is_reply

CATALOG_VERSION = 1
_PARTITION_KEY = re.compile(r"^[A-Za-z0-9_.-]+:[A-Za-z0-9_.@-]+$")

ClockFn = Callable[[], float]


def canonical_json(obj: Any) -> str:
    """Sorted keys, compact separators, UTF-8 (no ASCII escaping), no
    NaN/Infinity. Deterministic across processes and backends."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _assert_no_nan(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        raise ContractError(f"{path}: NaN/Infinity is not representable in canonical JSON")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _assert_no_nan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_nan(v, f"{path}[{i}]")


@dataclass(frozen=True)
class Message:
    id: str
    type: str
    schema_version: int
    ts: float
    source: str
    trace_id: str
    causation_id: str | None
    correlation_id: str | None
    partition_key: str | None
    priority: int = 5
    ttl_seconds: float | None = None
    reply_to: str | None = None
    idempotency_key: str | None = None
    payload: dict = field(default_factory=dict)

    # --- construction -----------------------------------------------------
    @classmethod
    def new(
        cls,
        type: str,
        *,
        source: str,
        payload: dict | None = None,
        trace_id: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        partition_key: str | None = None,
        priority: int | None = None,
        ttl_seconds: float | None = None,
        reply_to: str | None = None,
        idempotency_key: str | None = None,
        schema_version: int | None = None,
        ts: float | None = None,
        clock: ClockFn | None = None,
    ) -> "Message":
        """Build a message with a fresh uuid4 id and a producer timestamp
        from `clock` (default: `time.time`). `priority` defaults to 9 for
        preempting control types and 5 otherwise. Does not validate --
        call `validate()` (the Bus does, on publish)."""
        spec = get_spec(type)
        if priority is None:
            from .topics import PREEMPTING_TYPES  # local: avoid import-order coupling

            priority = PREEMPT_PRIORITY if type in PREEMPTING_TYPES else 5
        now = ts if ts is not None else (clock or time.time)()
        return cls(
            id=str(uuid.uuid4()),
            type=type,
            schema_version=schema_version if schema_version is not None else spec.version,
            ts=float(now),
            source=source,
            trace_id=trace_id or str(uuid.uuid4()),
            causation_id=causation_id,
            correlation_id=correlation_id,
            partition_key=partition_key,
            priority=priority,
            ttl_seconds=ttl_seconds,
            reply_to=reply_to,
            idempotency_key=idempotency_key,
            payload=dict(payload or {}),
        )

    def reply(self, type: str, payload: dict, *, source: str, clock: ClockFn | None = None) -> "Message":
        """A reply to this message: same trace, caused by this message,
        correlated to this message's id, on the same partition."""
        return Message.new(
            type,
            source=source,
            payload=payload,
            trace_id=self.trace_id,
            causation_id=self.id,
            correlation_id=self.id,
            partition_key=self.partition_key,
            clock=clock,
        )

    def caused(self, type: str, payload: dict, *, source: str, **routing: Any) -> "Message":
        """A follow-on message in the same trace, caused by this one."""
        routing.setdefault("partition_key", self.partition_key)
        return Message.new(type, source=source, payload=payload, trace_id=self.trace_id,
                           causation_id=self.id, **routing)

    def with_(self, **changes: Any) -> "Message":
        return replace(self, **changes)

    # --- serialization ----------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        _assert_no_nan(self.payload, "$.payload")
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        try:
            return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
        except TypeError as exc:
            raise ContractError(f"bad envelope: {exc}") from None

    @classmethod
    def from_json(cls, text: str) -> "Message":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContractError(f"bad JSON: {exc}") from None
        if not isinstance(data, dict):
            raise ContractError("envelope must be a JSON object")
        return cls.from_dict(data)

    def sha256(self) -> str:
        import hashlib

        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def validate(message: Message) -> Message:
    """Enforce every invariant from section 2. Returns the message so it
    can be used inline (`await bus.publish(validate(m))`). Raises
    ContractError with every problem found, not just the first."""
    errors: list[str] = []
    try:
        spec = get_spec(message.type)
    except ContractError as exc:
        raise ContractError(str(exc)) from None
    if message.schema_version != spec.version:
        errors.append(f"schema_version {message.schema_version} != catalog {spec.version} for {message.type}")
    if not isinstance(message.payload, dict):
        errors.append("payload must be an object")
    else:
        errors.extend(spec.validate(message.payload))
    if not isinstance(message.priority, int) or isinstance(message.priority, bool) or not 0 <= message.priority <= 9:
        errors.append(f"priority {message.priority!r} not in 0..9")
    if message.partition_key is not None and not _PARTITION_KEY.match(message.partition_key):
        errors.append(f"partition_key {message.partition_key!r} must have the form <kind>:<id>")
    if isinstance(message.priority, int) and message.priority >= PREEMPT_PRIORITY and message.partition_key is not None:
        errors.append("a preempting (priority >= 9) message must not set partition_key")
    if is_reply(message.type) and not message.correlation_id:
        errors.append(f"reply type {message.type} requires correlation_id")
    for name in ("id", "source", "trace_id"):
        if not getattr(message, name):
            errors.append(f"{name} is required")
    if message.ttl_seconds is not None and message.ttl_seconds <= 0:
        errors.append("ttl_seconds must be > 0 when set")
    try:
        _assert_no_nan(message.payload, "$.payload")
    except ContractError as exc:
        errors.append(str(exc))
    if errors:
        raise ContractError(f"{message.type} ({message.id}): " + "; ".join(errors))
    return message


@dataclass(frozen=True)
class Event:
    """A Ledger record: the message minus routing fields (section 6).
    `seq` is assigned by the Ledger on append (0 before)."""

    stream: str
    type: str
    ts: float
    trace_id: str
    causation_id: str | None
    payload: dict
    seq: int = 0
    idempotency_key: str | None = None

    @classmethod
    def from_message(cls, message: Message, stream: str) -> "Event":
        return cls(
            stream=stream,
            type=message.type,
            ts=message.ts,
            trace_id=message.trace_id,
            causation_id=message.causation_id,
            payload=dict(message.payload),
            idempotency_key=message.idempotency_key or message.id,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        try:
            return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
        except TypeError as exc:
            raise ContractError(f"bad event: {exc}") from None


__all__ = ["CATALOG_VERSION", "ContractError", "Event", "Message", "canonical_json", "validate"]
