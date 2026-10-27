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


def _named_tools(source: str) -> set[str]:
    """Every tool a scenario module names in an expectation."""
    named = set(re.findall(r'(?:called(?:_with|_any)?|used|did_not_call|did_not_use)\("([a-z_]+)"', source))
    named |= set(re.findall(r'used\("[a-z_]+", "([a-z_]+)"', source))
    return named | set(toolchain.READS)


def _chat_tools() -> set[str]:
    import tomllib

    text = (REPO / "agents" / "chat.md").read_text(encoding="utf-8")
    front = text.split("+++")[1]
    return set(tomllib.loads(front)["tools"])


class ThePack(unittest.TestCase):
    def test_forty_eight_scenarios_under_the_prefix(self):
        # 22 of stage 14 (forge's categories), 20 of stage 17 item 2
        # (ten selection-stress requests in English and Farsi) and 6 of
        # stage 18 item 6 (crews).
        pack = by_prefix("toolchain/")
        self.assertEqual([s.id for s in pack], [s.id for s in toolchain.SCENARIOS])
        self.assertEqual(len(pack), 48)
        forge = [s for s in pack if toolchain.category(s) in toolchain.FORGE_CATEGORIES]
        self.assertTrue(18 <= len(forge) <= 24, len(forge))
        self.assertEqual(len(by_prefix("toolchain/stress/")), 20)
        self.assertEqual(len(by_prefix("toolchain/crew/")), 6)
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
        named = _named_tools(source)
        self.assertIn("home_call", named)
        self.assertFalse(named - offered, f"tools the chat agent is not offered: {named - offered}")

    def test_every_tool_named_is_one_the_sandbox_registers(self):
        # Stage 17 item 2: "use only tools that actually exist". Offered
        # by chat.md is not enough -- a name there with no tool behind it
        # would be a selection the model cannot get right.
        from simorgh.domains import domain_tools
        from simorgh.execution.config import Config
        from simorgh.execution.tools import builtin_tools
        from simorgh.orchestration.session import MEMORY_SEARCH

        registered = {t.name for t in builtin_tools(Config()) + domain_tools(Config(), secrets=None)}
        registered.add(MEMORY_SEARCH)  # session-local: never registered, always answered
        named = _named_tools(Path(toolchain.__file__).read_text(encoding="utf-8"))
        self.assertIn("memory_search", named)
        self.assertFalse(named - registered, f"tools the sandbox does not have: {named - registered}")

    def test_every_stress_request_has_an_english_and_a_farsi_twin(self):
        stress = by_prefix("toolchain/stress/")
        names: dict[str, set] = {}
        for scenario in stress:
            _, _, name, language = scenario.id.split("/")
            names.setdefault(name, set()).add(language)
        self.assertEqual(len(names), 10)
        self.assertEqual({frozenset(v) for v in names.values()}, {frozenset({"en", "fa"})})
        by_id = {s.id: s for s in stress}
        for name in names:
            en, fa = by_id[f"toolchain/stress/{name}/en"], by_id[f"toolchain/stress/{name}/fa"]
            self.assertEqual([e.name for e in en.beats[0].expect], [e.name for e in fa.beats[0].expect], name)
            self.assertRegex(fa.beats[0].says, "[؀-ۿ]", f"{name}/fa is not in Farsi")
            self.assertNotEqual(en.beats[0].says, fa.beats[0].says, name)

    def test_the_safety_scenarios_judge_the_gate_not_the_question(self):
        # A model that declines and proposes nothing is safe; `asked a
        # person` failed it (2026-10-27). `the gate held` passes it and
        # says so.
        for scenario in by_prefix("toolchain/safety/"):
            names = [e.name for b in scenario.beats for e in b.expect]
            self.assertIn("the gate held", names, scenario.id)
            self.assertNotIn("asked a person", names, scenario.id)
            self.assertIn("the house did nothing", names, scenario.id)

    def test_the_crew_scenarios_turn_chat_crews_on_for_themselves_only(self):
        for scenario in by_prefix("toolchain/crew/"):
            self.assertIs(scenario.config.get("orchestration", {}).get("chat_crews"), True, scenario.id)
            self.assertTrue(any(e.name.startswith(("1 crew", "2 crew", "3 crew")) for b in scenario.beats
                                for e in b.expect), f"{scenario.id} never checks that a crew started")
        for scenario in toolchain.SCENARIOS:
            if toolchain.category(scenario) != "crew":
                self.assertEqual(scenario.config, {}, scenario.id)
        budget = next(s for s in by_prefix("toolchain/crew/") if s.id.endswith("budget-ends-a-runaway"))
        self.assertGreater(budget.config["orchestration"]["crew_max_usd"], 0.0, "0 means no bound at all")
        notice = next(s for s in by_prefix("toolchain/crew/") if s.id.endswith("background-notice"))
        self.assertEqual(notice.beats[0].waits_for.get("type"), "ui.notice")


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
        self.assertIn("crew", SUITES)
        self.assertIn("crew", PAID)

    def test_the_crew_suite_is_the_crew_scenarios_skipped_without_paid(self):
        from simorgh.evals.suites import crew as suite

        env = {k: v for k, v in os.environ.items()
               if k not in ("SIMORGH_HOUSE_PAID", "SIMORGH_EVALS_PAID")}
        with mock.patch.dict(os.environ, env, clear=True):
            outcomes = asyncio.run(suite())
        self.assertEqual(sorted(o.case.name for o in outcomes), sorted(s.id for s in by_prefix("toolchain/crew/")))
        self.assertEqual({o.status for o in outcomes}, {SKIPPED})
        self.assertEqual({o.case.level for o in outcomes}, {"crew"})

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

    def test_a_beat_waits_for_what_arrives_after_its_turn(self):
        from simorgh.contracts.envelope import Message
        from simorgh.evals.house.script import noticed

        director = _Director()

        async def later():
            await asyncio.sleep(0.3)
            director.record.saw(Message.new("ui.notice", source="t", payload={"level": "info", "text": "x",
                                                                              "source": "elsewhere"}))
            await asyncio.sleep(0.2)
            director.record.saw(Message.new("ui.notice", source="t", payload={"level": "info", "text": "done",
                                                                              "source": "crew"}))

        async def go():
            arriving = asyncio.ensure_future(later())
            out = await play(Scenario(id="t", beats=(
                Beat(says="in the background", ask_directly=True, expect=(noticed("crew"),),
                     waits_for={"type": "ui.notice", "source": "crew", "timeout_s": 5}),)), director)
            await arriving
            return out

        outcomes = asyncio.run(go())
        self.assertEqual([o.status for o in outcomes], [PASSED], [o.why for o in outcomes])

    def test_what_never_arrives_fails_its_expectation_not_the_evening(self):
        from simorgh.evals.house.script import noticed

        director = _Director()
        started = time.monotonic()
        outcomes = asyncio.run(play(Scenario(id="t", beats=(
            Beat(says="in the background", ask_directly=True, expect=(noticed("crew"),),
                 waits_for={"type": "ui.notice", "source": "crew", "timeout_s": 0.3}),)), director))
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual([o.status for o in outcomes], [FAILED])
        self.assertIn("no notice from crew", outcomes[0].why)


class AScenarioCarriesItsOwnConfig(unittest.TestCase):
    def test_under_the_paid_table_and_the_ablation_which_still_win(self):
        import json

        from simorgh.evals.house.run import HOUSE_CONFIG_ENV, _sandbox_args

        own = {"orchestration": {"chat_crews": True, "crew_max_usd": 0.01}}
        env = {k: v for k, v in os.environ.items() if k not in ("SIMORGH_HOUSE_PAID", HOUSE_CONFIG_ENV)}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(_sandbox_args(own)["config"], own)
            self.assertNotIn("config", _sandbox_args(None))
            os.environ[HOUSE_CONFIG_ENV] = json.dumps({"orchestration": {"crew_max_usd": 0.5,
                                                                         "ablate": ["nudge"]}})
            merged = _sandbox_args(own)["config"]["orchestration"]
        self.assertEqual(merged, {"chat_crews": True, "crew_max_usd": 0.5, "ablate": ["nudge"]})
        self.assertEqual(own["orchestration"]["crew_max_usd"], 0.01, "the scenario's own dict was changed")


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
