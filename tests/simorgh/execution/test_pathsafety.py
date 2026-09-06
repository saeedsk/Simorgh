"""`execution.pathsafety`: ported from v1's `tool_protocol.py` boundary
(08-execution.md section 5.2). Never raises; every refusal is an
explicit `[refused: ...]` string instead of an exception or a real
filesystem escape."""

import tempfile
import unittest
from pathlib import Path

from simorgh.execution import pathsafety

_ROOTS = ("src", "docs", "tests")


class TestResolveSafePath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("hello")
        (self.root / "docs").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_valid_relative_path_under_a_readable_root_resolves(self):
        target, refusal = pathsafety.resolve_safe_path(self.root, "src/a.py", readable_roots=_ROOTS)
        self.assertIsNone(refusal)
        self.assertEqual(target, (self.root / "src" / "a.py").resolve())

    def test_an_absolute_path_is_refused(self):
        target, refusal = pathsafety.resolve_safe_path(self.root, "/etc/passwd", readable_roots=_ROOTS)
        self.assertIsNone(target)
        self.assertIn("refused", refusal)

    def test_traversal_is_refused(self):
        target, refusal = pathsafety.resolve_safe_path(self.root, "src/../../../etc/passwd", readable_roots=_ROOTS)
        self.assertIsNone(target)
        self.assertIn("refused", refusal)

    def test_a_root_not_in_readable_roots_is_refused(self):
        target, refusal = pathsafety.resolve_safe_path(self.root, "simorgh/kernel/service.py", readable_roots=_ROOTS)
        self.assertIsNone(target)
        self.assertIn("outside the readable areas", refusal)

    def test_credential_shaped_names_are_refused(self):
        for raw in ("src/.env", "src/credentials.json", "src/id_rsa", "src/foo.pem"):
            target, refusal = pathsafety.resolve_safe_path(self.root, raw, readable_roots=_ROOTS)
            self.assertIsNone(target, raw)
            self.assertIn("credentials", refusal, raw)

    def test_an_overlong_path_is_refused(self):
        raw = "src/" + ("a" * 5000)
        target, refusal = pathsafety.resolve_safe_path(self.root, raw, readable_roots=_ROOTS, max_path_chars=100)
        self.assertIsNone(target)
        self.assertIn("too long", refusal)


class TestSafeReadFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("hello world")

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_file_content(self):
        content = pathsafety.safe_read_file(self.root, "src/a.py", readable_roots=_ROOTS)
        self.assertEqual(content, "hello world")

    def test_refuses_a_directory(self):
        content = pathsafety.safe_read_file(self.root, "src", readable_roots=_ROOTS)
        self.assertTrue(content.startswith("[refused:"))

    def test_refuses_a_traversal_attempt_without_raising(self):
        content = pathsafety.safe_read_file(self.root, "../../../etc/passwd", readable_roots=_ROOTS)
        self.assertTrue(content.startswith("[refused:"))

    def test_truncates_very_large_files(self):
        (self.root / "src" / "big.py").write_text("x" * 30_000)
        content = pathsafety.safe_read_file(self.root, "src/big.py", readable_roots=_ROOTS)
        self.assertIn("truncated", content)
        self.assertLess(len(content), 30_000)


class TestSafeListDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("x")
        (self.root / "src" / "sub").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_or_dot_lists_the_readable_roots(self):
        self.assertEqual(pathsafety.safe_list_dir(self.root, "", readable_roots=_ROOTS), "\n".join(_ROOTS))
        self.assertEqual(pathsafety.safe_list_dir(self.root, ".", readable_roots=_ROOTS), "\n".join(_ROOTS))

    def test_lists_entries_with_trailing_slash_on_directories(self):
        content = pathsafety.safe_list_dir(self.root, "src", readable_roots=_ROOTS)
        self.assertIn("a.py", content)
        self.assertIn("sub/", content)

    def test_refuses_a_file_path(self):
        content = pathsafety.safe_list_dir(self.root, "src/a.py", readable_roots=_ROOTS)
        self.assertTrue(content.startswith("[refused:"))


class TestInWriteScope(unittest.TestCase):
    def test_a_path_under_a_write_scope_is_in_scope(self):
        self.assertTrue(pathsafety.in_write_scope("src/foo.py", write_scopes=("src/",)))

    def test_a_path_outside_write_scopes_is_not(self):
        self.assertFalse(pathsafety.in_write_scope("docs/SOUL.md", write_scopes=("src/",)))

    def test_traversal_is_never_in_scope_even_with_a_matching_prefix(self):
        self.assertFalse(pathsafety.in_write_scope("src/../../../etc/passwd", write_scopes=("src/",)))


if __name__ == "__main__":
    unittest.main()
