"""Stage 2 item 2: the prompt says what each tool does and takes."""

import unittest

from simorgh.cognition.service import _argument_shape, _tool_instruction_block

SPECS = {
    "read_file": {"description": "Read a file's contents (path-safety bounded).",
                  "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}},
    "web_fetch": {"description": "Fetch a URL.",
                  "input_schema": {"type": "object", "required": ["url"], "properties": {"url": {}, "max_chars": {}}}},
}


class ToolsAreDescribed(unittest.TestCase):
    def test_each_offered_tool_gets_a_line_with_what_it_does_and_takes(self):
        block = _tool_instruction_block({"expected": "tool_calls", "tools": ["read_file", "web_fetch"]}, SPECS)
        self.assertIn("- READ_FILE: Read a file's contents (path-safety bounded). (argument: path)", block)
        self.assertIn("- WEB_FETCH: Fetch a URL. (arguments: url, max_chars?)", block)

    def test_an_unregistered_tool_is_still_listed_by_name(self):
        block = _tool_instruction_block({"expected": "tool_calls", "tools": ["skill:new"]}, {})
        self.assertIn("- SKILL:NEW", block)

    def test_the_shape_is_short(self):
        self.assertEqual(_argument_shape({"type": "object"}), "")
        many = {"type": "object", "properties": {f"p{i}": {} for i in range(12)}}
        self.assertTrue(_argument_shape(many).endswith(", ..."))

    def test_no_block_when_no_tools_are_expected(self):
        self.assertIsNone(_tool_instruction_block({"expected": "text", "tools": ["read_file"]}, SPECS))
