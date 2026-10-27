"""Stage 18's review gaps, closed (docs/plan/stage-18-agent-crews.md, Status):

1. the crew tools have flat native schemas, announced on `tool.registered`
   and checked by the guardrails, and a crew tool the session was not
   offered is refused, guardrails or none;
2. a crew member's `claude_code_task` is capped at, and charged to, its
   crew's dollars;
4. a background result reaches the person who asked, not the owner: two
   people, a real Initiative, end to end;
5. a background report filed but not delivered when the process stopped
   is delivered once by the next start, never twice.

Every model, Guardian and Execution here is a fake; nothing leaves the
process."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message, validate
from simorgh.contracts.messages.crew import MemberBudget
from simorgh.contracts.protocols import Context
from simorgh.contracts.streamnames import crew_stream
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.crew import CREW_BUDGET, DELIVERED_KIND, TOOL_SPECS, Crew
from simorgh.orchestration.service import Service
from simorgh.orchestration.session import CREW_TOOLS
from simorgh.orchestration.tools import forget_registered, tool_schemas

from .fakes import FakeGuardianExecution
from .harness import Harness, run
from .test_chat_crews import _chat, _collect, _member_answer, _until
from .test_crews import CrewCognition, _call, _root, _runner, _text


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


# -- 1. schemas and the offered set ---------------------------------------------------------


class TheCrewToolsHaveSchemas(unittest.TestCase):
    def test_every_crew_tool_has_a_flat_object_schema(self):
        self.assertEqual(set(TOOL_SPECS), set(CREW_TOOLS))
        for name, spec in TOOL_SPECS.items():
            with self.subTest(tool=name):
                schema = spec["input_schema"]
                self.assertEqual(schema["type"], "object")
                self.assertTrue(spec["description"])
                self.assertTrue(schema["properties"])
                for key, prop in schema["properties"].items():
                    self.assertNotEqual(prop.get("type"), "object", f"{name}.{key} is nested")
                    self.assertNotEqual((prop.get("items") or {}).get("type"), "object", f"{name}.{key}")
                for key in schema.get("required") or ():
                    self.assertIn(key, schema["properties"])

    @run
    async def test_orchestration_announces_them_and_its_own_announcement_is_not_a_tool_policy(self):
        async with Harness() as h:
            seen, start = _collect(h, topics.TOOL_REGISTERED)
            await start()
            bus = h.client("orchestration")
            service = Service()
            service._ctx = SimpleNamespace(bus=bus, logger=_Logger())  # noqa: SLF001
            forget_registered()
            try:
                await service._announce_crew_tools(service._ctx)  # noqa: SLF001
                await _until(lambda: len(seen) == len(TOOL_SPECS))
                for message in seen:
                    await service._on_tool_registered(message)  # noqa: SLF001
                from simorgh.orchestration.tools import _TOOL_POLICY, known_tools

                known = known_tools()
                policy = dict(_TOOL_POLICY)
                schemas = tool_schemas()
            finally:
                forget_registered()
        names = {m.payload["name"] for m in seen}
        self.assertEqual(names, set(TOOL_SPECS))
        for message in seen:
            validate(message)
            self.assertEqual(message.payload["input_schema"], TOOL_SPECS[message.payload["name"]]["input_schema"])
        self.assertEqual(schemas["spawn"], TOOL_SPECS["spawn"]["input_schema"], "the guardrails have them")
        self.assertFalse(names & set(known), "not an Execution tool in the known set")
        self.assertFalse(names & set(policy), "no read-only policy: await_agents must not batch with reads")

    def test_a_native_provider_is_handed_the_schema(self):
        """Cognition keeps a `tool.registered` schema and hands it to a
        native provider (`_offered_specs`): the path these now take."""
        from simorgh.cognition.service import Service as Cognition

        cognition = Cognition()
        for name, spec in TOOL_SPECS.items():
            asyncio.run(cognition._on_tool_registered(Message.new(  # noqa: SLF001
                topics.TOOL_REGISTERED, source="orchestration", payload={
                    "name": name, "version": "1", "description": spec["description"], "read_only": True,
                    "reversibility": "read_only", "schema_ref": "", "provider": "builtin",
                    "input_schema": spec["input_schema"]})))
        specs = cognition._offered_specs({"expected": "tool_calls", "tools": ["spawn", "await_agents"]})  # noqa: SLF001
        self.assertEqual(specs[0]["input_schema"]["required"], ["brief"])
        self.assertIn("mode", specs[1]["input_schema"]["properties"])


class OnlyAnOfferedCrewToolIsAnswered(unittest.TestCase):
    @run
    async def test_a_chat_turn_without_crews_cannot_ask_a_parent_even_with_the_guardrails_off(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "chat-1": [{"tool_calls": [_call(1, "ask_parent", question="which one?")]},
                           {"tool_calls": [_call(2, "spawn", brief="price of A", background=True)]},
                           {"text": "No."}]})
            await cognition.start()
            runner = _runner(h, ablate=("nudge", "steps"))
            outcome = await asyncio.wait_for(runner.run(_chat(), user_text="x"), timeout=30)
            await cognition.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        second, third = (_text(c) for c in cognition.calls["chat-1"][1:3])
        self.assertIn("Tool 'ask_parent' does not exist", second)
        self.assertIn("Tool 'spawn' does not exist", third)
        self.assertNotIn("chat-1", runner._crews, "nothing was spawned")  # noqa: SLF001

    @run
    async def test_a_voice_turn_is_not_answered_a_wait_it_was_not_offered(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "voice-1": [{"tool_calls": [_call(1, "await_agents", timeout_s=30)]}, {"text": "No."}]})
            await cognition.start()
            runner = _runner(h, chat_crews=True, ablate=("nudge",))
            await asyncio.wait_for(runner.run(_chat("voice-1", channel="voice", speaker="Soodeh"), user_text="x"),
                                   timeout=30)
            await cognition.stop()
        self.assertIn("Tool 'await_agents' does not exist", _text(cognition.calls["voice-1"][1]))

    @run
    async def test_with_the_guardrails_on_a_call_missing_its_brief_is_a_bad_args_nudge(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", agent="research")]}, {"text": "ok"}]})
            await cognition.start()
            runner = _runner(h)
            await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            await cognition.stop()
        self.assertIn("'brief' is required", _text(cognition.calls["t-root"][1]))

    @run
    async def test_the_flat_budget_keys_are_read(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="price of A", steps=4, budget_usd=0.05)]},
                           {"text": "ok"}], "*": [{"text": "A is 5.\n- a.md"}]})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h)
            await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            member = runner._crews["t-root"].members["t-root-h1"]  # noqa: SLF001
            await asyncio.wait_for(member.task, timeout=10)
            await cognition.stop(); await gx.stop()
        self.assertEqual((member.budget.steps, member.budget.usd), (4, 0.05))


# -- 2. Claude Code's dollars ---------------------------------------------------------------


class FakeClaudeCode:
    """Guardian and Execution for `claude_code_task`: answers with a result
    whose metadata blob carries the run's `cost_usd`, as the tool does."""

    def __init__(self, h, *, cost_usd: float) -> None:
        self._h = h
        self._bus = h.client("guardian")
        self.cost_usd = cost_usd
        self.proposals: list[dict] = []
        self._sub = None

    async def start(self):
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        p = message.payload
        self.proposals.append(dict(p))
        meta = {"status": "ok", "cost_usd": self.cost_usd} if p["tool"] == "claude_code_task" else {}
        ref = await self._h.ledger.put_blob(json.dumps(meta).encode(), content_type="application/json")
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": p["action_id"], "ok": True, "output_ref": "", "stdout_preview": "Claude Code ok",
            "duration_ms": 1, "side_effects": [], "metadata_ref": ref, "tool": p["tool"]}, source="execution"))


class ClaudeCodeSpendsTheCrewsDollars(unittest.TestCase):
    async def _crew(self, h, cost_usd, member_script):
        cognition = CrewCognition(h.client("cognition"), {
            "t-root": [{"tool_calls": [_call(1, "spawn", agent="claude_code", brief="add a helper")]},
                       {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                       {"text": "done"}],
            "t-root-h1": member_script})
        cc = FakeClaudeCode(h, cost_usd=cost_usd)
        await cognition.start(); await cc.start()
        runner = _runner(h, crew_max_usd=0.5)
        outcome = await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
        await cognition.stop(); await cc.stop()
        return runner._crews["t-root"], cc, outcome  # noqa: SLF001

    @run
    async def test_the_run_is_capped_at_the_crews_dollars_and_its_cost_ends_the_crew(self):
        async with Harness() as h:
            crew, cc, outcome = await self._crew(h, 0.6, [
                {"tool_calls": [{"tool": "claude_code_task", "args": {"feature": "a helper"}}]},
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x.py"}}]},
                {"text": "built it\n- x.py"}])
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        runs = [p for p in cc.proposals if p["tool"] == "claude_code_task"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["args"]["max_usd"], 0.5, "capped at what the crew had left")
        self.assertGreaterEqual(crew.spent_usd, 0.6)
        self.assertTrue(crew.exhausted.startswith("usd"), crew.exhausted)
        member = crew.members["t-root-h1"]
        self.assertEqual(member.cancel_reason, CREW_BUDGET)
        self.assertEqual(member.report.status, "partial")
        self.assertGreaterEqual(member.report.cost_usd, 0.6, "the report carries what Claude Code cost")
        self.assertFalse([p for p in cc.proposals if p["tool"] == "read_file"], "stopped once spent")

    def test_a_spent_crew_refuses_the_run_before_it_is_proposed(self):
        async def go():
            runner = SimpleNamespace()
            crew = Crew("t-root", max_usd=0.5)
            member = await crew.admit(parent="t-root", agent="claude_code", brief="x", depth=1,
                                      budget=crew.carve("t-root", MemberBudget(steps=4)))
            session = Session(task_id=member.handle, kind="patch", mode="execute", user_text="x",
                              profile=profiles.AGENTS["claude_code"], budget=Budget(max_steps=4),
                              crew_id="t-root")
            from simorgh.orchestration.session import SessionRunner

            runner._crews = {"t-root": crew}
            runner._crew_of = lambda s: SessionRunner._crew_of(runner, s)
            payload = {"args": {"feature": "x", "max_usd": 5}}
            first = SessionRunner._carve_claude_code(runner, session, payload)
            capped = payload["args"]["max_usd"]
            await crew.charge(member.handle, usd=0.5)
            second = SessionRunner._carve_claude_code(runner, session, {"args": {"feature": "x"}})
            return first, capped, second

        first, capped, second = asyncio.run(go())
        self.assertEqual((first, capped), ("", 0.5), "asking for more than is left gets what is left")
        self.assertIn("the crew budget is spent", second)


# -- 4. two people, end to end through a real Initiative ------------------------------------


class TheResultReachesWhoAsked(unittest.TestCase):
    @run
    async def test_soodehs_result_is_said_to_soodeh_and_saeeds_goes_to_his_phone(self):
        from simorgh.initiative.service import Service as Initiative

        async with Harness() as h:
            seen, start = _collect(h, topics.PERCEPT_TIME_SCHEDULED, topics.ACTION_PROPOSED)
            await start()
            # The house: Soodeh alone in the kitchen, Saeed in the office.
            world = h.client("worldmodel")

            async def answer(message):
                await world.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                    "ok": True, "facet": "home", "as_of": 0.0, "entities": [], "presence": {},
                    "situation": {"quiet_hours": False, "someone_asleep": False, "child_alone": False,
                                  "tv_playing": False, "nobody_home": False,
                                  "people": {"Soodeh": "kitchen", "Saeed": "office"}}})

            await world.subscribe(topics.WORLD_ENV_QUERY, answer)
            with tempfile.TemporaryDirectory() as tmp:
                initiative = Initiative(owner="Saeed")
                await initiative.start(Context(
                    name="initiative", instance_id="", run_id="t", mode="single", bus=h.client("initiative"),
                    ledger=h.ledger, config={}, secrets={}, clock=h.clock, logger=_Logger(), data_dir=Path(tmp)))
                cognition = CrewCognition(h.client("cognition"), {
                    "voice-s": [{"tool_calls": [_call(1, "spawn", brief="price of A", background=True)]},
                                {"text": "I'll find out."}],
                    "voice-m": [{"tool_calls": [_call(1, "spawn", brief="price of B", background=True)]},
                                {"text": "On it."}],
                    "voice-s-h1": _member_answer("A"), "voice-m-h1": _member_answer("B")}, delay={"*": 0.05})
                gx = FakeGuardianExecution(h.client("guardian"))
                await cognition.start(); await gx.start()
                runner = _runner(h, chat_crews=True)
                await asyncio.gather(
                    runner.run(_chat("voice-s", channel="voice", speaker="Soodeh"), user_text="x"),
                    runner.run(_chat("voice-m", channel="voice", speaker="Saeed"), user_text="y"))

                def offered():
                    return [m.payload for m in seen if m.type == topics.ACTION_PROPOSED
                            and m.payload.get("requester_channel") == "initiative"]

                await _until(lambda: len(offered()) == 2)
                await initiative.stop(); await cognition.stop(); await gx.stop()
        percepts = {m.payload["person"]: m.payload["label"] for m in seen if m.type == topics.PERCEPT_TIME_SCHEDULED}
        self.assertEqual(set(percepts), {"Soodeh", "Saeed"})
        self.assertIn("Dishwasher A", percepts["Soodeh"])
        self.assertIn("Dishwasher B", percepts["Saeed"])
        by_tool = {p["tool"]: p for p in offered()}
        self.assertEqual(set(by_tool), {"speak", "notify"})
        self.assertIn("Dishwasher A", by_tool["speak"]["args"]["text"], "said in Soodeh's room, to her")
        self.assertIn("Dishwasher B", by_tool["notify"]["args"]["body"], "the owner's phone has the owner's")
        self.assertNotIn("Dishwasher A", by_tool["notify"]["args"]["body"], "and never Soodeh's")


# -- 5. undelivered background reports survive a restart ------------------------------------


class AStopDoesNotLoseTheNotice(unittest.TestCase):
    @run
    async def test_a_report_filed_before_the_notice_went_is_delivered_once_after_a_restart(self):
        async with Harness() as h:
            seen, start = _collect(h, topics.UI_NOTICE, topics.PERCEPT_TIME_SCHEDULED)
            await start()
            cognition = CrewCognition(h.client("cognition"), {
                "voice-1": [{"tool_calls": [_call(1, "spawn", brief="price of A", background=True)]},
                            {"text": "I'll find out."}],
                "chat-1": [{"tool_calls": [_call(1, "spawn", brief="price of B", background=True)]},
                           {"text": "On it."}],
                "voice-1-h1": _member_answer("A"), "chat-1-h1": _member_answer("B")}, delay={"*": 0.05})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            first = _runner(h, chat_crews=True)

            async def stopped(crew):
                return None  # the process stopped between the report and the notice

            first._deliver_background = stopped  # noqa: SLF001
            await first.run(_chat("voice-1", channel="voice", speaker="Soodeh"), user_text="x")
            await first.run(_chat("chat-1"), user_text="y")
            for crew_id in ("voice-1", "chat-1"):
                await asyncio.wait_for(first._crews[crew_id].members[f"{crew_id}-h1"].task, timeout=10)  # noqa: SLF001
            await asyncio.sleep(0.1)
            self.assertEqual(seen, [], "nothing went before the stop")

            # A new process over the same ledger.
            second = _runner(h, chat_crews=True)
            delivered = await second.deliver_pending_background()
            await _until(lambda: len(seen) == 2)
            third = _runner(h, chat_crews=True)
            again = await third.deliver_pending_background()
            await asyncio.sleep(0.1)
            events = await h.ledger.read(crew_stream("voice-1"))
            await cognition.stop(); await gx.stop()
        self.assertEqual((delivered, again), (2, 0), "once, and never twice")
        self.assertEqual(len(seen), 2)
        spoken = next(m.payload for m in seen if m.type == topics.PERCEPT_TIME_SCHEDULED)
        self.assertEqual(spoken["person"], "Soodeh")
        self.assertIn("Dishwasher A", spoken["label"])
        typed = next(m.payload for m in seen if m.type == topics.UI_NOTICE)
        self.assertIn("Dishwasher B", typed["text"])
        records = [e.payload for e in events if e.type == topics.CREW_MESSAGE and e.payload["kind"] == DELIVERED_KIND]
        self.assertEqual([(r["from"], r["to"]) for r in records], [("voice-1-h1", "voice:Soodeh")])

    @run
    async def test_a_live_delivery_is_recorded_so_a_restart_does_not_repeat_it(self):
        async with Harness() as h:
            seen, start = _collect(h, topics.UI_NOTICE)
            await start()
            cognition = CrewCognition(h.client("cognition"), {
                "chat-1": [{"tool_calls": [_call(1, "spawn", brief="price of A", background=True)]},
                           {"text": "On it."}], "*": _member_answer("A")}, delay={"*": 0.05})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            await _runner(h, chat_crews=True).run(_chat(), user_text="x")
            await _until(lambda: seen)
            after_restart = await _runner(h, chat_crews=True).deliver_pending_background()
            await asyncio.sleep(0.1)
            await cognition.stop(); await gx.stop()
        self.assertEqual(after_restart, 0)
        self.assertEqual(len(seen), 1)

    def test_an_external_crew_is_never_turned_into_a_household_notice(self):
        async def go():
            events = []

            async def append(type_, payload):
                events.append(SimpleNamespace(type=type_, payload=dict(payload)))

            crew = Crew("crew-x", append=append)
            crew.external = True
            await crew.admit(parent="crew-x", agent="research", brief="x", depth=1,
                             budget=crew.carve("crew-x", MemberBudget(steps=3)),
                             background=True, requester="Soodeh", requester_channel="a2a")
            return Crew.fold("crew-x", events)

        self.assertTrue(asyncio.run(go()).external)


if __name__ == "__main__":
    unittest.main()
