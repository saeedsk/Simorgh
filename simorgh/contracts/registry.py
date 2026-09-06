"""The message-type registry: `define()` turns one field declaration
(`fields.py`) into a frozen dataclass with `to_payload`/`from_payload`,
a JSON Schema, and a catalog entry keyed by type and version.

Why generated dataclasses rather than ~120 hand-written ones: the
catalog and its schemas must agree exactly, forever, across sixteen
independently-built subsystems. Two sources of truth would drift the
first time someone added an optional field to one and forgot the other.
`make_dataclass` from a single declaration makes drift impossible, and
`schemagen` + tests make the checked-in schema files a verified
projection of the same declaration.

Replies (`*.reply` types) automatically admit the error shape from
docs/blueprint/03-contracts-and-messaging.md section 9 --
`{ok: false, error: {code, detail, retryable}}` -- as a second `anyOf`
branch, so a requester can always distinguish "answered" from "failed
to answer" without every reply type re-declaring it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from .fields import Bool, Enum, F, Field, O, Obj, Str, nullable, object_schema
from .validation import ValidationError, validate

ERROR_FIELDS = (F("code", Str), F("detail", Str), F("retryable", Bool))
REPLY_ERROR_FIELDS = (O("ok", Bool), O("error", Obj(*ERROR_FIELDS)))


class ContractError(ValueError):
    """A message violates the catalog (unknown type, bad payload, bad
    envelope). Raised in the *producer's* process at publish time."""


@dataclass(frozen=True)
class MessageSpec:
    type: str
    version: int
    fields: tuple[Field, ...]
    dataclass: type
    schema: dict
    doc: str = ""

    @property
    def is_reply(self) -> bool:
        return self.type.endswith(".reply")

    def validate(self, payload: Any) -> list[str]:
        return validate(payload, self.schema, "$.payload")

    def check(self, payload: Any) -> None:
        errors = self.validate(payload)
        if errors:
            raise ContractError(f"{self.type} v{self.version}: " + "; ".join(errors))

    def build(self, **kwargs: Any) -> Any:
        """Construct the dataclass, validating the resulting payload."""
        instance = self.dataclass(**kwargs)
        self.check(instance.to_payload())
        return instance


_REGISTRY: dict[str, MessageSpec] = {}


def _class_name(type_name: str) -> str:
    return "".join(part.capitalize() for part in type_name.replace("_", ".").split("."))


def _make_dataclass(type_name: str, fields: tuple[Field, ...], doc: str) -> type:
    required = [f for f in fields if f.required]
    optional = [f for f in fields if not f.required]
    spec: list = [(f.name, f.node.py) for f in required]
    spec += [(f.name, f.node.py | None, dataclasses.field(default=None)) for f in optional]
    optional_names = frozenset(f.name for f in optional)

    def to_payload(self) -> dict:
        out = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if value is None and f.name in optional_names:
                continue
            out[f.name] = value
        return out

    def from_payload(cls, payload: dict):
        known = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in payload.items() if k in known}
        try:
            return cls(**kwargs)
        except TypeError as exc:
            raise ContractError(f"{type_name}: {exc}") from None

    namespace = {
        "to_payload": to_payload,
        "from_payload": classmethod(from_payload),
        "__doc__": doc or f"Payload dataclass for `{type_name}`.",
        "TYPE": type_name,
    }
    return dataclasses.make_dataclass(
        _class_name(type_name), spec, frozen=True, namespace=namespace
    )


def define(
    type_name: str,
    fields: list[Field] | tuple[Field, ...] = (),
    *,
    version: int = 1,
    doc: str = "",
    additional: Any = True,
) -> type:
    """Register `type_name` and return its dataclass. Every `messages/`
    module calls this once per type; `topics.CATALOG` must list the same
    types (verified by tests, not trusted)."""
    if type_name in _REGISTRY:
        raise ContractError(f"message type {type_name!r} defined twice")
    fields = tuple(fields)
    if type_name.endswith(".reply"):
        # `ok`/`error` are always admitted on a reply; the success branch
        # keeps the declared required fields, the error branch requires
        # exactly {ok: false, error}.
        fields = fields + REPLY_ERROR_FIELDS
        success = object_schema(fields, additional)
        # A success reply may say ok=true (or omit it) but never ok=false --
        # otherwise a reply type with no required fields would accept a
        # bare {ok: false} on its success branch.
        success["properties"]["ok"] = {"anyOf": [{"const": True}, {"type": "null"}]}
        error = {
            "type": "object",
            "properties": {
                "ok": {"const": False},
                "error": object_schema(ERROR_FIELDS),
            },
            "required": ["ok", "error"],
            "additionalProperties": True,
        }
        schema = {"anyOf": [success, error]}
    else:
        schema = object_schema(fields, additional)
    cls = _make_dataclass(type_name, fields, doc)
    _REGISTRY[type_name] = MessageSpec(type_name, version, fields, cls, schema, doc)
    return cls


def get_spec(type_name: str) -> MessageSpec:
    try:
        return _REGISTRY[type_name]
    except KeyError:
        raise ContractError(f"unknown message type {type_name!r}") from None


def all_specs() -> dict[str, MessageSpec]:
    return dict(_REGISTRY)


def error_reply_payload(code: str, detail: str, *, retryable: bool = False) -> dict:
    """The section-9 error shape for any `*.reply`."""
    return {"ok": False, "error": {"code": code, "detail": detail, "retryable": retryable}}


__all__ = [
    "ContractError",
    "MessageSpec",
    "ValidationError",
    "all_specs",
    "define",
    "error_reply_payload",
    "get_spec",
    # re-exported so message modules import one name
    "Enum",
    "nullable",
]
