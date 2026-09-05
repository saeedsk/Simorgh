import tempfile
import unittest
from pathlib import Path

from src.cognition.tool_protocol import (
    extract_code,
    first_line_argument,
    is_valid_python,
    parse_marker,
    preview,
    read_file_for_patch,
    safe_list_dir,
    safe_read_file,
)


class TestParseMarker(unittest.TestCase):
    def test_matches_a_known_marker_case_insensitively(self):
        kind, payload = parse_marker("read: src/x.py", ("READ", "RUN"))
        self.assertEqual(kind, "read")
        self.assertEqual(payload, "src/x.py")

    def test_no_marker_returns_none_and_full_text(self):
        kind, payload = parse_marker("just a final answer", ("READ",))
        self.assertIsNone(kind)
        self.assertEqual(payload, "just a final answer")


class TestExtractCode(unittest.TestCase):
    def test_strips_markdown_fence(self):
        self.assertEqual(extract_code("```python\nx = 1\n```"), "x = 1")

    def test_empty_input_returns_none(self):
        self.assertIsNone(extract_code("   "))


class TestFirstLineArgument(unittest.TestCase):
    def test_single_line_is_unchanged(self):
        self.assertEqual(first_line_argument("src/x.py"), "src/x.py")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(first_line_argument("  src/x.py  \n"), "src/x.py")

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(first_line_argument(""), "")
        self.assertEqual(first_line_argument("   \n  "), "")

    def test_discards_everything_after_the_first_line(self):
        # Live-caught with a real provider: the model doesn't always
        # stop at "READ: <path>" -- it keeps reasoning out loud in the
        # same response instead of emitting a clean single-line marker.
        rambling = (
            "src/orchestrator/discovery.py\n"
            "Wait, the tool format is:\n"
            "`READ: <repo-relative path>` exactly as the ENTIRE response."
        )
        self.assertEqual(first_line_argument(rambling), "src/orchestrator/discovery.py")

    def test_first_line_itself_is_stripped(self):
        self.assertEqual(first_line_argument("  src/x.py  \nmore text"), "src/x.py")


class TestIsValidPython(unittest.TestCase):
    def test_valid_code_is_true(self):
        self.assertTrue(is_valid_python("def f():\n    return 1\n"))

    def test_invalid_code_is_false(self):
        self.assertFalse(is_valid_python("this is not python {{{"))


class TestPreview(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(preview("hello"), "hello")

    def test_newlines_are_collapsed_to_a_single_line(self):
        result = preview("line1\nline2\nline3")
        self.assertNotIn("\n", result)
        self.assertIn("line1", result)
        self.assertIn("line2", result)

    def test_long_text_is_truncated_with_a_count(self):
        text = "x" * 1000
        result = preview(text, limit=100)
        self.assertLessEqual(len(result), 130)
        self.assertIn("more chars", result)


class TestSafeReadFile(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src").mkdir()
        (self.repo_root / "src" / "example.py").write_text("EXAMPLE = 1\n")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_reads_an_allowed_file(self):
        content = safe_read_file(self.repo_root, "src/example.py")
        self.assertIn("EXAMPLE", content)

    def test_refuses_absolute_path(self):
        self.assertIn("refused", safe_read_file(self.repo_root, "/etc/passwd"))

    def test_refuses_path_traversal(self):
        self.assertIn("refused", safe_read_file(self.repo_root, "../../etc/passwd"))

    def test_refuses_path_outside_allowed_roots(self):
        self.assertIn("refused", safe_read_file(self.repo_root, "requirements.txt"))

    def test_refuses_credential_looking_path(self):
        result = safe_read_file(self.repo_root, "src/.env")
        self.assertIn("refused", result)
        self.assertIn("credentials", result)

    def test_refuses_nonexistent_file(self):
        self.assertIn("refused", safe_read_file(self.repo_root, "src/nope.py"))

    def test_never_raises_and_refuses_a_pathologically_long_payload(self):
        # Live-caught crash: a confused model's "READ:" payload was a
        # 50,000+ character hallucinated blob (embedding fake "READ:"/
        # "DRAFT:" exchanges), and Path.is_file() raised a raw OSError
        # ("File name too long") that nothing caught, killing the whole
        # CLI process. This must come back as a refusal string, never an
        # exception, regardless of how large or malformed the input is.
        huge_payload = "src/" + ("a" * 50_000)

        result = safe_read_file(self.repo_root, huge_payload)

        self.assertIsInstance(result, str)
        self.assertIn("refused", result)

    def test_never_raises_for_a_single_path_component_over_the_os_limit(self):
        # A single path segment longer than the filesystem's max name
        # length (255 bytes on most systems) is exactly what triggered
        # the live OSError -- exercised directly, not just via the
        # generic huge-payload case above.
        too_long_segment = "src/" + ("a" * 300)

        result = safe_read_file(self.repo_root, too_long_segment)

        self.assertIsInstance(result, str)
        self.assertIn("refused", result)

    def test_truncates_content_over_the_max_read_size(self):
        big_file = self.repo_root / "src" / "big.py"
        big_file.write_text("x = 1\n" * 10_000)

        result = safe_read_file(self.repo_root, "src/big.py")

        self.assertIn("truncated", result)


class TestSafeListDir(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src" / "agents").mkdir(parents=True)
        (self.repo_root / "src" / "example.py").write_text("EXAMPLE = 1\n")
        (self.repo_root / "src" / "agents" / "logic.py").write_text("X = 1\n")
        (self.repo_root / "src" / "__pycache__").mkdir()
        (self.repo_root / "src" / "__pycache__" / "junk.pyc").write_text("junk")
        (self.repo_root / "docs").mkdir()
        (self.repo_root / "tests").mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_path_lists_the_allowed_top_level_roots(self):
        result = safe_list_dir(self.repo_root, "")
        self.assertEqual(set(result.splitlines()), {"src/", "docs/", "tests/"})

    def test_dot_path_lists_the_allowed_top_level_roots(self):
        result = safe_list_dir(self.repo_root, ".")
        self.assertEqual(set(result.splitlines()), {"src/", "docs/", "tests/"})

    def test_lists_entries_under_an_allowed_directory(self):
        result = safe_list_dir(self.repo_root, "src")
        entries = set(result.splitlines())
        self.assertIn("example.py", entries)
        self.assertIn("agents/", entries)

    def test_pycache_is_hidden_from_listings(self):
        result = safe_list_dir(self.repo_root, "src")
        self.assertNotIn("__pycache__", result)
        self.assertNotIn("__pycache__/", result)

    def test_lists_nested_directory(self):
        result = safe_list_dir(self.repo_root, "src/agents")
        self.assertEqual(result, "logic.py")

    def test_refuses_absolute_path(self):
        self.assertIn("refused", safe_list_dir(self.repo_root, "/etc"))

    def test_refuses_path_traversal(self):
        self.assertIn("refused", safe_list_dir(self.repo_root, "../.."))

    def test_refuses_path_outside_allowed_roots(self):
        self.assertIn("refused", safe_list_dir(self.repo_root, "scripts"))

    def test_refuses_a_file_path_not_a_directory(self):
        self.assertIn("refused", safe_list_dir(self.repo_root, "src/example.py"))

    def test_refuses_nonexistent_directory(self):
        self.assertIn("refused", safe_list_dir(self.repo_root, "src/nope"))

    def test_never_raises_and_refuses_a_pathologically_long_payload(self):
        result = safe_list_dir(self.repo_root, "src/" + ("a" * 10_000))
        self.assertIsInstance(result, str)
        self.assertIn("refused", result)

    def test_empty_directory_reports_clearly(self):
        (self.repo_root / "src" / "empty").mkdir()
        result = safe_list_dir(self.repo_root, "src/empty")
        self.assertIn("empty", result.lower())


class TestReadFileForPatch(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        (self.repo_root / "src").mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_reads_full_content_without_truncation_past_the_read_tool_limit(self):
        # 20_000 chars is safe_read_file's own truncation point -- this
        # must come back whole, not cut short the way a chat READ would.
        big = "x = 1\n" * 5000  # well over 20,000 chars
        (self.repo_root / "src" / "big.py").write_text(big)

        content, refusal = read_file_for_patch(self.repo_root, "src/big.py")

        self.assertIsNone(refusal)
        self.assertEqual(content, big)

    def test_refuses_a_file_over_the_patch_seed_ceiling(self):
        from src.cognition.tool_protocol import _MAX_PATCH_SEED_CHARS

        huge = "x" * (_MAX_PATCH_SEED_CHARS + 1)
        (self.repo_root / "src" / "huge.py").write_text(huge)

        content, refusal = read_file_for_patch(self.repo_root, "src/huge.py")

        self.assertIsNone(content)
        self.assertIn("too large", refusal)

    def test_refuses_path_traversal_same_as_safe_read_file(self):
        content, refusal = read_file_for_patch(self.repo_root, "../../etc/passwd")

        self.assertIsNone(content)
        self.assertIn("refused", refusal)

    def test_refuses_path_outside_allowed_roots(self):
        content, refusal = read_file_for_patch(self.repo_root, "requirements.txt")

        self.assertIsNone(content)
        self.assertIn("refused", refusal)

    def test_refuses_nonexistent_file(self):
        content, refusal = read_file_for_patch(self.repo_root, "src/nope.py")

        self.assertIsNone(content)
        self.assertIn("refused", refusal)

    def test_never_raises_for_a_pathologically_long_payload(self):
        content, refusal = read_file_for_patch(self.repo_root, "src/" + ("a" * 10_000))

        self.assertIsNone(content)
        self.assertIsInstance(refusal, str)


if __name__ == "__main__":
    unittest.main()
