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


class ImproveMeansImproveTestCase(unittest.IsolatedAsyncioTestCase):
    """`improve <anything with no path>` used to create a SKILL task.

    So "improve, the game freezes after a second" became "write a
    reusable skill module", and three rounds of verification asked
    whether a skill had been produced. The creator, seeing it in the
    task list: "why human ask became a skill? it should have been
    categorized as a task".

    Drafting a skill is a real thing to want; it is now something you
    ask for by name."""

    async def asyncSetUp(self):
        import asyncio

        from simorgh.bus.config import Config as BusConfig
        from simorgh.bus.factory import make_backend, make_client
        from simorgh.contracts import topics
        from simorgh.ledger.factory import make_ledger

        from tests.simorgh.helpers import FakeClock

        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="interface", ledger=self.ledger,
                               clock=self.clock.now)
        await self.bus.start()
        self.other = make_client(backend, source="planning", ledger=self.ledger,
                                 clock=self.clock.now)
        await self.other.start()
        self.created: list = []

        async def _on_create(message) -> None:
            self.created.append(message.payload)
            await self.other.reply(message, type=topics.TASK_CREATE_REPLY,
                                   payload={"task_id": "t-1"})

        self._sub = await self.other.subscribe(topics.TASK_CREATE, _on_create)

    async def asyncTearDown(self):
        await self._sub.unsubscribe()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()

    async def _run(self, line: str) -> dict:
        from simorgh.interface.dispatch import dispatch
        from simorgh.interface.vitals import VitalsCache

        command = parse(line)
        await dispatch(command, bus=self.bus, clock=self.clock, session_id="s1",
                       vitals=VitalsCache(), ledger=self.ledger)
        return self.created[-1] if self.created else {}

    async def test_improve_with_prose_makes_a_patch_task(self):
        payload = await self._run("improve the game freezes after a second")
        self.assertEqual(payload["kind"], "patch")
        self.assertEqual(payload["description"], "the game freezes after a second")

    async def test_improve_with_prose_names_no_subject_rather_than_a_wrong_one(self):
        payload = await self._run("improve the game freezes after a second")
        self.assertNotIn("subject", payload)

    async def test_improve_with_a_path_still_names_it(self):
        payload = await self._run("improve workspace/g.html fix the freeze")
        self.assertEqual(payload["kind"], "patch")
        self.assertEqual(payload["subject"], "workspace/g.html")
        self.assertEqual(payload["description"], "fix the freeze")

    async def test_a_skill_is_asked_for_by_name(self):
        payload = await self._run("skill a day trading advisor")
        self.assertEqual(payload["kind"], "skill")
        self.assertEqual(payload["description"], "a day trading advisor")

    async def test_a_step_budget_still_works_on_both(self):
        self.assertEqual((await self._run("improve fix it steps=30"))["max_steps"], 30)
        self.assertEqual((await self._run("skill a thing steps=25"))["max_steps"], 25)

    async def test_improve_with_nothing_says_what_to_type(self):
        from simorgh.interface.dispatch import dispatch
        from simorgh.interface.vitals import VitalsCache

        outcome = await dispatch(parse("improve"), bus=self.bus, clock=self.clock,
                                 session_id="s1", vitals=VitalsCache(), ledger=self.ledger)
        self.assertIn("usage: improve", outcome.text)
        self.assertIn("skill", outcome.text)

    async def test_skill_with_nothing_points_back_at_improve(self):
        from simorgh.interface.dispatch import dispatch
        from simorgh.interface.vitals import VitalsCache

        outcome = await dispatch(parse("skill"), bus=self.bus, clock=self.clock,
                                 session_id="s1", vitals=VitalsCache(), ledger=self.ledger)
        self.assertIn("improve", outcome.text)


class HelpPanelTestCase(unittest.TestCase):
    def test_every_command_is_on_the_help_screen_with_its_words(self):
        from simorgh.interface.parser import SUBCOMMANDS
        from simorgh.interface.render import help_panel
        text = help_panel(enabled=False)
        for name in COMMAND_NAMES:
            self.assertIn(f"  {name}", text, name)
        for name, subs in SUBCOMMANDS.items():
            for sub, meaning in subs:
                self.assertIn(f"{name} {sub}".strip(), text)
                self.assertIn(meaning, text)
        self.assertIn("tasks clear", text)
        self.assertIn("Look around", text)
        self.assertIn("Voice", text)
        self.assertNotIn("\x1b[", text, "no colour when colour is off")

    def test_every_section_names_only_real_commands(self):
        from simorgh.interface.parser import SECTIONS, SUBCOMMANDS
        for _title, names in SECTIONS:
            for name in names:
                self.assertIn(name, COMMAND_NAMES, name)
        for name in SUBCOMMANDS:
            self.assertIn(name, COMMAND_NAMES, name)
