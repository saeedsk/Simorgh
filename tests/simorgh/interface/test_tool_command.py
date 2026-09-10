"""The `tool` command: fifty tools reachable from the terminal through
one command, and through Guardian rather than around it.

Adding a slash command per tool would have made the help screen
unreadable and still not answered the question a person actually has.
What matters most in these tests is the safety property: this publishes
`action.proposed` exactly as a Worker does, so a denial denies and an
escalation escalates. The CLI is another caller in front of the gate,
not a way round it."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.interface import dispatch as dispatch_module
from simorgh.interface.dispatch import cli_tool_args, dispatch
from simorgh.interface.parser import Command
from simorgh.interface.vitals import VitalsCache
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


class CliArgumentTestCase(unittest.TestCase):
    """A person types one line; the model writes two. Both have to mean
    the same thing, and the table that decides is shared
    (`contracts/toolargs.py`) so they cannot drift apart."""

    def test_a_single_string_tool_takes_the_whole_remainder(self):
        self.assertEqual(cli_tool_args("kb_search", "flood cover on the house"),
                         {"query": "flood cover on the house"})

    def test_a_no_argument_tool_sends_no_arguments(self):
        self.assertEqual(cli_tool_args("sec_self", ""), {})

    def test_a_two_part_tool_splits_on_the_first_space_when_typed_on_one_line(self):
        """`tool remind 20m take the bins out` means what it looks
        like. Splitting on a newline, as the model's path does, would
        put the whole sentence in the time field."""
        self.assertEqual(cli_tool_args("remind", "20m take the bins out"),
                         {"when": "20m", "text": "take the bins out"})

    def test_a_two_part_tool_still_honours_a_real_newline(self):
        self.assertEqual(cli_tool_args("remind", "tomorrow 9am\ncall the plumber"),
                         {"when": "tomorrow 9am", "text": "call the plumber"})

    def test_json_after_the_first_word_merges_into_the_arguments(self):
        args = cli_tool_args("home_call", 'light.turn_on {"target": "kitchen lights"}')
        self.assertEqual(args, {"service": "light.turn_on", "target": "kitchen lights"})

    def test_a_whole_json_object_is_taken_as_the_arguments(self):
        self.assertEqual(cli_tool_args("kb_search", '{"query": "flood", "k": 3}'),
                         {"query": "flood", "k": 3})

    def test_malformed_json_is_an_error_rather_than_a_silent_string(self):
        self.assertIn("__error__", cli_tool_args("kb_search", '{"query": '))

    def test_key_value_pairs_work_for_a_tool_with_no_marker_shape(self):
        args = cli_tool_args("some_unknown_tool", "alpha=1 beta=two gamma=true")
        self.assertEqual(args, {"alpha": 1, "beta": "two", "gamma": True})

    def test_a_quoted_value_keeps_its_spaces(self):
        self.assertEqual(cli_tool_args("some_unknown_tool", 'note="two words"'),
                         {"note": "two words"})

    def test_an_unknown_tool_with_no_pairs_sends_nothing_rather_than_a_guess(self):
        """Inventing an argument name produces a call the tool silently
        ignores, which is harder to diagnose than one that plainly had
        no arguments."""
        self.assertEqual(cli_tool_args("some_unknown_tool", "just some words"), {})


class _ToolCommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.executor = make_client(backend, source="execution", ledger=self.ledger,
                                    clock=self.clock.now)
        await self.executor.start()
        self.vitals = VitalsCache()
        self.proposals: list = []
        self.behaviour = "ok"

    async def asyncTearDown(self):
        await self.executor.stop()
        await self.bus.stop()
        await self.ledger.stop()

    async def _register(self, name: str, *, reversibility: str = "read_only",
                        description: str = "does a thing") -> None:
        await self.ledger.append(dispatch_module.TOOLS_STREAM, Event(
            stream=dispatch_module.TOOLS_STREAM, type="registered", ts=self.clock.now(),
            trace_id="", causation_id=None,
            payload={"name": name, "provider": "builtin", "reversibility": reversibility,
                     "read_only": reversibility == "read_only", "description": description}))

    async def _stand_in_for_guardian_and_execution(self) -> None:
        """Answers a proposal the way the real pair would."""

        async def _on_proposed(message) -> None:
            self.proposals.append(message.payload)
            action_id = message.payload["action_id"]
            if self.behaviour == "denied":
                await self.executor.publish(self.executor.new(topics.ACTION_DENIED, {
                    "action_id": action_id, "reasons": ["plan mode: only read-only tools"],
                    "layer": "policy", "tool": message.payload["tool"]}))
                return
            ok = self.behaviour != "failed"
            await self.executor.publish(self.executor.new(topics.ACTION_RESULT, {
                "action_id": action_id, "ok": ok,
                "output_ref": "", "stdout_preview": "two passages matched" if ok else "",
                "duration_ms": 12, "side_effects": [],
                **({} if ok else {"error": "the index is empty"})}))

        self._sub = await self.executor.subscribe(topics.ACTION_PROPOSED, _on_proposed)
        self.addAsyncCleanup(self._sub.unsubscribe)

    async def _tool(self, args: str) -> str:
        outcome = await dispatch(
            Command(name="tool", args=args, raw=f"tool {args}"),
            bus=self.bus, clock=self.clock, session_id="s1", vitals=self.vitals,
            ledger=self.ledger)
        return outcome.text


class ToolListTestCase(_ToolCommandTestCase):
    async def test_with_nothing_registered_it_says_so(self):
        self.assertIn("no tools registered", await self._tool(""))

    async def test_it_lists_what_is_registered_grouped(self):
        for name in ("kb_search", "kb_ask", "home_call", "read_file"):
            await self._register(name)
        listed = await self._tool("")
        self.assertIn("documents:", listed)
        self.assertIn("the house:", listed)
        self.assertIn("kb_search", listed)
        self.assertIn("4 tools", listed)

    async def test_it_says_that_guardian_still_applies(self):
        await self._register("kb_search")
        self.assertIn("Guardian", await self._tool(""))

    async def test_an_unknown_name_suggests_a_near_one(self):
        await self._register("kb_search")
        answer = await self._tool("kb_serach flood")
        self.assertIn("kb_search", answer)

    async def test_a_tool_named_with_no_arguments_says_what_it_wants(self):
        await self._register("kb_search")
        answer = await self._tool("kb_search")
        self.assertIn("<query>", answer)


class ToolRunTestCase(_ToolCommandTestCase):
    async def test_it_proposes_the_action_and_prints_the_result(self):
        await self._register("kb_search")
        await self._stand_in_for_guardian_and_execution()
        answer = await self._tool("kb_search flood cover")
        self.assertIn("two passages matched", answer)
        self.assertEqual(len(self.proposals), 1)
        self.assertEqual(self.proposals[0]["tool"], "kb_search")
        self.assertEqual(self.proposals[0]["args"], {"query": "flood cover"})

    async def test_the_proposal_says_a_person_asked_for_it(self):
        """`proposed_by` is what tells a reviewer, later, that this was
        a person at the terminal rather than an autonomous step."""
        await self._register("kb_search")
        await self._stand_in_for_guardian_and_execution()
        await self._tool("kb_search flood")
        self.assertTrue(self.proposals[0]["proposed_by"].startswith("interface:"))
        self.assertIn("terminal", self.proposals[0]["rationale"])

    async def test_a_denial_is_reported_with_its_reason(self):
        """The CLI is another caller in front of the gate, not a way
        round it."""
        await self._register("home_call", reversibility="irreversible")
        await self._stand_in_for_guardian_and_execution()
        self.behaviour = "denied"
        answer = await self._tool('home_call lock.unlock {"target": "front door"}')
        self.assertIn("denied", answer)
        self.assertIn("only read-only tools", answer)

    async def test_a_failure_is_reported_as_a_failure(self):
        await self._register("kb_search")
        await self._stand_in_for_guardian_and_execution()
        self.behaviour = "failed"
        answer = await self._tool("kb_search flood")
        self.assertIn("failed", answer)
        self.assertIn("index is empty", answer)

    async def test_nothing_answering_times_out_rather_than_hanging_forever(self):
        await self._register("kb_search")
        outcome = await dispatch_module._tool_command(
            "kb_search flood", bus=self.bus, ledger=self.ledger, session_id="s1", timeout=0.1)
        self.assertIn("did not finish", outcome.text)

    async def test_a_result_that_arrives_immediately_is_not_missed(self):
        """Subscribing after publishing would let a fast tool answer
        into the gap, and the command would wait out its whole timeout
        on a call that had already succeeded."""
        await self._register("sec_posture")
        await self._stand_in_for_guardian_and_execution()
        answer = await self._tool("sec_posture")
        self.assertIn("two passages matched", answer)
        self.assertEqual(self.proposals[0]["args"], {})

    async def test_a_long_output_comes_back_from_the_blob(self):
        await self._register("kb_search")
        body = "x" * 5000
        ref = await self.ledger.put_blob(body.encode())

        async def _on_proposed(message) -> None:
            await self.executor.publish(self.executor.new(topics.ACTION_RESULT, {
                "action_id": message.payload["action_id"], "ok": True, "output_ref": ref,
                "stdout_preview": "x" * 100, "duration_ms": 5, "side_effects": []}))

        sub = await self.executor.subscribe(topics.ACTION_PROPOSED, _on_proposed)
        self.addAsyncCleanup(sub.unsubscribe)
        answer = await self._tool("kb_search flood")
        self.assertEqual(len(answer.strip()), 5000)
