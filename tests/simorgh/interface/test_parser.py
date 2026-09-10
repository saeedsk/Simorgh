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


class ASentenceStartingWithACommandWordTestCase(unittest.TestCase):
    """Typing a remark must not run a command.

    Live-caught 2026-09-10 at a real prompt. `exit strategy for the
    company is unclear` STOPPED THE SYSTEM, and `pause for a moment and
    think about it` paused every subsystem. Both commands take `args`
    as a free-text reason, so the sentence became the reason and nothing
    downstream could tell it from an instruction. `status of the game is
    bad, it freezes` printed a health panel and the remark reached
    nothing at all.

    `_looks_like_prose` did not help: it guarded only the autocorrect
    guess and the punctuation-trimmed path, and these sentences match a
    command name exactly.
    """

    def test_exit_does_not_stop_the_system_mid_sentence(self):
        self.assertIsNone(parse("exit strategy for the company is unclear").name)

    def test_pause_does_not_halt_everything_mid_sentence(self):
        self.assertIsNone(parse("pause for a moment and think about it").name)

    def test_a_remark_about_status_is_a_remark(self):
        self.assertIsNone(parse("status of the game is bad, it freezes").name)

    def test_asking_for_help_with_something_is_a_question(self):
        self.assertIsNone(parse("help me understand why the build fails").name)

    def test_the_bare_command_still_works(self):
        for word in ("exit", "pause", "resume", "status", "help", "capabilities"):
            self.assertEqual(parse(word).name, word)

    def test_the_slash_still_means_this_is_a_command(self):
        """Typing the slash is a person saying so, reason and all."""
        command = parse("/exit because I am done")
        self.assertEqual((command.name, command.args), ("exit", "because I am done"))

    def test_a_command_that_really_takes_an_argument_still_takes_it(self):
        for line, name, args in (("benchmark run gaia 5", "benchmark", "run gaia 5"),
                                 ("interests rust", "interests", "rust"),
                                 ("research the moon", "research", "the moon"),
                                 ("cancel abc123", "cancel", "abc123")):
            command = parse(line)
            self.assertEqual((command.name, command.args), (name, args))


class ArgumentHintsMatchTheDispatcherTestCase(unittest.TestCase):
    """The hints are not decoration any more: `NO_ARGUMENT_COMMANDS` is
    derived from them, so a wrong hint now changes behaviour as well as
    help text. Three were wrong until 2026-09-10 -- `interests`,
    `benchmark` and `mcp` all read real arguments while declaring none.
    """

    def test_commands_that_read_arguments_declare_them(self):
        from simorgh.interface.parser import NO_ARGUMENT_COMMANDS

        for name in ("interests", "benchmark", "mcp", "tasks", "auto", "cancel"):
            self.assertNotIn(name, NO_ARGUMENT_COMMANDS,
                             f"{name} reads args in dispatch; its hint must say so")

    def test_commands_that_ignore_arguments_declare_nothing(self):
        from simorgh.interface.parser import NO_ARGUMENT_COMMANDS

        for name in ("status", "help", "capabilities", "pause", "resume", "exit"):
            self.assertIn(name, NO_ARGUMENT_COMMANDS)
