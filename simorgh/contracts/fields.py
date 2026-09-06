"""The tiny field-type language every message type is declared in.

One declaration produces both the frozen dataclass and the JSON Schema
(see `registry.define`), so the two can never drift apart -- the schema
files under `schema/` are *generated* from these declarations by
`schemagen` and a test proves they are in sync. Keep this deliberately
small: it only has to express the shapes in
docs/blueprint/03-contracts-and-messaging.md section 4.

Usage in a `messages/<domain>.py` module:

    define("task.step", [
        F("task_id", Str), F("step_no", Int), F("phase", Enum("gather", "act", "verify")),
        F("summary", Str), O("tool", Str), O("confidence", Float),
    ])

`F` is a required field, `O` an optional one (absent or null on the
wire; `None` on the dataclass).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Node:
    """A schema node. `schema()` renders JSON Schema; `py` is the Python
    annotation used on the generated dataclass (informational -- the
    dataclass does not enforce it, the schema does)."""

    kind: str
    py: Any = Any
    enum: tuple = ()
    item: "Node | None" = None
    props: tuple = ()  # tuple[Field, ...]
    additional: Any = True  # bool | Node

    def schema(self) -> dict:
        if self.kind == "any":
            return {}
        if self.kind == "nullable":
            return nullable(self.item.schema() if self.item else {})
        if self.kind == "enum":
            return {"type": "string", "enum": list(self.enum)}
        if self.kind == "list":
            return {"type": "array", "items": self.item.schema() if self.item else {}}
        if self.kind == "object":
            return object_schema(self.props, self.additional)
        return {"type": self.kind}


@dataclass(frozen=True)
class Field:
    name: str
    node: Node
    required: bool = True

    def schema(self) -> dict:
        base = self.node.schema()
        return base if self.required else nullable(base)


def nullable(schema: dict) -> dict:
    """Optional fields may be absent *or* null on the wire (a producer that
    serializes a dataclass with a None keeps a stable shape either way)."""
    if not schema:  # `any` already admits null
        return schema
    if "type" in schema and isinstance(schema["type"], str) and "enum" not in schema:
        return {**schema, "type": [schema["type"], "null"]}
    return {"anyOf": [schema, {"type": "null"}]}


def object_schema(props: tuple, additional: Any = True) -> dict:
    schema: dict = {
        "type": "object",
        "properties": {f.name: f.schema() for f in props},
        "required": [f.name for f in props if f.required],
    }
    if additional is False:
        schema["additionalProperties"] = False
    elif isinstance(additional, Node):
        schema["additionalProperties"] = additional.schema()
    else:
        schema["additionalProperties"] = True
    return schema


# --- the vocabulary ---------------------------------------------------------

Str = Node("string", str)
Int = Node("integer", int)
Float = Node("number", float)
Bool = Node("boolean", bool)
Any_ = Node("any", Any)


def Enum(*values: str) -> Node:
    return Node("enum", str, enum=tuple(values))


def List(item: Node = Any_) -> Node:
    return Node("list", list, item=item)


def Nullable(item: Node) -> Node:
    """A *required* key whose value may be null (distinct from `O`, an
    optional key): the key must be present so a consumer can tell "no
    value" from "field forgotten"."""
    return Node("nullable", item.py | None, item=item)


def Obj(*props: Field, additional: Any = True) -> Node:
    return Node("object", dict, props=tuple(props), additional=additional)


def F(name: str, node: Node) -> Field:
    return Field(name, node, required=True)


def O(name: str, node: Node) -> Field:
    return Field(name, node, required=False)
