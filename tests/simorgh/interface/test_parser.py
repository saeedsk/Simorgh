import unittest

from simorgh.interface.parser import parse


class ParserTestCase(unittest.TestCase):
    def test_plain_text_is_chat(self):
        cmd = parse("how are you doing today")
        self.assertIsNone(cmd.name)
        self.assertEqual(cmd.args, "how are you doing today")

    def test_recognized_command_with_args(self):
        cmd = parse("research quantum computing")
        self.assertEqual(cmd.name, "research")
        self.assertEqual(cmd.args, "quantum computing")

    def test_leading_slash_is_optional(self):
        cmd = parse("/status")
        self.assertEqual(cmd.name, "status")

    def test_autocorrect_announces_the_guess(self):
        cmd = parse("imporve a unit converter")
        self.assertEqual(cmd.name, "improve")
        self.assertEqual(cmd.guessed_from, "imporve")
        self.assertEqual(cmd.args, "a unit converter")

    def test_bang_is_shell_passthrough(self):
        cmd = parse("!echo hi")
        self.assertEqual(cmd.name, "!")
        self.assertEqual(cmd.args, "echo hi")

    def test_blank_line_is_none(self):
        self.assertIsNone(parse("   "))

    def test_unrecognized_short_word_is_chat_not_a_guess(self):
        cmd = parse("hey there")
        self.assertIsNone(cmd.name)
        self.assertIsNone(cmd.guessed_from)


if __name__ == "__main__":
    unittest.main()


class ProseIsNotACommandTestCase(unittest.TestCase):
    """A near-miss first word is sometimes a typo and sometimes just a
    sentence.

    The creator typed "improvment, now the game works for one second,
    then it freezes" as a remark. `improvment,` cleared the autocorrect
    cutoff for `improve`, and `improve <topic>` with no path in it
    creates a SKILL task -- so a bug report about a game became "write a
    skill", and three rounds of verification asked whether a skill had
    been produced."""

    def test_the_sentence_that_started_this_is_chat(self):
        command = parse("improvment, now the game works for one second, then it freezes")
        self.assertIsNone(command.name)

    def test_a_typo_with_a_real_argument_is_still_corrected(self):
        command = parse("improvment workspace/x.py fix the thing")
        self.assertEqual(command.name, "improve")
        self.assertEqual(command.guessed_from, "improvment")

    def test_a_leading_slash_keeps_the_correction_permissive(self):
        """Typing the slash is a person saying "this is a command", and
        their typo should still be fixed."""
        command = parse("/improvment, do a thing")
        self.assertEqual(command.name, "improve")

    def test_a_bare_command_with_a_full_stop_still_runs(self):
        """A word on its own is not a sentence, whatever it ends in."""
        self.assertEqual(parse("status.").name, "status")
        self.assertEqual(parse("exit!").name, "exit")

    def test_an_exact_command_followed_by_a_question_is_chat(self):
        """"benchmark, how did it go?" asks about the benchmark; it does
        not ask to run one."""
        self.assertIsNone(parse("benchmark, how did it go?").name)
        self.assertIsNone(parse("tasks, anything left?").name)

    def test_an_exact_command_with_an_ordinary_argument_still_runs(self):
        self.assertEqual(parse("improve workspace/x.html fix the freeze").name, "improve")
        self.assertEqual(parse("domains knowledge").name, "domains")
        self.assertEqual(parse("research the best voxel engines").name, "research")

    def test_a_goal_containing_a_comma_still_reaches_its_command(self):
        """`plan` takes prose. An exact first word with no punctuation on
        it is the person naming the command."""
        command = parse("plan a trip to Iran, then book it")
        self.assertEqual(command.name, "plan")
        self.assertEqual(command.args, "a trip to Iran, then book it")

    def test_a_plain_typo_with_no_argument_is_still_corrected(self):
        self.assertEqual(parse("staus").name, "status")

    def test_a_word_that_is_nothing_like_a_command_is_chat(self):
        self.assertIsNone(parse("hello there").name)
        self.assertIsNone(parse("what happened to the minecraft game?").name)
