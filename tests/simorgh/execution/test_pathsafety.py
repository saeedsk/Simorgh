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


class SimCanReadItsOwnSourceTestCase(unittest.TestCase):
    """The credential guard matched a WORD anywhere in a path, so it hid
    Sim's own code from Sim.

    Observed 2026-09-10: `simorgh/kernel/secrets.py` and its test were
    unreadable, all three `simorgh/contracts/schema/world.env.*.json`
    schemas matched on the ".env" inside "world.env.query", and
    `docs/secrets-design.md` was refused for having the word in its
    title. `search_code` skipped the same files, so Sim could not even
    grep for a symbol defined in its own secret store.

    The replacement is narrower on purpose: a `.py` or `.md` named after
    secrets is source ABOUT secrets; a `.json`, `.env` or `.pem` by the
    same name is the thing itself. Secrets here live in the environment
    or a 0600 TOML, never in tracked source.
    """

    def _refused(self, path: str) -> bool:
        from pathlib import Path

        return pathsafety.looks_like_credential_path(Path(path).parts)

    def test_sims_own_secret_store_is_readable_source(self):
        for path in ("simorgh/kernel/secrets.py", "tests/simorgh/kernel/test_secrets.py",
                     "docs/secrets-design.md", "simorgh/kernel/vault.py"):
            self.assertFalse(self._refused(path), path)

    def test_a_schema_with_env_in_the_middle_of_its_name_is_readable(self):
        self.assertFalse(self._refused("simorgh/contracts/schema/world.env.query.v1.json"))

    def test_a_real_dotenv_is_still_refused(self):
        for path in ("tools/.env", "tools/.env.local", "config/prod.env"):
            self.assertTrue(self._refused(path), path)

    def test_a_credential_data_file_is_still_refused(self):
        for path in ("tools/credentials.json", "app/token.yaml", "app/passwords.toml"):
            self.assertTrue(self._refused(path), path)

    def test_a_private_key_is_still_refused_by_name_or_extension(self):
        for path in ("workspace/id_rsa", "certs/server.pem", "certs/client.key", "x/.netrc"):
            self.assertTrue(self._refused(path), path)

    def test_a_credential_directory_protects_whatever_is_inside_it(self):
        for path in ("secrets/anything.txt", "home/.ssh/config", "home/.aws/config"):
            self.assertTrue(self._refused(path), path)
