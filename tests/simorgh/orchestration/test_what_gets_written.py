"""What actually reaches a file, and what a tool result actually means.

Four more found by putting one task at a time to Sim and watching,
2026-09-07 -- the round after the five that first let it write anything
at all. Each one turned a correct answer from the model into no change,
or into a broken file.
"""

from __future__ import annotations

import unittest

from simorgh.cognition.parser import parse_marker
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.tools import _python_syntax_problem
from simorgh.orchestration import profiles
from simorgh.orchestration.tools import to_action_payload

_SKILL_TOOLS = tuple(profiles.SKILL.tools)


def _payload(tool: str, argument: str) -> dict:
    return to_action_payload(
        action_id="a1", task_id="t1", rationale="step 1",
        call={"tool": tool, "args": {"argument": argument}},
    )


class TestACodeFenceNeverReachesTheFile(unittest.TestCase):
    """Asked for its first skill, Sim replied with its code in a
    ```python fence and `apply_skill` wrote the fence into the file, so
    `word_count.py` began with a literal "```python"."""

    def test_a_fenced_body_is_unwrapped(self):
        args = _payload("apply_skill", "simorgh_skills/x.py\n```python\ndef run():\n    return 1\n```")["args"]
        self.assertEqual(args["code"], "def run():\n    return 1")

    def test_an_unlabelled_fence_is_unwrapped_too(self):
        args = _payload("apply_source_patch", "simorgh/x.py\n```\nx = 1\n```")["args"]
        self.assertEqual(args["code"], "x = 1")

    def test_unfenced_code_is_left_exactly_as_it_is(self):
        body = "def run():\n    return 1\n"
        args = _payload("apply_skill", f"simorgh_skills/x.py\n{body}")["args"]
        self.assertEqual(args["code"], body)

    def test_the_path_is_still_the_first_line(self):
        args = _payload("apply_skill", "simorgh_skills/x.py\n```python\nx = 1\n```")["args"]
        self.assertEqual(args["subject"], "simorgh_skills/x.py")


class TestABrokenFileIsRefusedNotWritten(unittest.TestCase):
    """Everything after the marker's first line becomes the file body,
    and the model kept talking after its code -- so a skill was written
    with a hallucinated "[test results: 42 passed]" and a stray "You are
    Simorgh, continue." pasted into it. The function above them was
    perfect; the file would not import."""

    def test_conversation_pasted_after_the_code_is_caught(self):
        code = 'def run(text):\n    return len(text.split())\n\n[test results: 42 passed]\n\nYou are Simorgh, continue.'
        problem = _python_syntax_problem("simorgh_skills/word_count.py", code)
        self.assertIsNotNone(problem)
        self.assertIn("Send only the file's code", problem)

    def test_real_code_passes(self):
        self.assertIsNone(_python_syntax_problem("simorgh/x.py", "def f():\n    return 1\n"))

    def test_the_error_names_the_line(self):
        problem = _python_syntax_problem("simorgh/x.py", "def f(:\n    pass\n")
        self.assertIn("line", problem)

    def test_a_non_python_file_is_not_parsed(self):
        self.assertIsNone(_python_syntax_problem("docs/notes.md", "# not python at all: ("))


class TestANativeToolCallIsStillACall(unittest.TestCase):
    """The model used the tool-call syntax it was trained on. The marker
    sat inside a `<tool_call>` tag, invisible to a line scan, so the
    session recorded a final answer and the task "completed" having done
    nothing."""

    def test_a_marker_wrapped_in_tool_call_tags_is_found(self):
        text = (
            "I'll start by checking whether the skill already exists."
            "<tool_call>SEARCH_CODE: word_count</arg_value></tool_call>"
        )
        marker, payload = parse_marker(text, _SKILL_TOOLS)
        self.assertEqual(marker, "search_code")
        self.assertTrue(payload.startswith("word_count"))

    def test_prose_that_merely_mentions_a_tool_is_unaffected(self):
        self.assertIsNone(parse_marker("read_file is a tool I have.", _SKILL_TOOLS)[0])

    def test_the_plain_convention_still_works(self):
        self.assertEqual(parse_marker("READ_FILE: a.py", _SKILL_TOOLS), ("read_file", "a.py"))


class TestNoTestsIsNotAFailingSuite(unittest.IsolatedAsyncioTestCase):
    """A brand-new file has no tests. pytest exits 5 for "nothing
    collected", which was read as a red suite -- so Sim did exactly what
    its instructions say and refused to commit, every time."""

    async def test_a_target_with_no_tests_reports_ok(self):
        import tempfile
        from pathlib import Path

        from simorgh.contracts.protocols import ToolContext
        from simorgh.execution.tools import RunTestsTool

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "simorgh").mkdir()
            (root / "simorgh" / "fresh.py").write_text("def f():\n    return 1\n")
            (root / "tests").mkdir()
            ctx = ToolContext(
                action_id="a1", task_id=None, scope={}, constraints={},
                data_dir=root, clock=None, logger=None, ledger=None,
            )
            result = await RunTestsTool(ExecutionConfig(repo_root=root)).run(
                {"target": "simorgh/fresh.py"}, ctx=ctx,
            )
            self.assertTrue(result.ok, result.error)
            self.assertTrue(result.metadata.get("no_tests_collected"))
            self.assertIn("no tests cover this target yet", result.output)


if __name__ == "__main__":
    unittest.main()
