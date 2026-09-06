"""A small, dependency-free JSON Schema (draft 2020-12 subset) validator.

The catalog's schemas only ever use: `type` (string or list of strings),
`required`, `properties`, `additionalProperties` (bool or schema), `enum`,
`const`, `items`, `anyOf`, `oneOf`. That subset is enough for every
message payload in docs/blueprint/03-contracts-and-messaging.md section 4
and keeps this validator small enough to read in one sitting -- which is
the point: a contracts package that pulled in a third-party validator
would make *every* subsystem depend on it (principle 4.14, stdlib core).

Numbers: JSON has one number type, so `"type": "number"` accepts ints
and floats, `"integer"` accepts ints (and integral floats, matching the
spec's "integer" definition); booleans are never numbers.
"""

from __future__ import annotations

from typing import Any

JSON_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")


class ValidationError(ValueError):
    """Raised by `check()`; `errors` lists every problem found, each as
    `"<json-path>: <reason>"` so a bug surfaces where it was written."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _type_matches(instance: Any, type_name: str) -> bool:
    if type_name == "null":
        return instance is None
    if type_name == "boolean":
        return isinstance(instance, bool)
    if type_name == "integer":
        if isinstance(instance, bool):
            return False
        return isinstance(instance, int) or (isinstance(instance, float) and instance.is_integer())
    if type_name == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if type_name == "string":
        return isinstance(instance, str)
    if type_name == "array":
        return isinstance(instance, list)
    if type_name == "object":
        return isinstance(instance, dict)
    raise ValueError(f"unknown JSON Schema type {type_name!r}")


def validate(instance: Any, schema: dict, path: str = "$") -> list[str]:
    """Return a list of error strings (empty means valid). Never raises
    for a bad *instance*; raises ValueError only for a malformed schema,
    which is a contracts bug, not a runtime condition."""
    errors: list[str] = []
    if schema is True or schema == {}:
        return errors
    if schema is False:
        return [f"{path}: no value allowed here"]

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']!r}")

    if "type" in schema:
        allowed = schema["type"]
        names = [allowed] if isinstance(allowed, str) else list(allowed)
        if not any(_type_matches(instance, name) for name in names):
            errors.append(f"{path}: expected type {'|'.join(names)}, got {type(instance).__name__}")
            return errors  # further structural checks would be meaningless

    if "anyOf" in schema:
        branches = schema["anyOf"]
        if not any(not validate(instance, branch, path) for branch in branches):
            errors.append(f"{path}: matched none of {len(branches)} anyOf branches")
    if "oneOf" in schema:
        branches = schema["oneOf"]
        hits = sum(1 for branch in branches if not validate(instance, branch, path))
        if hits != 1:
            errors.append(f"{path}: matched {hits} of {len(branches)} oneOf branches (need exactly 1)")

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}.{name}: required property missing")
        for name, value in instance.items():
            if name in properties:
                errors.extend(validate(value, properties[name], f"{path}.{name}"))
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}.{name}: additional property not allowed")
                elif isinstance(extra, dict):
                    errors.extend(validate(value, extra, f"{path}.{name}"))

    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(validate(item, schema["items"], f"{path}[{index}]"))

    return errors


def check(instance: Any, schema: dict, path: str = "$") -> None:
    """Raise ValidationError if `instance` doesn't satisfy `schema`."""
    errors = validate(instance, schema, path)
    if errors:
        raise ValidationError(errors)


def is_valid(instance: Any, schema: dict) -> bool:
    return not validate(instance, schema)
