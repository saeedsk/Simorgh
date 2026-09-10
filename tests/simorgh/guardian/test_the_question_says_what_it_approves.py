"""A person cannot approve what they are not shown.

The prompt was `f"Approve {tool}? ({reasons})"`, so a human saw

    Approve install_package? (irreversible action requires human approval)

with no package name, no registry, and no sign that `allow_new` had
switched the typosquat check off. The same sentence covered `run_shell`
without the command and a write without the path. Guardian has the
arguments two lines earlier; the person deciding was the only party who
could not see them (observer, 2026-09-10).
"""

from __future__ import annotations

import unittest

from simorgh.guardian.service import approval_question


class TheQuestionSaysWhatItApprovesTestCase(unittest.TestCase):
    def test_an_install_names_the_package_and_the_manager(self):
        question = approval_question(
            "install_package", {"manager": "pip", "spec": "evil-typosquat-9x", "allow_new": True},
            ["irreversible action requires human approval"])
        self.assertIn("evil-typosquat-9x", question)
        self.assertIn("pip", question)
        self.assertIn("allow_new=True", question)

    def test_a_shell_command_is_shown(self):
        question = approval_question("run_shell", {"command": "rm -rf build"}, ["irreversible"])
        self.assertIn("rm -rf build", question)

    def test_the_reason_is_still_there(self):
        question = approval_question("x", {}, ["irreversible action requires human approval"])
        self.assertIn("irreversible action requires human approval", question)

    def test_a_secret_argument_is_named_but_never_printed(self):
        """The person needs to know a secret is in play; they do not
        need to read it off their own screen."""
        question = approval_question("deploy", {"api_key": "sk-live-abcd1234"}, ["irreversible"])
        self.assertIn("api_key", question)
        self.assertNotIn("sk-live-abcd1234", question)

    def test_a_large_body_is_summarised_not_pasted(self):
        question = approval_question("apply_source_patch",
                                     {"subject": "simorgh/x.py", "code": "x" * 5000},
                                     ["irreversible"])
        self.assertIn("simorgh/x.py", question)
        self.assertIn("5000 chars", question)
        self.assertLess(len(question), 500)

    def test_a_question_is_never_a_wall_of_text(self):
        question = approval_question("t", {f"a{i}": "value" for i in range(200)}, ["why"])
        self.assertLessEqual(len(question), 400)

    def test_a_tool_with_no_arguments_still_reads_as_a_question(self):
        self.assertEqual(approval_question("pause", {}, ["irreversible"]),
                         "Approve pause? [irreversible]")


if __name__ == "__main__":
    unittest.main()
