"""Stage 14 items 1-2: the tool-chain pack, the fault in the house, the suite.

The pack's scenarios can only be PASSED by a real model, so what is
tested here is everything around that: that the pack is what the plan
says (18-24 scenarios, eight categories, all typed by the owner and all
needing a model), that every device and tool it names exists in the
sandbox's house and the chat agent's tool list -- a scenario asking for
a device the fake house does not have measures nothing -- that a floor
run reports every one skipped with its reason, and that an injected
fault really makes the house refuse and then recover.
"""

import asyncio
import os
import re
import time
import unittest
from pathlib import Path
from unittest import mock

import pytest

from simorgh.contracts.home.fakes import DEFAULT_HOUSE, DEFAULT_SERVICES
from simorgh.evals.api import Case, FAILED, Outcome, PASSED, SKIPPED
from simorgh.evals.house.record import Record
from simorgh.evals.house.run import per_scenario, run_pack
from simorgh.evals.house.scenarios import all_scenarios, by_prefix, toolchain
from simorgh.evals.house.script import Beat, Scenario, called, play

REPO = Path(__file__).resolve().parents[4]


def _chat_tools() -> set[str]:
    import tomllib

    text = (REPO / "agents" / "chat.md").read_text(encoding="utf-8")
    front = text.split("+++")[1]
    return set(tomllib.loads(front)["tools"])


class ThePack(unittest.TestCase):
    def test_eighteen_to_twenty_four_scenarios_under_the_prefix(self):
        pack = by_prefix("toolchain/")
        self.assertEqual([s.id for s in pack], [s.id for s in toolchain.SCENARIOS])
        self.assertTrue(18 <= len(pack) <= 24, len(pack))
        self.assertEqual(len({s.id for s in pack}), len(pack), "two scenarios share an id")
        self.assertTrue({s.id for s in pack} <= {s.id for s in all_scenarios()}, "the pack is not registered")

    def test_every_category_has_at_least_two(self):
        counts = {c: 0 for c in toolchain.CATEGORIES}
        for scenario in toolchain.SCENARIOS:
            self.assertIn(toolchain.category(scenario), counts, scenario.id)
            counts[toolchain.category(scenario)] += 1
        thin = {c: n for c, n in counts.items() if n < 2}
        self.assertFalse(thin, f"categories resting on fewer than two scenarios: {thin}")

    def test_all_need_a_model_and_are_typed_by_the_owner(self):
        for scenario in toolchain.SCENARIOS:
            self.assertTrue(scenario.needs_model, scenario.id)
            self.assertTrue(scenario.needs_model_because, scenario.id)
            self.assertTrue(scenario.because, scenario.id)
            for beat in scenario.beats:
                # No `who`: `play` routes it to `director.type`, the
                # owner's console -- not the voice path.
                self.assertEqual(beat.who, "", scenario.id)
                self.assertTrue(beat.says and beat.ask_directly, scenario.id)
                self.assertTrue(beat.expect, f"{scenario.id} has a beat that expects nothing")

    def test_nothing_judges_the_wording(self):
        wording = ("said ", "printed", "said nothing like", "remembered")
        for scenario in toolchain.SCENARIOS:
            for beat in scenario.beats:
                for expectation in beat.expect:
                    self.assertFalse(expectation.name.startswith(wording),
                                     f"{scenario.id}: {expectation.name} reads the reply's words")

    def test_every_safety_scenario_answers_the_question_it_raises(self):
        # Unanswered, the typed turn waits out Guardian's half-hour prompt.
        for scenario in by_prefix("toolchain/safety/"):
            self.assertEqual({b.answers for b in scenario.beats}, {"no"}, scenario.id)

    def test_every_recovery_scenario_injects_a_failure(self):
        for scenario in by_prefix("toolchain/recovery/"):
            faults = [b.fails for b in scenario.beats if b.fails]
            self.assertTrue(faults, scenario.id)
            for fault in faults:
                self.assertIn(fault["service"].partition(".")[2],
                              DEFAULT_SERVICES[fault["service"].partition(".")[0]], scenario.id)

    def test_every_device_and_service_named_exists_in_the_sandbox_house(self):
        source = Path(toolchain.__file__).read_text(encoding="utf-8")
        entities = {row[0] for row in DEFAULT_HOUSE}
        named = set(re.findall(r'"([a-z_]+\.[a-z_]+)"', source))
        self.assertTrue(named)
        for name in named:
            domain, _, rest = name.partition(".")
            is_service = rest in DEFAULT_SERVICES.get(domain, ())
            self.assertTrue(is_service or name in entities,
                            f"{name!r} is neither a service nor a device of the fake house")

    def test_every_tool_named_is_offered_to_the_chat_agent(self):
        offered = _chat_tools()
        source = Path(toolchain.__file__).read_text(encoding="utf-8")
        named = set(re.findall(r'called(?:_with|_any)?\("([a-z_]+)"', source))
        named |= set(re.findall(r'did_not_call\("([a-z_]+)"', source))
        named |= set(toolchain.READS)
        self.assertIn("home_call", named)
        self.assertFalse(named - offered, f"tools the chat agent is not offered: {named - offered}")


class OnTheFloor(unittest.TestCase):
    def test_every_scenario_is_skipped_with_its_reason_and_no_house_is_booted(self):
        env = {k: v for k, v in os.environ.items() if k != "SIMORGH_HOUSE_PAID"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("simorgh.evals.house.run._in_a_child",
                           side_effect=AssertionError("a floor run booted a house")):
            outcomes = asyncio.run(run_pack(toolchain.SCENARIOS))
        self.assertEqual(len(outcomes), len(toolchain.SCENARIOS))
        self.assertEqual({o.status for o in outcomes}, {SKIPPED})
        self.assertTrue(all("floor provider" in o.why for o in outcomes))
        rows = per_scenario(outcomes, toolchain.SCENARIOS)
        self.assertEqual({o.status for o in rows}, {SKIPPED})
        self.assertEqual({o.case.level for o in rows}, set(toolchain.CATEGORIES))


class PerScenario(unittest.TestCase):
    def _o(self, scenario, status, why=""):
        return Outcome(case=Case(name="x", kind="expectation", detail={"scenario": scenario, "beat": "b"}),
                       status=status, why=why)

    def test_every_expectation_must_hold(self):
        rows = {o.case.name: o for o in per_scenario([
            self._o("toolchain/plumbing/a", PASSED), self._o("toolchain/plumbing/a", PASSED),
            self._o("toolchain/recovery/b", PASSED), self._o("toolchain/recovery/b", FAILED, "no retry"),
            self._o("toolchain/safety/c", PASSED), self._o("toolchain/safety/c", SKIPPED, "raised"),
        ])}
        self.assertEqual(rows["toolchain/plumbing/a"].status, PASSED)
        self.assertEqual(rows["toolchain/recovery/b"].status, FAILED)
        self.assertIn("no retry", rows["toolchain/recovery/b"].why)
        # Could not be judged: out of the denominator, not a pass.
        self.assertEqual(rows["toolchain/safety/c"].status, SKIPPED)
        self.assertEqual(rows["toolchain/recovery/b"].case.level, "recovery")

    def test_a_scenario_that_produced_nothing_is_skipped_not_lost(self):
        lost = Scenario(id="toolchain/plumbing/lost")
        rows = per_scenario([], [lost])
        self.assertEqual([(o.case.name, o.status) for o in rows], [("toolchain/plumbing/lost", SKIPPED)])


class TheSuite(unittest.TestCase):
    def test_registered_and_paid(self):
        from simorgh.evals.suites import PAID, SUITES

        self.assertIn("toolchain", SUITES)
        self.assertIn("toolchain", PAID)

    def test_without_paid_it_reports_one_skipped_case_per_scenario(self):
        from simorgh.evals.suites import toolchain as suite

        env = {k: v for k, v in os.environ.items()
               if k not in ("SIMORGH_HOUSE_PAID", "SIMORGH_EVALS_PAID")}
        with mock.patch.dict(os.environ, env, clear=True):
            outcomes = asyncio.run(suite())
            self.assertNotIn("SIMORGH_HOUSE_PAID", os.environ)
        self.assertEqual(len(outcomes), len(toolchain.SCENARIOS))
        self.assertEqual({o.status for o in outcomes}, {SKIPPED})


class _Director:
    """Just enough of `Director` to watch `play` arm and disarm."""

    def __init__(self):
        self.record = Record()
        self.faults: list[tuple] = []
        self.answering: list[str] = []
        self.typed: list[str] = []

    def now(self):
        return time.monotonic()

    def fail(self, service, *, times=1, error="", target="", kind="transient"):
        self.faults.append((service, times))

    async def answer_prompts(self, answer, *, since):
        self.answering.append(answer)
        await asyncio.sleep(3600)

    async def type(self, text):
        await asyncio.sleep(0)
        self.typed.append(text)
        return self.now()


class PlayArmsTheBeat(unittest.TestCase):
    def test_a_fault_is_armed_for_its_beat_and_disarmed_after(self):
        director = _Director()
        scenario = Scenario(id="t", beats=(
            Beat(says="turn it on", ask_directly=True, answers="no",
                 fails={"service": "light.turn_on", "times": 1, "error": "busy"},
                 expect=(called("home_call"),)),
            Beat(says="and again"),
        ))
        asyncio.run(play(scenario, director))
        self.assertEqual(director.faults, [("light.turn_on", 1), ("light.turn_on", 0)])
        self.assertEqual(director.answering, ["no"])
        self.assertEqual(director.typed, ["turn it on", "and again"])


@pytest.mark.integration
class TheHouseFailsWhenToldTo(unittest.IsolatedAsyncioTestCase):
    async def test_a_fault_fires_once_and_the_retry_works(self):
        from simorgh.evals.house import Sandbox

        async with Sandbox() as sandbox:
            execution = sandbox.service("execution")
            tool = execution._registry["home_call"]  # noqa: SLF001
            sandbox.fail("light.turn_on", times=1, error="Home Assistant did not answer in time (504)")
            args = {"service": "light.turn_on", "target": "light.kitchen_main"}

            first = await tool.run(args, ctx=_context(execution))
            self.assertFalse(first.ok)
            self.assertIn("504", first.error)
            self.assertEqual(sandbox.record.house, [], "a refused call is not something the house did")

            second = await tool.run(args, ctx=_context(execution))
            self.assertTrue(second.ok, second.error)
            self.assertEqual([(a.service, a.targets) for a in sandbox.record.house],
                             [("light.turn_on", ("light.kitchen_main",))])
            kitchen = await sandbox.house.state("light.kitchen_main")
            self.assertEqual(kitchen.state, "on")

    async def test_the_media_tools_reach_the_same_house(self):
        from simorgh.evals.house import Sandbox

        async with Sandbox() as sandbox:
            execution = sandbox.service("execution")
            tool = execution._registry["media_control"]  # noqa: SLF001
            self.assertIs(tool._given, sandbox.house)  # noqa: SLF001
            result = await tool.run({"op": "volume", "where": "media_player.kitchen_echo", "value": 15},
                                    ctx=_context(execution))
            self.assertTrue(result.ok, result.error)
            self.assertEqual([(a.service, a.args) for a in sandbox.record.house],
                             [("media_player.volume_set", {"volume_level": 0.15})])


@pytest.mark.integration
class APersonAnswersNo(unittest.IsolatedAsyncioTestCase):
    async def test_the_question_is_answered_and_the_door_stays_locked(self):
        """`Beat(answers="no")` end to end: Guardian asks, the scenario's
        person says no through the Interface, Guardian refuses, and the
        front door -- which this sandbox really could open -- stays shut."""
        from simorgh.evals.house import Director, Sandbox
        from simorgh.evals.house.script import asked_a_person, the_house_did_nothing, was_denied

        async with Sandbox() as sandbox:
            director = Director(sandbox)
            mark = director.now()
            answering = asyncio.ensure_future(director.answer_prompts("no", since=mark))
            try:
                await director.propose("home_call", {"service": "lock.unlock", "target": "lock.front_door"},
                                       requester="", channel="cli", wait=False)
                denied = await director.wait_for("action.denied", since=mark, timeout=20.0)
            finally:
                answering.cancel()
            self.assertIsNotNone(denied, "nobody refused after the person said no")
            for expectation in (asked_a_person(), was_denied(), the_house_did_nothing()):
                self.assertEqual(expectation.check(sandbox.record, mark), "", expectation.name)
            self.assertEqual((await sandbox.house.state("lock.front_door")).state, "locked")


def _context(execution):
    from simorgh.contracts.protocols import ToolContext

    inner = execution._ctx  # noqa: SLF001
    return ToolContext(action_id="toolchain-control", task_id="", scope={"paths": [], "network": False},
                       constraints={}, data_dir=execution._config.repo_root,  # noqa: SLF001
                       clock=inner.clock, logger=inner.logger, ledger=inner.ledger, bus=inner.bus,
                       root=None)


if __name__ == "__main__":
    unittest.main()
