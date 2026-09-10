"""`replace_in_file`: changing part of a file without re-sending it all.

`apply_source_patch` replaces a file entirely, so altering one line of a
150-line document meant re-emitting all 150 lines. A chat turn's output
budget was smaller than the file, so each "edit" wrote a truncated copy
and the file got shorter every time.

Live-caught 2026-09-09 rebuilding a voxel game: 147 lines became 131,
then 129, then 76, then 54, each write a sincere attempt at the whole
file that ran out of room. The content-loss guard caught one step and
the model routed around it with smaller files. No amount of prompting
fixes that -- the tool was asking for something the model could not
deliver."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.tools import ReplaceInFileTool, parse_replace_blocks


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None)


def _block(find: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{find}\n=======\n{replace}\n>>>>>>> REPLACE"


class ParseTestCase(unittest.TestCase):
    def test_one_block(self):
        blocks, problem = parse_replace_blocks(_block("a = 1", "a = 2"))
        self.assertEqual(problem, "")
        self.assertEqual(blocks, [("a = 1", "a = 2")])

    def test_several_blocks(self):
        blocks, problem = parse_replace_blocks(_block("a", "b") + "\n" + _block("c", "d"))
        self.assertEqual(problem, "")
        self.assertEqual(blocks, [("a", "b"), ("c", "d")])

    def test_multi_line_bodies_keep_their_shape(self):
        blocks, _ = parse_replace_blocks(_block("def f():\n    return 1",
                                                 "def f():\n    return 2"))
        self.assertEqual(blocks[0][0], "def f():\n    return 1")

    def test_an_empty_replacement_is_a_deletion(self):
        blocks, problem = parse_replace_blocks("<<<<<<< SEARCH\ndrop me\n=======\n>>>>>>> REPLACE")
        self.assertEqual(problem, "")
        self.assertEqual(blocks, [("drop me", "")])

    def test_no_block_at_all_shows_the_shape(self):
        _, problem = parse_replace_blocks("just some prose")
        self.assertIn("<<<<<<< SEARCH", problem)

    def test_an_unclosed_block_is_refused_rather_than_half_applied(self):
        _, problem = parse_replace_blocks("<<<<<<< SEARCH\na\n=======\nb")
        self.assertIn("never closed", problem)

    def test_a_nested_open_is_refused(self):
        _, problem = parse_replace_blocks("<<<<<<< SEARCH\na\n<<<<<<< SEARCH\nb")
        self.assertIn("second SEARCH", problem)

    def test_an_end_marker_with_no_start_is_refused(self):
        _, problem = parse_replace_blocks(">>>>>>> REPLACE")
        self.assertIn("no SEARCH", problem)

    def test_an_empty_search_is_refused(self):
        _, problem = parse_replace_blocks("<<<<<<< SEARCH\n\n=======\nx\n>>>>>>> REPLACE")
        self.assertIn("empty", problem)

    def test_a_stray_extra_angle_bracket_is_tolerated(self):
        """A model that writes seven brackets instead of eight has not
        made a meaningful mistake."""
        blocks, problem = parse_replace_blocks(
            "<<<<<<<< SEARCH\na\n========\nb\n>>>>>>>> REPLACE")
        self.assertEqual(problem, "")
        self.assertEqual(blocks, [("a", "b")])


class _ToolTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "workspace").mkdir()
        self.tool = ReplaceInFileTool(Config(repo_root=self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / "workspace" / name
        path.write_text(text, encoding="utf-8")
        return path

    async def _run(self, name: str, code: str):
        return await self.tool.run({"path": f"workspace/{name}", "code": code}, ctx=_ctx())


class ReplaceTestCase(_ToolTestCase):
    LONG = "\n".join(f"line {n}" for n in range(150))

    async def test_it_changes_only_what_was_asked(self):
        path = self._write("g.html", self.LONG)
        result = await self._run("g.html", _block("line 42", "line forty-two"))
        self.assertTrue(result.ok, result.error)
        after = path.read_text()
        self.assertIn("line forty-two", after)
        self.assertIn("line 149", after)

    async def test_the_rest_of_a_long_file_survives(self):
        """The whole point. A 150-line file must still be 150 lines
        after a one-line edit."""
        path = self._write("g.html", self.LONG)
        await self._run("g.html", _block("line 42", "line forty-two"))
        self.assertEqual(len(path.read_text().splitlines()), 150)

    async def test_several_edits_in_one_call(self):
        path = self._write("g.html", self.LONG)
        result = await self._run("g.html",
                                 _block("line 101", "ONE") + "\n" + _block("line 102", "TWO"))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata["blocks"], 2)
        self.assertIn("ONE", path.read_text())
        self.assertIn("TWO", path.read_text())

    async def test_it_reports_the_length_change(self):
        self._write("g.html", self.LONG)
        result = await self._run("g.html", _block("line 105", "line 105\nline 105b"))
        self.assertIn("+1 lines", result.output)
        self.assertEqual(result.metadata["lines_after"], 151)

    async def test_text_that_is_not_there_changes_nothing(self):
        path = self._write("g.html", self.LONG)
        before = path.read_text()
        result = await self._run("g.html", _block("line 999", "x"))
        self.assertFalse(result.ok)
        self.assertIn("not in", result.error)
        self.assertEqual(path.read_text(), before, "a refusal must not have written")

    async def test_a_search_that_is_a_substring_of_other_lines_is_refused(self):
        """"line 1" is inside "line 10" through "line 19" and "line 100"
        onwards. A tool that took the first match would have edited the
        wrong line and said it succeeded."""
        path = self._write("g.html", self.LONG)
        before = path.read_text()
        result = await self._run("g.html", _block("line 1", "ONE"))
        self.assertFalse(result.ok)
        self.assertIn("appears 61 times", result.error)
        self.assertEqual(path.read_text(), before)

    async def test_text_appearing_twice_is_refused_rather_than_guessed(self):
        """Replacing the first of three identical lines is a coin flip,
        and the two-thirds of the time it guesses wrong the damage is
        silent."""
        path = self._write("g.html", "a\nsame\nb\nsame\nc")
        result = await self._run("g.html", _block("same", "changed"))
        self.assertFalse(result.ok)
        self.assertIn("appears 2 times", result.error)
        self.assertIn("unique", result.error)
        self.assertEqual(path.read_text(), "a\nsame\nb\nsame\nc")

    async def test_a_later_block_failing_leaves_the_file_untouched(self):
        """All or nothing. Half an edit is a file nobody asked for."""
        path = self._write("g.html", self.LONG)
        before = path.read_text()
        result = await self._run("g.html",
                                 _block("line 101", "ONE") + "\n" + _block("nowhere", "x"))
        self.assertFalse(result.ok)
        self.assertEqual(path.read_text(), before)

    async def test_replacing_something_with_itself_says_nothing_changed(self):
        """Saying "written" when nothing moved is the failure this
        project keeps calling out."""
        self._write("g.html", self.LONG)
        result = await self._run("g.html", _block("line 107", "line 107"))
        self.assertTrue(result.ok)
        self.assertFalse(result.metadata["changed"])
        self.assertIn("nothing changed", result.output)

    async def test_a_deletion_removes_the_text(self):
        path = self._write("g.html", "keep\ndrop me\nkeep too")
        await self._run("g.html", "<<<<<<< SEARCH\ndrop me\n\n=======\n>>>>>>> REPLACE")
        self.assertNotIn("drop me", path.read_text())

    async def test_a_file_that_does_not_exist_is_refused(self):
        result = await self._run("nope.html", _block("a", "b"))
        self.assertFalse(result.ok)

    async def test_no_path_is_refused(self):
        result = await self.tool.run({"path": "  ", "code": _block("a", "b")}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_writing_outside_the_scope_is_refused(self):
        (self.root / "secrets.txt").write_text("a\nb\n")
        result = await self.tool.run({"path": "../outside.txt", "code": _block("a", "b")},
                                     ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_indentation_is_preserved_exactly(self):
        path = self._write("a.py", "def f():\n    x = 1\n    return x\n")
        result = await self._run("a.py", _block("    x = 1", "    x = 2"))
        self.assertTrue(result.ok, result.error)
        self.assertIn("    x = 2", path.read_text())

    async def test_a_python_edit_that_would_not_parse_is_refused(self):
        """The same guard `apply_source_patch` has: refusing beats
        writing a file that cannot run."""
        path = self._write("a.py", "def f():\n    return 1\n")
        result = await self._run("a.py", _block("    return 1", "    return ("))
        self.assertFalse(result.ok)
        self.assertIn("return 1", path.read_text())


class ContractTestCase(unittest.TestCase):
    def test_it_is_reversible_not_irreversible(self):
        tool = ReplaceInFileTool(Config())
        self.assertEqual(tool.reversibility, "reversible")
        self.assertFalse(tool.read_only)

    def test_the_description_warns_against_the_whole_file_tool(self):
        """The model has to know WHICH to reach for; that choice is the
        whole bug."""
        description = ReplaceInFileTool(Config()).description
        self.assertIn("apply_source_patch", description)
        self.assertIn("truncate", description)


class ReadPastTheEndTestCase(unittest.TestCase):
    """A range past the end answers with the tail rather than nothing.

    Three steps in a row went to guessing line ranges on 2026-09-09,
    while the model was trying to edit a file it had just shortened. It
    learned only the length each time and had to guess again."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "workspace").mkdir()
        (self.root / "workspace" / "g.html").write_text(
            "\n".join(f"line {n}" for n in range(1, 61)), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _read(self, start: int, end: int) -> str:
        from simorgh.execution import pathsafety

        return pathsafety.safe_read_lines(self.root, "workspace/g.html", start=start, end=end,
                                           readable_roots=("workspace",))

    def test_it_still_says_the_real_length(self):
        self.assertIn("has 60 lines", self._read(200, 260))

    def test_it_shows_the_end_of_the_file(self):
        answer = self._read(200, 260)
        self.assertIn("line 60", answer)
        self.assertIn("line 21", answer)

    def test_it_says_that_it_showed_the_tail(self):
        self.assertIn("Here are the last", self._read(200, 260))

    def test_the_tail_is_numbered_with_real_line_numbers(self):
        self.assertIn("   60| line 60", self._read(200, 260))

    def test_a_range_inside_the_file_is_unaffected(self):
        answer = self._read(1, 3)
        self.assertIn("    1| line 1", answer)
        self.assertNotIn("Here are the last", answer)
