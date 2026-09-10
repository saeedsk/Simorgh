"""One table of commands, three consumers.

There were three lists: `parser.COMMAND_NAMES`, the TUI's completion
table, and the splash's rows. Adding a command meant remembering all
three, and on 2026-09-09 four new ones went into two of them -- so
`tool`, `domains`, `config` and `alerts` worked when typed and did not
autocomplete, which reads like the command does not exist.

The creator, finding it: "following command and many other don't have
autocomplete ability"."""

from __future__ import annotations

import unittest

from simorgh.interface import render
from simorgh.interface.parser import COMMAND_NAMES, COMMANDS, command_help, parse
from simorgh.interface.tui import COMMANDS as TUI_COMMANDS, _command_matches


class OneSourceTestCase(unittest.TestCase):
    def test_every_command_can_be_completed(self):
        completable = {name for name, _ in TUI_COMMANDS}
        self.assertEqual(set(COMMAND_NAMES) - completable, set())

    def test_every_completion_is_a_real_command(self):
        completable = {name for name, _ in TUI_COMMANDS}
        self.assertEqual(completable - set(COMMAND_NAMES), set())

    def test_every_command_appears_in_help(self):
        listed = {usage.split()[0] for usage, _ in command_help()}
        self.assertEqual(set(COMMAND_NAMES) - listed, set())

    def test_the_newest_commands_are_all_there(self):
        """The four that started this."""
        for name in ("tool", "domains", "config", "alerts"):
            self.assertIn(name, COMMAND_NAMES)
            self.assertTrue(_command_matches(name), name)

    def test_every_command_has_a_description(self):
        for name, _, description in COMMANDS:
            self.assertTrue(description.strip(), name)

    def test_no_command_is_listed_twice(self):
        self.assertEqual(len(COMMAND_NAMES), len(set(COMMAND_NAMES)))


class CompletionTestCase(unittest.TestCase):
    def test_a_prefix_finds_the_command(self):
        self.assertEqual([n for n, _ in _command_matches("dom")], ["domains"])

    def test_a_leading_slash_is_optional(self):
        self.assertEqual(_command_matches("/dom"), _command_matches("dom"))

    def test_a_prefix_matching_several_offers_all_of_them(self):
        names = [n for n, _ in _command_matches("c")]
        self.assertIn("config", names)
        self.assertIn("capabilities", names)
        self.assertIn("cancel", names)

    def test_completions_carry_their_description(self):
        self.assertTrue(all(desc for _, desc in _command_matches("t")))

    def test_something_that_matches_nothing_offers_nothing(self):
        self.assertEqual(_command_matches("zzzz"), [])


class SplashTestCase(unittest.TestCase):
    def test_the_splash_shows_the_head_of_the_table_not_all_of_it(self):
        """Twenty rows on the first screen someone sees is a wall, and
        `help` is one word away."""
        self.assertLess(len(render._QUICK_COMMANDS), len(COMMANDS))
        self.assertEqual(render._QUICK_COMMANDS[0][0], "status")

    def test_the_splash_shows_usage_not_just_names(self):
        usages = dict(render._QUICK_COMMANDS)
        self.assertIn("domains [name]", usages)


class ArgumentTestCase(unittest.TestCase):
    def test_a_command_with_an_argument_parses(self):
        command = parse("/domains knowledge")
        self.assertEqual((command.name, command.args), ("domains", "knowledge"))

    def test_a_bare_command_parses_with_no_argument(self):
        self.assertEqual(parse("domains").args, "")
