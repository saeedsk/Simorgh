"""One array without `items` made Gemini refuse every native call.

`400 INVALID_ARGUMENT: ...function_declarations[30].parameters.properties
[rates].items: missing field` -- the energy tariff tool's `rates`, and
the whole request (every tool) was refused, so a native-dialect Gemini
never answered once (a BFCL run, 2026-09-22: 120 of 120 cases fell to
the floor).
"""

import unittest

from simorgh.cognition.providers.native import gemini_declarations


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


class EveryArray(unittest.TestCase):
    def test_an_array_with_no_items_is_given_some(self):
        decls = gemini_declarations([{"name": "t", "input_schema": {
            "type": "object", "properties": {"rates": {"type": "array"}}}}])
        rates = decls[0]["function_declarations"][0]["parameters"]["properties"]["rates"]
        self.assertIn("items", rates)

    def test_every_registered_tool_passes(self):
        from simorgh.domains import domain_tools
        from simorgh.execution.config import Config
        from simorgh.execution.tools import builtin_tools

        tools = [{"name": t.name, "description": t.description, "input_schema": getattr(t, "args_schema", None) or {"type": "object"}}
                 for t in builtin_tools(Config()) + domain_tools(Config(), secrets=None)]
        for node in _walk(gemini_declarations(tools)):
            if node.get("type") == "array":
                self.assertIsInstance(node.get("items"), dict, node)


if __name__ == "__main__":
    unittest.main()
