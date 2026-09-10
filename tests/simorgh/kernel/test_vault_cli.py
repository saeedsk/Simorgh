"""`simorgh vault ...`: the door onto `kernel/vault.py`.

The vault module has existed since 7f54faa with no command surface at
all, so every credential had to go in an environment variable -- the
same designed-slot-with-no-door shape the scheduler had before
`schedule` was added.

It is a CLI subcommand and NOT a REPL command on purpose. Adding a
secret means typing it, and the REPL's line reader echoes what it is
given and keeps it in history, so a password typed there would end up
on the screen and in a file.

Every test here points `SIMORGH_VAULT_PATH` at a temporary file, so
none of them touches the real vault, and the key comes from an injected
fake keyring rather than the machine's keychain."""

from __future__ import annotations

import io
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from simorgh.kernel.cli import main


class _VaultCliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "vault.bin"
        # `SIMORGH_VAULT_NO_KEYRING` keeps the key in a file beside the
        # temporary vault. Without it these tests reach the real macOS
        # keychain and leave an entry behind, which has happened to this
        # project once already from nothing but running the suite.
        self._env = unittest.mock.patch.dict(
            "os.environ", {"SIMORGH_VAULT_PATH": str(self.path),
                           "SIMORGH_VAULT_NO_KEYRING": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _run(self, *argv, typed: str | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            if typed is not None:
                with unittest.mock.patch("getpass.getpass", return_value=typed):
                    code = main(list(argv))
            else:
                code = main(list(argv))
        return code, out.getvalue(), err.getvalue()


class ListTestCase(_VaultCliTestCase):
    def test_an_empty_vault_says_how_to_add_one(self):
        code, out, _ = self._run("vault", "list")
        self.assertEqual(code, 0)
        self.assertIn("empty", out)
        self.assertIn("simorgh vault add", out)

    def test_it_names_the_file_and_where_the_key_came_from(self):
        _, out, _ = self._run("vault", "list")
        self.assertIn(str(self.path), out)
        self.assertIn("key from", out)

    def test_a_stored_credential_is_listed_by_id_and_kind(self):
        self._run("vault", "add", "imap:fastmail", typed="app-password")
        _, out, _ = self._run("vault", "list")
        self.assertIn("imap:fastmail", out)
        self.assertIn("password", out)

    def test_listing_never_prints_the_value(self):
        """The property that makes this safe to run over someone's
        shoulder."""
        self._run("vault", "add", "imap:fastmail", typed="hunter2-the-actual-secret")
        _, out, _ = self._run("vault", "list")
        self.assertNotIn("hunter2", out)


class AddTestCase(_VaultCliTestCase):
    def test_it_stores_what_was_typed(self):
        code, out, _ = self._run("vault", "add", "imap:home", typed="s3cret")
        self.assertEqual(code, 0)
        self.assertIn("imap:home", out)

        from simorgh.kernel.vault import Vault

        self.assertEqual(dict(Vault(self.path).open("imap:home")), {"password": "s3cret"})

    def test_the_value_is_never_echoed_back(self):
        _, out, _ = self._run("vault", "add", "imap:home", typed="s3cret")
        self.assertNotIn("s3cret", out)
        self.assertIn("never echoed", out)

    def test_typing_nothing_stores_nothing(self):
        code, _, err = self._run("vault", "add", "imap:home", typed="")
        self.assertEqual(code, 1)
        self.assertIn("nothing stored", err)

    def test_a_second_field_joins_the_same_credential(self):
        """An OAuth credential is several values under one id. Adding
        the second must not throw the first away."""
        self._run("vault", "add", "google:me", "--field", "client_id", typed="the-id")
        self._run("vault", "add", "google:me", "--field", "client_secret", typed="the-secret")

        from simorgh.kernel.vault import Vault

        self.assertEqual(dict(Vault(self.path).open("google:me")),
                         {"client_id": "the-id", "client_secret": "the-secret"})

    def test_the_kind_is_recorded(self):
        self._run("vault", "add", "google:me", "--kind", "oauth2", typed="t")
        _, out, _ = self._run("vault", "list")
        self.assertIn("oauth2", out)


class RemoveTestCase(_VaultCliTestCase):
    def test_it_removes(self):
        self._run("vault", "add", "imap:home", typed="x")
        code, out, _ = self._run("vault", "remove", "imap:home")
        self.assertEqual(code, 0)
        _, listed, _ = self._run("vault", "list")
        self.assertNotIn("imap:home", listed)

    def test_removing_something_absent_is_not_an_error(self):
        self.assertEqual(self._run("vault", "remove", "never:existed")[0], 0)


class ImportTestCase(_VaultCliTestCase):
    def test_it_copies_from_the_environment(self):
        with unittest.mock.patch.dict("os.environ", {"MY_TOKEN": "from-the-env"}):
            code, out, _ = self._run("vault", "import", "svc:x", "env:MY_TOKEN")
        self.assertEqual(code, 0)

        from simorgh.kernel.vault import Vault

        self.assertEqual(dict(Vault(self.path).open("svc:x")), {"password": "from-the-env"})

    def test_it_copies_from_a_file(self):
        source = Path(self._tmp.name) / "token.txt"
        source.write_text("  from-a-file\n", encoding="utf-8")
        self._run("vault", "import", "svc:y", f"file:{source}")

        from simorgh.kernel.vault import Vault

        self.assertEqual(dict(Vault(self.path).open("svc:y")), {"password": "from-a-file"})

    def test_it_says_the_copy_is_a_copy(self):
        """`import` reads once and never again, so rotating the source
        does not rotate this. Saying so is the difference between a
        person knowing that and finding out months later."""
        with unittest.mock.patch.dict("os.environ", {"MY_TOKEN": "v"}):
            _, out, _ = self._run("vault", "import", "svc:x", "env:MY_TOKEN")
        self.assertIn("copy", out)

    def test_a_source_that_cannot_be_read_is_an_error_not_an_empty_secret(self):
        code, _, err = self._run("vault", "import", "svc:x", "env:DEFINITELY_NOT_SET")
        self.assertEqual(code, 1)
        self.assertIn("could not read", err)

    def test_the_value_is_never_printed(self):
        with unittest.mock.patch.dict("os.environ", {"MY_TOKEN": "super-secret-value"}):
            _, out, _ = self._run("vault", "import", "svc:x", "env:MY_TOKEN")
        self.assertNotIn("super-secret", out)


class StaleTestCase(_VaultCliTestCase):
    def test_a_fresh_credential_is_not_stale(self):
        self._run("vault", "add", "imap:home", typed="x")
        _, out, _ = self._run("vault", "stale")
        self.assertIn("nothing unused", out)

    def test_an_old_credential_is_reported(self):
        self._run("vault", "add", "imap:home", typed="x")
        _, out, _ = self._run("vault", "stale", "--days", "0")
        self.assertIn("imap:home", out)


class BadConfigTestCase(_VaultCliTestCase):
    def test_an_unloadable_config_does_not_lock_you_out_of_the_vault(self):
        """Being locked out of your credentials because a TOML key has a
        typo is a bad afternoon."""
        broken = Path(self._tmp.name) / "broken.toml"
        broken.write_text("this is not = valid = toml", encoding="utf-8")
        code, out, _ = self._run("--config", str(broken), "vault", "list")
        self.assertEqual(code, 0)
        self.assertIn(str(self.path), out)


class KeychainTestCase(_VaultCliTestCase):
    def test_the_opt_out_keeps_the_key_in_a_file(self):
        """Set in every test here, so the suite never reaches the real
        keychain. Asserted rather than assumed, because the failure is
        invisible: everything passes and an entry is quietly left on the
        developer's machine."""
        self._run("vault", "add", "imap:home", typed="x")
        _, out, _ = self._run("vault", "list")
        self.assertIn("key from file", out)
        self.assertTrue(self.path.with_suffix(self.path.suffix + ".key").is_file())

    def test_the_key_file_is_not_readable_by_anyone_else(self):
        import os
        import stat as stat_module

        self._run("vault", "add", "imap:home", typed="x")
        key_path = self.path.with_suffix(self.path.suffix + ".key")
        mode = key_path.stat().st_mode
        self.assertEqual(mode & 0o077, 0, stat_module.filemode(mode))
