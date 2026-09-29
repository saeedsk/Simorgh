"""run_shell's PATH carries the command-line tools that live inside a
macOS app. 2026-09-29: "Tailscale isn't installed on this host" -- it was,
with its CLI inside Tailscale.app."""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.execution import shell


class ShellFindsAppClis(unittest.TestCase):
    def test_an_app_cli_dir_that_exists_is_appended(self):
        with mock.patch.object(shell, "APP_CLI_DIRS", ("/opt/Some.app/Contents/MacOS",)), \
                mock.patch.object(shell.os.path, "isdir", return_value=True), \
                mock.patch.dict(shell.os.environ, {"PATH": "/usr/bin:/bin"}, clear=True):
            self.assertEqual(shell._child_env()["PATH"], "/usr/bin:/bin:/opt/Some.app/Contents/MacOS")  # noqa: SLF001

    def test_one_that_does_not_exist_is_not(self):
        with mock.patch.object(shell, "APP_CLI_DIRS", ("/opt/Missing.app/Contents/MacOS",)), \
                mock.patch.object(shell.os.path, "isdir", return_value=False), \
                mock.patch.dict(shell.os.environ, {"PATH": "/usr/bin"}, clear=True):
            self.assertEqual(shell._child_env()["PATH"], "/usr/bin")  # noqa: SLF001

    def test_secrets_are_still_taken_out(self):
        with mock.patch.dict(shell.os.environ, {"PATH": "/usr/bin", "TOGETHER_API_KEY": "sk-x"}, clear=True):
            self.assertNotIn("TOGETHER_API_KEY", shell._child_env())  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
