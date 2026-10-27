"""Stage 18 items 3, 9 and 10's orchestration half (docs/plan/stage-18-agent-crews.md):

- chat and voice crews: `[orchestration] chat_crews`, `spawn{background}`,
  the report delivered to the person who asked through the paths that
  already reach a person (`ui.notice`; Initiative's reminder for voice),
  and into the conversation it was asked in;
- a remote agent as a member (`a2a:<name>`): one Guardian-gated
  `a2a_call`, progress from `a2a:calls`, `input-required` as an
  `ask_parent`, `cancel_agent` as `tasks/cancel`, a denial ending it;
- `crew.spawn` answered (the A2A server's request), and the caller's
  answers and cancels reaching the crew;
- `read_ref` reads only blobs the crew wrote itself.

Every model, Guardian and Execution here is a fake; nothing leaves the
process."""

from __future__ import annotations

import asyncio
import json
import time
import unittest
import uuid
from dataclasses import replace
from types import SimpleNamespace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.messages.crew import MemberBudget, Report
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.crew import Crew, render_background
from simorgh.orchestration.service import Service
from simorgh.orchestration.transcript import append_exchange, conversation_id, recent_lines
from simorgh.orchestration.worker import Worker

from .fakes import FakeGuardianExecution
from .harness import Harness, run
from .test_crews import CrewCognition, _call, _root, _runner, _text


def _chat(task_id="chat-1", *, channel="cli", speaker="", text="Compare dishwashers A, B and C."):
    profile = profiles.VOICE_CHAT if channel == "voice" else profiles.CHAT
    return Session(task_id=task_id, kind="chat", mode="execute", user_text=text, channel=channel, speaker=speaker,
                   profile=replace(profile, verify=False, max_steps=6), budget=Budget(max_steps=6))


def _collect(h, *types):
    seen: list[Message] = []

    async def on(message):
        seen.append(message)

    async def start():
        return [await h.client("observer").subscribe(t, on) for t in types]

    return seen, start


def _member_answer(x):
    return [{"tool_calls": [{"tool": "read_file", "args": {"path": f"{x}.md"}}]},
            {"text": f"Dishwasher {x} costs {ord(x) * 5}.\n- {x}.md lists it at {ord(x) * 5}"}]


async def _until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition never held")
        await asyncio.sleep(0.02)


class ChatCrews(unittest.TestCase):
    @run
    async def test_a_typed_compare_answers_at_once_and_the_report_arrives_as_one_notice(self):
        """The plan's item 3 acceptance: "compare A, B and C" with
        chat_crews on answers at once, and the report arrives as a notice
        with all three."""
        async with Harness() as h:
            seen, start = _collect(h, topics.UI_NOTICE, topics.PERCEPT_TIME_SCHEDULED)
            await start()
            # The conversation is going on: a turn a minute ago.
            await append_exchange(h.ledger, conversation_id("cli", ""), user_text="hi", answer="hello",
                                  who="User", ts=h.clock.now() - 60)
            cognition = CrewCognition(h.client("cognition"), {
                "chat-1": [{"tool_calls": [_call(i, "spawn", brief=f"price of dishwasher {x}", background=True)
                                           for i, x in enumerate("ABC")]},
                           {"text": "I'm on it -- I'll tell you when the three prices are in."}],
                "chat-1-h1": _member_answer("A"), "chat-1-h2": _member_answer("B"), "chat-1-h3": _member_answer("C"),
            }, delay={"chat-1": 0.0, "*": 0.3})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h, keep=False, chat_crews=True)
            outcome = await asyncio.wait_for(runner.run(_chat(), user_text="Compare A, B and C."), timeout=30)
            crew = runner._crews["chat-1"]  # noqa: SLF001
            reported_before_answer = [m.handle for m in crew.members.values() if m.report is not None]
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertIn("I'm on it", outcome.result_summary)
            self.assertFalse(seen, "nothing is delivered before the members report")
            await _until(lambda: seen)
            await asyncio.sleep(0.1)
            lines = await recent_lines(h.ledger, conversation_id("cli", ""), 5)
            await cognition.stop(); await gx.stop()
        self.assertEqual(reported_before_answer, [], "the turn answered before any member reported")
        self.assertEqual(len(crew.members), 3)
        self.assertEqual([m.type for m in seen], [topics.UI_NOTICE], "one notice, on the console's path")
        notice = seen[0].payload
        self.assertEqual(notice["source"], "crew")
        for x in "ABC":
            self.assertIn(f"price of dishwasher {x}", notice["text"])
            self.assertIn(f"Dishwasher {x} costs {ord(x) * 5}", notice["text"])
        self.assertTrue(any("Back from the background work" in line for line in lines),
                        "the result joined the conversation it was asked in")
        self.assertEqual(runner._crews, {}, "the crew is forgotten once delivered")  # noqa: SLF001

    @run
    async def test_an_old_conversation_gets_the_notice_but_not_the_line(self):
        async with Harness() as h:
            seen, start = _collect(h, topics.UI_NOTICE)
            await start()
            await append_exchange(h.ledger, conversation_id("cli", ""), user_text="hi", answer="hello",
                                  who="User", ts=h.clock.now() - 6 * 3600)
            cognition = CrewCognition(h.client("cognition"), {
                "chat-1": [{"tool_calls": [_call(1, "spawn", brief="price of A", background=True)]},
                           {"text": "On it."}],
                "*": _member_answer("A")})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h, chat_crews=True)
            await asyncio.wait_for(runner.run(_chat(), user_text="x"), timeout=30)
            await _until(lambda: seen)
            lines = await recent_lines(h.ledger, conversation_id("cli", ""), 5)
            await cognition.stop(); await gx.stop()
        self.assertFalse(any("Back from" in line for line in lines))

    @run
    async def test_off_by_default_spawn_is_not_offered_and_is_refused(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "chat-1": [{"tool_calls": [_call(1, "spawn", brief="price of A", background=True)]},
                           {"text": "I could not start that."}]})
            await cognition.start()
            runner = _runner(h)
            outcome = await asyncio.wait_for(runner.run(_chat(), user_text="x"), timeout=30)
            await cognition.stop()
        first = cognition.calls["chat-1"][0].payload
        self.assertNotIn("spawn", json.dumps(first.get("tools") or []))
        self.assertNotIn("chat-1", runner._crews)  # noqa: SLF001
        self.assertEqual(outcome.kind, "completed", outcome.reason)

    @run
    async def test_chat_may_start_only_read_only_agents_and_voice_only_in_the_background(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "chat-1": [{"tool_calls": [_call(1, "spawn", brief="fix the bug", agent="patch")]},
                           {"tool_calls": [_call(2, "spawn", brief="go elsewhere", agent="a2a:desk")]},
                           {"text": "No."}],
                "voice-1": [{"tool_calls": [_call(1, "spawn", brief="price of A")]},
                            {"text": "No."}]})
            await cognition.start()
            runner = _runner(h, chat_crews=True)
            await asyncio.wait_for(runner.run(_chat(), user_text="x"), timeout=30)
            await asyncio.wait_for(runner.run(_chat("voice-1", channel="voice", speaker="Soodeh"), user_text="x"),
                                   timeout=30)
            await cognition.stop()
        typed = [_text(c) for c in cognition.calls["chat-1"]]
        self.assertIn("only read-only agents (research, browser), not 'patch'", typed[1])
        self.assertIn("not 'a2a:desk'", typed[2])
        spoken = _text(cognition.calls["voice-1"][1])
        self.assertIn("a spoken turn starts work only in the background", spoken)
        voice_tools = json.dumps(cognition.calls["voice-1"][0].payload.get("tools") or [])
        self.assertIn("spawn", voice_tools)
        self.assertNotIn("await_agents", voice_tools, "a spoken turn is offered nothing that waits")

    @run
    async def test_a_spoken_request_reaches_its_person_through_initiative(self):
        """Voice: the report is Initiative's reminder for the person who
        asked -- which weighs quiet hours and the room -- never a notice
        printed for whoever is at the console, and never spoken directly."""
        async with Harness() as h:
            seen, start = _collect(h, topics.UI_NOTICE, topics.PERCEPT_TIME_SCHEDULED, topics.VOICE_SPEAK_REQUEST)
            await start()
            cognition = CrewCognition(h.client("cognition"), {
                "voice-1": [{"tool_calls": [_call(1, "spawn", brief="price of A", background=True)]},
                            {"text": "I'll find out."}],
                "*": _member_answer("A")}, delay={"*": 0.1})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h, chat_crews=True)
            await asyncio.wait_for(runner.run(_chat("voice-1", channel="voice", speaker="Soodeh"), user_text="x"),
                                   timeout=30)
            await _until(lambda: seen)
            await asyncio.sleep(0.1)
            member_proposals = [p.payload for p in gx.proposals if p.payload["task_id"] == "voice-1-h1"]
            await cognition.stop(); await gx.stop()
        self.assertEqual([m.type for m in seen], [topics.PERCEPT_TIME_SCHEDULED])
        p = seen[0].payload
        self.assertEqual(p["person"], "Soodeh")
        self.assertTrue(p["schedule_id"].startswith("crew:voice-1"))
        self.assertIn("Dishwasher A costs 325", p["label"])
        self.assertTrue(member_proposals)
        self.assertEqual({(x["requester"], x["requester_channel"]) for x in member_proposals}, {("Soodeh", "voice")},
                         "the member acted as the person who asked")

    @run
    async def test_a_cancelled_spoken_turn_leaves_its_background_work_running(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "voice-1": [{"tool_calls": [_call(1, "spawn", brief="price of A", background=True)]},
                            {"text": "On it."}],
                "*": _member_answer("A")}, delay={"*": 0.2, "voice-1": 0.0})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            cancelled = set()
            runner = _runner(h, chat_crews=True, is_cancelled=lambda t: t in cancelled)
            session = _chat("voice-1", channel="voice", speaker="Soodeh")
            original = runner._crew_tool  # noqa: SLF001

            async def spawn_then_cancel(s, call):
                result = await original(s, call)
                cancelled.add("voice-1")  # the person said the next thing
                return result

            runner._crew_tool = spawn_then_cancel  # noqa: SLF001
            outcome = await asyncio.wait_for(runner.run(session, user_text="x"), timeout=30)
            member = runner._crews["voice-1"].members["voice-1-h1"]  # noqa: SLF001
            await asyncio.wait_for(member.task, timeout=10)
            await cognition.stop(); await gx.stop()
        self.assertEqual(outcome.reason, "the task was cancelled")
        self.assertEqual(member.report.status, "ok")


class TheNoticeText(unittest.TestCase):
    def test_it_carries_conclusions_not_transcripts_and_stays_short_spoken(self):
        crew_members = []
        for x in "AB":
            m = SimpleNamespace(agent="research", status="done", job=f"price of {x}",
                                report=Report(status="ok", summary=f"{x} is 500.", findings=()))
            crew_members.append(m)
        text = render_background(crew_members)
        self.assertIn("price of A -- ok: A is 500.", text)
        spoken = render_background(crew_members, spoken=True)
        self.assertEqual(spoken, "What you asked me to look into: A is 500; B is 500.")


# -- remote members -------------------------------------------------------------------------


class FakeRemote:
    """Guardian and Execution for `a2a_call`, with a scripted remote agent
    behind it: writes the tool's status updates to `a2a:calls` (as
    `execution/a2a.py` does) and answers with a metadata blob."""

    def __init__(self, h, script, *, deny=False, unconfigured=False, hold_s=0.0):
        self._h = h
        self._bus = h.client("guardian")
        self.script = list(script)
        self.deny = deny
        self.unconfigured = unconfigured
        self.hold_s = hold_s
        self.proposals: list[dict] = []
        self.sent = 0
        self._sub = None

    async def start(self):
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _progress(self, handle, state, text):
        await self._h.ledger.append("a2a:calls", Event(
            stream="a2a:calls", type="progress", ts=self._h.clock.now(), trace_id="", causation_id=None,
            payload={"action_id": "x", "task": handle, "agent": "desk", "task_id": "r-1", "state": state,
                     "text": text}, idempotency_key=uuid.uuid4().hex))

    async def _on(self, message):
        p = message.payload
        self.proposals.append(dict(p))
        if self.deny:
            await self._bus.publish(message.caused(topics.ACTION_DENIED, {
                "action_id": p["action_id"], "reasons": ["household data may not leave"], "layer": "policy"},
                source="guardian"))
            return
        asyncio.ensure_future(self._run(message))

    async def _run(self, message):
        p = message.payload
        args, handle = p["args"], p["task_id"]
        meta: dict
        if self.unconfigured:
            await self._result(message, ok=False, error="a2a_call desk: needs `pip install a2a-sdk`",
                               kind="unconfigured", meta={"agent": "desk"})
            return
        if args.get("cancel"):
            await self._result(message, ok=True, out="desk: task r-1 is canceled",
                               meta={"agent": "desk", "task_id": "r-1", "state": "canceled"})
            return
        self.sent += 1
        step = self.script.pop(0) if self.script else {"state": "completed", "text": "done"}
        await self._progress(handle, "working", step.get("progress", "reading the reviews"))
        if self.hold_s:
            await asyncio.sleep(self.hold_s)
        meta = {"agent": "desk", "task_id": "r-1", "state": step["state"]}
        if step["state"] == "input-required":
            meta["question"] = step["text"]
        await self._result(message, ok=True, out=step["text"], meta=meta)

    async def _result(self, message, *, ok, out="", error="", kind="", meta=None):
        ref = await self._h.ledger.put_blob(json.dumps(meta or {}).encode(), content_type="application/json")
        payload = {"action_id": message.payload["action_id"], "ok": ok, "output_ref": "", "stdout_preview": out,
                   "duration_ms": 1, "side_effects": [], "metadata_ref": ref, "tool": "a2a_call"}
        if not ok:
            payload.update(error=error, error_kind=kind)
        await self._bus.publish(message.caused(topics.ACTION_RESULT, payload, source="execution"))


class RemoteMembers(unittest.TestCase):
    async def _crew(self, h, remote, root_script, *, member_text=None):
        cognition = CrewCognition(h.client("cognition"), {"t-root": root_script})
        await cognition.start(); await remote.start()
        runner = _runner(h)
        root = _root()
        root.speaker, root.channel = "Saeed", "cli"
        outcome = await asyncio.wait_for(runner.run(root, user_text="x"), timeout=30)
        await cognition.stop(); await remote.stop()
        return runner, outcome, cognition

    @run
    async def test_one_gated_call_progress_on_the_crew_and_the_answer_as_its_report(self):
        async with Harness() as h:
            seen, start = _collect(h, topics.CREW_MESSAGE)
            await start()
            remote = FakeRemote(h, [{"state": "completed", "text": "B is cheaper by $40."}])
            runner, outcome, cognition = await self._crew(h, remote, [
                {"tool_calls": [_call(1, "spawn", brief="which dishwasher is cheaper?", agent="a2a:desk",
                                      report="progress", data=["public"])]},
                {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                {"text": "B."}])
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertEqual(len(remote.proposals), 1)
        p = remote.proposals[0]
        self.assertEqual(p["tool"], "a2a_call")
        self.assertEqual(p["args"]["agent"], "desk")
        self.assertEqual(p["args"]["message"], "which dishwasher is cheaper?", "only the job leaves the house")
        self.assertEqual((p["requester"], p["requester_channel"]), ("Saeed", "cli"))
        member = runner._crews["t-root"].members["t-root-h1"]  # noqa: SLF001
        self.assertEqual(member.report.status, "ok")
        self.assertIn("B is cheaper by $40", member.report.summary)
        progress = [m.payload for m in seen if m.payload.get("kind") == "progress"]
        self.assertTrue(progress and "desk is working: reading the reviews" in progress[0]["body"], progress)
        self.assertIn("desk is working", _text(cognition.calls["t-root"][-1]), "progress reached the parent")

    @run
    async def test_input_required_is_an_ask_parent_and_the_answer_goes_back_on_the_same_task(self):
        async with Harness() as h:
            remote = FakeRemote(h, [{"state": "input-required", "text": "Which postcode?"},
                                    {"state": "completed", "text": "Delivery Tuesday."}])
            runner, outcome, cognition = await self._crew(h, remote, [
                {"tool_calls": [_call(1, "spawn", brief="delivery dates", agent="a2a:desk")]},
                {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                {"tool_calls": [_call(3, "send_agent", to="t-root-h1", kind="answer", text="SW1A 1AA")]},
                {"tool_calls": [_call(4, "await_agents", timeout_s=20)]},
                {"text": "Tuesday."}])
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertIn("desk asks: Which postcode?", _text(cognition.calls["t-root"][2]))
        second = remote.proposals[1]["args"]
        self.assertEqual((second["task_id"], second["message"]), ("r-1", "SW1A 1AA"))
        member = runner._crews["t-root"].members["t-root-h1"]  # noqa: SLF001
        self.assertIn("Delivery Tuesday", member.report.summary)

    @run
    async def test_cancel_agent_sends_tasks_cancel(self):
        async with Harness() as h:
            remote = FakeRemote(h, [{"state": "completed", "text": "late"}], hold_s=1.0)
            runner, outcome, _ = await self._crew(h, remote, [
                {"tool_calls": [_call(1, "spawn", brief="slow job", agent="a2a:desk")]},
                {"tool_calls": [_call(2, "cancel_agent", handle="t-root-h1", reason="not needed")]},
                {"tool_calls": [_call(3, "await_agents", timeout_s=20)]},
                {"text": "ok"}])
            member = runner._crews["t-root"].members["t-root-h1"]  # noqa: SLF001
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        cancels = [p["args"] for p in remote.proposals if p["args"].get("cancel")]
        self.assertEqual(cancels, [{"agent": "desk", "task_id": "r-1", "cancel": True}])
        self.assertEqual(member.report.status, "cancelled")

    @run
    async def test_a_guardian_denial_ends_it_and_nothing_more_is_proposed(self):
        async with Harness() as h:
            remote = FakeRemote(h, [], deny=True)
            runner, outcome, _ = await self._crew(h, remote, [
                {"tool_calls": [_call(1, "spawn", brief="send the calendar", agent="a2a:desk")]},
                {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                {"text": "It was refused."}])
        member = runner._crews["t-root"].members["t-root-h1"]  # noqa: SLF001
        self.assertEqual(len(remote.proposals), 1)
        self.assertEqual(remote.sent, 0)
        self.assertEqual(member.report.status, "blocked")
        self.assertIn("household data may not leave", member.report.summary)

    @run
    async def test_without_the_sdk_the_member_is_blocked_by_name(self):
        async with Harness() as h:
            remote = FakeRemote(h, [], unconfigured=True)
            runner, _, _ = await self._crew(h, remote, [
                {"tool_calls": [_call(1, "spawn", brief="anything", agent="a2a:desk")]},
                {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                {"text": "No SDK."}])
        member = runner._crews["t-root"].members["t-root-h1"]  # noqa: SLF001
        self.assertEqual(member.report.status, "blocked")
        self.assertIn("pip install a2a-sdk", member.report.summary)

    @run
    async def test_a_bad_remote_name_is_refused(self):
        async with Harness() as h:
            remote = FakeRemote(h, [])
            _, _, cognition = await self._crew(h, remote, [
                {"tool_calls": [_call(1, "spawn", brief="x", agent="a2a:../etc")]}, {"text": "no"}])
        self.assertIn("is not a remote agent's name", _text(cognition.calls["t-root"][1]))
        self.assertEqual(remote.proposals, [])


# -- crews from outside a session (`crew.spawn`) ----------------------------------------------


class CrewSpawnRequests(unittest.TestCase):
    async def _service(self, h):
        bus = h.client("orchestration")
        worker = Worker(bus, h.ledger, clock=h.clock.now, worker_id="w1", assemble_timeout_s=0.05,
                        think_timeout_s=30.0)
        service = Service()
        service._ctx = SimpleNamespace(bus=bus)  # noqa: SLF001
        service._workers = [worker]  # noqa: SLF001
        subs = [await bus.subscribe(topics.CREW_SPAWN, service._on_crew_spawn),  # noqa: SLF001
                await bus.subscribe(topics.CREW_MESSAGE, service._on_crew_message),  # noqa: SLF001
                await bus.subscribe(topics.CREW_CANCEL, service._on_crew_cancel)]  # noqa: SLF001
        return service, worker, subs

    async def _ask(self, h, **payload):
        caller = h.client("interface")
        base = {"agent": "research", "brief": "price of A", "requester": "Soodeh", "requester_channel": "a2a",
                "report": "progress", "background": True}
        base.update(payload)
        reply = await caller.request(Message.new(topics.CREW_SPAWN, source="interface", payload=base), timeout=5)
        return dict(reply.payload)

    @run
    async def test_an_empty_requester_channel_is_refused_and_nothing_runs(self):
        async with Harness() as h:
            _, worker, _ = await self._service(h)
            reply = await self._ask(h, requester_channel="")
        self.assertIs(reply["ok"], False)
        self.assertIn("requester_channel", reply["error"]["detail"])
        self.assertEqual(worker._runner._crews, {})  # noqa: SLF001

    @run
    async def test_a_writer_or_unknown_agent_is_refused(self):
        async with Harness() as h:
            await self._service(h)
            patch = await self._ask(h, agent="patch")
            nobody = await self._ask(h, agent="nobody")
        self.assertIn("read-only", patch["error"]["detail"])
        self.assertIn("no agent called 'nobody'", nobody["error"]["detail"])

    @run
    async def test_the_member_acts_as_the_caller_and_hears_the_callers_answer(self):
        async with Harness() as h:
            seen, start = _collect(h, topics.CREW_REPORT, topics.UI_NOTICE, topics.PERCEPT_TIME_SCHEDULED)
            await start()
            _, worker, _ = await self._service(h)
            cognition = CrewCognition(h.client("cognition"), {"*": [
                {"tool_calls": [_call(1, "ask_parent", question="which size?", timeout_s=10, default="large")]},
                {"tool_calls": [{"tool": "read_file", "args": {"path": "a.md"}}]},
                {"text": "A costs 500 in small.\n- a.md says so"}]})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            reply = await self._ask(h)
            crew_id, handle = reply["crew_id"], reply["handle"]
            crew = worker._runner._crews[crew_id]  # noqa: SLF001
            await _until(lambda: crew.questions.get(handle))
            # The A2A server's follow-up: from the root, seq 0, numbered here.
            await h.client("interface").publish(Message.new(topics.CREW_MESSAGE, source="interface", payload={
                "crew_id": crew_id, "from": crew_id, "to": handle, "kind": "answer", "body": "small",
                "refs": [], "seq": 0, "reply_to": crew.questions[handle]}))
            await _until(lambda: seen)
            proposals = [p.payload for p in gx.proposals]
            await cognition.stop(); await gx.stop()
        self.assertTrue(crew.external)
        self.assertEqual([m.type for m in seen], [topics.CREW_REPORT], "an A2A caller gets crew.report, no notice")
        self.assertEqual(seen[0].payload["report"]["status"], "ok")
        self.assertIn("your parent answered: small", _text(cognition.calls[handle][1]))
        self.assertEqual({(p["requester"], p["requester_channel"]) for p in proposals}, {("Soodeh", "a2a")})

    @run
    async def test_a_cancel_from_outside_reaches_the_member(self):
        async with Harness() as h:
            _, worker, _ = await self._service(h)
            cognition = CrewCognition(h.client("cognition"), {"*": [
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]}]}, delay={"*": 0.05})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            reply = await self._ask(h)
            crew = worker._runner._crews[reply["crew_id"]]  # noqa: SLF001
            member = crew.members[reply["handle"]]
            await h.client("interface").publish(Message.new(topics.CREW_CANCEL, source="interface", payload={
                "crew_id": reply["crew_id"], "handle": reply["handle"], "reason": "the caller cancelled"}))
            await asyncio.wait_for(member.task, timeout=10)
            await cognition.stop(); await gx.stop()
        self.assertEqual(member.report.status, "cancelled")
        self.assertEqual(member.cancel_reason, "the caller cancelled")


# -- read_ref ---------------------------------------------------------------------------------


class ReadRefReadsOnlyTheCrewsOwn(unittest.TestCase):
    @run
    async def test_a_hash_typed_into_a_report_is_not_readable_and_the_crews_own_overflow_is(self):
        async with Harness() as h:
            secret = await h.ledger.put_blob(b"somebody else's diary", content_type="text/plain")
            long_answer = "x" * 1500 + f"\n- see [ref: {secret}]"
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="dig")]},
                           {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                           {"tool_calls": [_call(3, "read_ref", ref=secret)]},
                           {"tool_calls": [_call(4, "read_ref", ref="__OVERFLOW__")]},
                           {"text": "done"}],
                "*": [{"text": long_answer}]})
            await cognition.start()
            runner = _runner(h)
            crew_box = {}
            original = runner._read_ref  # noqa: SLF001

            async def read_ref(session, args):
                if args.get("ref") == "__OVERFLOW__":
                    crew = runner._crews["t-root"]  # noqa: SLF001
                    args = {"ref": crew.members["t-root-h1"].report.artifacts[0]}
                    crew_box["overflow"] = args["ref"]
                return await original(session, args)

            runner._read_ref = read_ref  # noqa: SLF001
            outcome = await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            await cognition.stop()
            events = await h.ledger.read("crew:t-root")
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        crew = runner._crews["t-root"]  # noqa: SLF001
        self.assertIn(secret, crew.refs, "the member did name it")
        self.assertFalse(crew.readable(secret))
        refused = _text(cognition.calls["t-root"][3])
        self.assertIn("only a ref your crew wrote itself", refused)
        self.assertNotIn("diary", refused)
        self.assertIn("xxxx", _text(cognition.calls["t-root"][4]), "the crew's own overflow blob reads")
        report = next(e.payload for e in events if e.type == topics.CREW_REPORT)
        self.assertEqual(report["owned_refs"], [crew_box["overflow"]])
        # And a restart knows the same.
        folded = Crew.fold("t-root", events)
        self.assertTrue(folded.readable(crew_box["overflow"]))
        self.assertFalse(folded.readable(secret))

    def test_a_blob_brief_is_the_crews_own(self):
        async def go():
            crew = Crew("t")
            await crew.admit(parent="t", agent="research", brief="long", depth=1, budget=MemberBudget(),
                             brief_ref="blob-1")
            self.assertTrue(crew.readable("blob-1"))
            self.assertFalse(crew.readable(""))
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
