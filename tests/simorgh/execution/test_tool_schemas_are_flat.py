"""Every tool's argument schema is flat (stage 17, "Flat schemas are
already done").

A nested object argument is where small models fail tool calls: the
model has to build a structure inside a structure, and a native dialect
gets one more chance to send it as a JSON string, or half of it. On
2026-10-27 every schema in the live registry was flat (read from
`execution:tools`); this keeps it that way. Iterates the real registry
the way the other execution tests do -- `builtin_tools` plus the
domains' `domain_tools` -- plus the tools that register only when a
person configures them (`a2a_call`, `claude_code_task`) and the
worktree tools, so a nested schema cannot hide behind a config switch.

"Flat" here means: no argument is an object that declares its own
`properties`, at any depth (inside an array's `items` too). A free-form
`{"type": "object"}` -- `home_call`'s `data`, passed to Home Assistant
as it comes -- is a map, not a nested schema, and stays allowed.
"""

from __future__ import annotations

import unittest

from simorgh.domains import domain_tools
from simorgh.execution.a2a import A2aCallTool
from simorgh.execution.claudecode import ClaudeCodeTaskTool
from simorgh.execution.config import Config
from simorgh.execution.service import input_schema_of
from simorgh.execution.tools import builtin_tools
from simorgh.execution.worktree import worktree_tools

#: Nested argument schemas that predate this test, each with why it is
#: kept. The set may only shrink: a new entry needs the same argument.
KNOWN_NESTED: dict[tuple[str, str], str] = {
    # A tariff is a list of named rates, each a price and the hours it
    # applies; flattening it means one call per rate. Set by a person
    # once, not chosen by a model mid-turn (energy domain).
    ("energy_tariff", "rates[]"): "a list of {name, price, hours} rows",
}


def _every_tool() -> list:
    config = Config()
    return (builtin_tools(config) + domain_tools(config, secrets=None)
            + worktree_tools(None, land_timeout_s=1.0)
            + [A2aCallTool((), secrets=None), ClaudeCodeTaskTool(config)])


def _nested(schema: dict, path: str = "") -> list[str]:
    """The paths under `schema` whose node is an object declaring
    `properties` (an array's items are `name[]`, an alternative
    `name<anyOf>`), at any depth: an array of arrays of objects, or an
    `anyOf` inside an array's items, is as nested as an object argument."""
    found: list[str] = []
    for name, node in (schema.get("properties") or {}).items():
        found += _nested_node(node, f"{path}{name}")
    return found


def _nested_node(node, here: str) -> list[str]:
    if not isinstance(node, dict):
        return []
    found: list[str] = []
    if node.get("properties"):
        found.append(here)
        # Reported once at its top; what is inside it is the same fault.
        return found
    if isinstance(node.get("items"), dict):
        found += _nested_node(node["items"], f"{here}[]")
    for key in ("anyOf", "oneOf", "allOf"):
        for option in node.get(key) or ():
            found += _nested_node(option, f"{here}<{key}>")
    return found


class EveryToolSchemaIsFlat(unittest.TestCase):
    def test_the_registry_is_the_real_one(self):
        names = {tool.name for tool in _every_tool()}
        # Not an empty list passing vacuously: the tools stage 17 talks about.
        for name in ("home_call", "room_play", "media_control", "remind", "cal_list", "kb_search",
                     "web_search", "cam_snapshot", "look_at_image", "a2a_call", "claude_code_task"):
            self.assertIn(name, names)
        self.assertGreater(len(names), 100)

    def test_no_argument_is_a_nested_object(self):
        nested = []
        for tool in _every_tool():
            for path in _nested(input_schema_of(tool)):
                if (tool.name, path) not in KNOWN_NESTED:
                    nested.append(f"{tool.name}.{path}")
        self.assertFalse(nested, f"nested argument schemas (flatten them, or argue for one in "
                                 f"KNOWN_NESTED): {nested}")

    def test_every_known_exception_is_still_there(self):
        # An exception the schema no longer needs is a hole a new nested
        # argument could walk through unnoticed.
        tools = {tool.name: tool for tool in _every_tool()}
        for (name, path), why in KNOWN_NESTED.items():
            self.assertIn(name, tools, why)
            self.assertIn(path, _nested(input_schema_of(tools[name])), f"{name}.{path} is flat now; drop it")

    def test_the_check_sees_a_nested_argument(self):
        # The positive control: the walk does find what it forbids.
        schema = {"type": "object", "properties": {
            "flat": {"type": "string"}, "map": {"type": "object"},
            "inner": {"type": "object", "properties": {"x": {"type": "string"}}},
            "rows": {"type": "array", "items": {"type": "object", "properties": {"y": {"type": "integer"}}}},
        }}
        self.assertEqual(sorted(_nested(schema)), ["inner", "rows[]"])

    def test_the_check_looks_below_the_first_level(self):
        # An array of arrays of objects, and an object among an array's
        # alternatives, are nested too; a one-level walk missed both.
        obj = {"type": "object", "properties": {"x": {"type": "string"}}}
        schema = {"type": "object", "properties": {
            "grid": {"type": "array", "items": {"type": "array", "items": obj}},
            "either": {"type": "array", "items": {"anyOf": [{"type": "string"}, obj]}},
            "maybe": {"anyOf": [{"type": "null"}, obj]},
            "strings": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        }}
        self.assertEqual(sorted(_nested(schema)), ["either[]<anyOf>", "grid[][]", "maybe<anyOf>"])


if __name__ == "__main__":
    unittest.main()
