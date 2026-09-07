"""Output parsing (docs/blueprint/subsystems/04-cognition.md section 5,
"Output parsing") -- every case here is a live-caught v1 lesson, not a
fresh design; see `simorgh/cognition/parser.py`'s module docstring."""

from __future__ import annotations

import unittest

from simorgh.cognition.api import ParsedOutput
from simorgh.cognition.parser import (
    OutputParser,
    extract_code,
    first_line_argument,
    is_valid_python,
    parse_marker,
    parse_search_replace_blocks,
    preview,
    scan_verdict,
)


class TestPreview(unittest.TestCase):
    def test_collapses_newlines_and_truncates(self):
        text = "line one\nline two\n" + ("x" * 200)
        result = preview(text, limit=20)
        self.assertNotIn("\n", result)
        self.assertIn("more chars", result)

    def test_short_text_untouched_besides_newline_collapse(self):
        self.assertEqual(preview("hello\nworld"), "hello ⏎ world")


class TestFirstLineArgument(unittest.TestCase):
    def test_a_model_that_keeps_rambling_past_the_marker_only_yields_the_first_line(self):
        # The live-caught lesson: a bare-token argument (a path) is only
        # ever the first non-empty line, even if the model keeps talking.
        rambling = "src/memory/long_term.py\nI chose this file because it contains the relevant class.\n"
        self.assertEqual(first_line_argument(rambling), "src/memory/long_term.py")

    def test_empty_text_yields_empty_string(self):
        self.assertEqual(first_line_argument("   \n  "), "")


class TestParseMarker(unittest.TestCase):
    def test_recognized_marker_is_case_insensitive(self):
        marker, payload = parse_marker("draft: def f(): pass", ("DRAFT", "RUN"))
        self.assertEqual(marker, "draft")
        self.assertEqual(payload, "def f(): pass")

    def test_unrecognized_text_returns_none_marker_and_the_whole_stripped_text(self):
        marker, payload = parse_marker("  just a final answer  ", ("DRAFT", "RUN"))
        self.assertIsNone(marker)
        self.assertEqual(payload, "just a final answer")


class TestExtractCode(unittest.TestCase):
    def test_pulls_python_out_of_a_fenced_block(self):
        text = "here you go:\n```python\nx = 1\n```\ntrailing prose"
        self.assertEqual(extract_code(text), "x = 1")

    def test_falls_back_to_the_whole_text_when_unfenced(self):
        self.assertEqual(extract_code("x = 1"), "x = 1")

    def test_empty_result_is_none_not_empty_string(self):
        self.assertIsNone(extract_code("```python\n\n```"))


class TestIsValidPython(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertTrue(is_valid_python("x = 1 + 2"))
        self.assertFalse(is_valid_python("def f(:"))


class TestParseSearchReplaceBlocks(unittest.TestCase):
    def test_one_block(self):
        text = (
            "<<<<<<< SEARCH\n"
            "old_line = 1\n"
            "=======\n"
            "new_line = 2\n"
            ">>>>>>> REPLACE\n"
        )
        blocks = parse_search_replace_blocks(text)
        self.assertEqual(blocks, [("old_line = 1", "new_line = 2")])

    def test_no_block_returns_none_not_empty_list(self):
        self.assertIsNone(parse_search_replace_blocks("just a plain final answer, no edit blocks here"))

    def test_multiple_blocks_in_order(self):
        text = (
            "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
            "some narration in between\n"
            "<<<<<<< SEARCH\nc\n=======\nd\n>>>>>>> REPLACE\n"
        )
        self.assertEqual(parse_search_replace_blocks(text), [("a", "b"), ("c", "d")])


class TestScanVerdict(unittest.TestCase):
    def test_finds_standalone_yes(self):
        self.assertTrue(scan_verdict("I looked it over.\nYES\nlooks good"))

    def test_finds_standalone_no_case_insensitive(self):
        self.assertFalse(scan_verdict("no, this fails the invariant"))

    def test_a_model_that_narrates_instead_of_answering_is_a_non_answer_not_a_rejection(self):
        # The live-caught lesson: silence must never be scored as a
        # rejection -- the caller has to see None and defer, not fail.
        self.assertIsNone(scan_verdict("I'm still thinking about whether this is correct."))


class TestOutputParser(unittest.TestCase):
    def setUp(self):
        self.parser = OutputParser()

    def test_default_expected_is_final(self):
        result = self.parser.parse("  the answer  ", None)
        self.assertEqual(result, ParsedOutput(kind="final", text="the answer"))

    def test_markers_single_token_argument_uses_first_line_only(self):
        text = "READ: src/foo.py\nbecause it looks relevant to the bug"
        result = self.parser.parse(text, {"kind": "markers", "markers": ("READ", "DRAFT")})
        self.assertEqual(result.kind, "tool_calls")
        self.assertEqual(result.tool_calls, ({"tool": "read", "args": {"argument": "src/foo.py"}},))

    def test_markers_code_bearing_marker_keeps_full_payload(self):
        text = "DRAFT: def f():\n    return 1\n"
        result = self.parser.parse(text, {"kind": "markers", "markers": ("DRAFT", "RUN")})
        self.assertEqual(result.tool_calls[0]["args"]["argument"], "def f():\n    return 1")

    def test_markers_real_v2_code_bearing_tool_names_keep_full_payload(self):
        """Live-caught: the real markers a session actually configures are
        `session.profile.tools`' full tool names (`orchestration/
        profiles.py`), not v1's short `DRAFT`/`RUN` -- `RUN_PYTHON_
        SANDBOXED`/`DRAFT_CANDIDATE` used to fall through to
        `first_line_argument` and silently lose everything past the first
        line of real multi-line code."""
        text = "RUN_PYTHON_SANDBOXED: def f():\n    return 1\n"
        result = self.parser.parse(text, {"kind": "markers", "markers": ("RUN_PYTHON_SANDBOXED", "READ_FILE")})
        self.assertEqual(result.tool_calls, ({"tool": "run_python_sandboxed", "args": {"argument": "def f():\n    return 1"}},))

    def test_markers_real_v2_single_token_tool_still_uses_first_line_only(self):
        text = "READ_FILE: docs/SOUL.md\nbecause it looks relevant to the bug"
        result = self.parser.parse(text, {"kind": "markers", "markers": ("READ_FILE", "RUN_PYTHON_SANDBOXED")})
        self.assertEqual(result.tool_calls, ({"tool": "read_file", "args": {"argument": "docs/SOUL.md"}},))

    def test_markers_no_marker_present_is_a_final_answer(self):
        result = self.parser.parse("just answering directly", {"kind": "markers", "markers": ("DRAFT",)})
        self.assertEqual(result.kind, "final")

    def test_edit_blocks_kind_parses_real_blocks(self):
        text = "<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE\n"
        result = self.parser.parse(text, {"kind": "edit_blocks"})
        self.assertEqual(result.kind, "edit_blocks")
        self.assertEqual(result.edit_blocks, ({"search": "foo", "replace": "bar"},))

    def test_edit_blocks_kind_falls_back_to_plain_code_when_the_model_ignores_the_instruction(self):
        result = self.parser.parse("```python\nx = 1\n```", {"kind": "edit_blocks"})
        self.assertEqual(result.kind, "final")
        self.assertEqual(result.text, "x = 1")

    def test_verdict_kind_true(self):
        result = self.parser.parse("Looks correct.\nYES", {"kind": "verdict"})
        self.assertEqual(result.kind, "verdict")
        self.assertTrue(result.verdict)

    def test_verdict_kind_non_answer_is_flagged_not_rejected(self):
        result = self.parser.parse("I need more context before I can say.", {"kind": "verdict"})
        self.assertEqual(result.kind, "non_answer")
        self.assertTrue(result.non_answer)
        self.assertIsNone(result.verdict)


if __name__ == "__main__":
    unittest.main()
