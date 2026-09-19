"""run_shell refusals that protect the creator's credentials (2026-09-18 evaluation, S2)."""

import unittest


class TheShellDoesNotReadCredentials(unittest.TestCase):
    """Reading a credential puts it in the model's context; the file tools
    already refused these directories and the shell did not (S2)."""

    def test_credential_reads_are_refused(self):
        from simorgh.execution.shell import refusal_for

        for command in ("cat ~/.simorgh/secrets.toml", "cp /Users/x/.ssh/id_ed25519 /tmp/k",
                        "base64 $HOME/.aws/credentials", "python3 -c \"print(open('/home/x/.gnupg/k').read())\"",
                        "security find-generic-password -s svc -w"):
            self.assertIsNotNone(refusal_for(command), command)

    def test_ordinary_commands_mentioning_ssh_as_a_word_run(self):
        from simorgh.execution.shell import refusal_for

        for command in ("grep -rn ssh docs/", "echo sshd is fine", "cat README.md", "ls -la"):
            self.assertIsNone(refusal_for(command), command)
