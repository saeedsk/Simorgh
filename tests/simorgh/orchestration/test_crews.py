"""Stage 18 item 2: agent crews -- members that run together, report in a
typed shape, talk over their inboxes, share one budget, and survive a
restart (docs/plan/stage-18-agent-crews.md, the item 2 acceptance list).

Every provider here is a fake with fixed delays: no model is called."""

from __future__ import annotations

import asyncio
import time
import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.messages.crew import MemberBudget, Report
from simorgh.contracts.registry import get_spec
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.crew import CREW_BUDGET, Crew, CrewRefused, Inbox, build_report, parse_report_text
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeGuardianExecution
from .harness import Harness, run


class CrewCognition:
    """Answers `cognition.think` per session (the think's trace id is the
    session's task id): a script per task id, the last reply repeating; a
    fixed delay and cost per call; every call kept with its timing.

    `together=n`: a session's first think waits until n sessions have
    thought, so n sessions that run at once all have a think in flight at
    the same instant whatever the machine's load, and sessions that run in
    turn never meet (`apart` is set once the generous ceiling passes).
    Sessions named in `alone` (a root whose think spawns the others) neither
    wait nor count."""

    def __init__(self, bus, scripts: dict, *, delay=None, cost=None, together: int = 0,
                 together_ceiling_s: float = 15.0, alone: tuple = ()) -> None:
        self._bus = bus
        self._scripts = scripts
        self._delay = delay or {}
        self._cost = cost or {}
        self.calls: dict[str, list] = {}
        self.spans: list[tuple[str, float, float]] = []
        self._sub = None
        self._together = together
        self._ceiling = together_ceiling_s
        self._alone = set(alone)
        self._met = asyncio.Event()
        self.apart = False

    async def start(self):
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self):
        if self._sub:
            await self._sub.unsubscribe()

    def _pick(self, table, task_id, default):
        for key in sorted(table, key=len, reverse=True):
            if task_id == key:
                return table[key]
        return table.get("*", default)

    async def _on(self, message):
        task_id = message.trace_id
        mine = self.calls.setdefault(task_id, [])
        mine.append(message)
        start = time.monotonic()
        if self._together and len(mine) == 1 and task_id not in self._alone:
            if len(set(self.calls) - self._alone) >= self._together:
                self._met.set()
            try:
                await asyncio.wait_for(self._met.wait(), self._ceiling)
            except asyncio.TimeoutError:
                self.apart = True
                self._met.set()
        delay = self._pick(self._delay, task_id, 0.0)
        if delay:
            await asyncio.sleep(delay)
        script = self._pick(self._scripts, task_id, [{"text": "done\n- nothing to add"}])
        step = script[min(len(mine) - 1, len(script) - 1)]
        if callable(step):
            step = step(message)
        self.spans.append((task_id, start, time.monotonic()))
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": step.get("text", ""), "tool_calls": step.get("tool_calls", []), "provider": "fake",
            "cost_usd": float(self._pick(self._cost, task_id, 0.0)), "tokens": 10, "floor": False,
            "non_answer": False})


def _root(task_id="t-root", text="Compare the three dishwashers."):
    return Session(task_id=task_id, kind="research", mode="execute", user_text=text,
                   profile=replace(profiles.RESEARCH, verify=False, max_steps=10), budget=Budget(max_steps=10))


def _call(i, tool, **args):
    return {"id": f"c{i}", "tool": tool, "args": args}


def _runner(h, *, keep=True, **kw):
    """`keep`: the crew stays in memory after the root ends, for the test
    to look at (the runner forgets it once nothing in it is running)."""
    kw.setdefault("delegation", True)
    kw.setdefault("think_timeout_s", 30.0)
    runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05, **kw)
    if keep:
        runner._forget_crew = lambda crew_id: None  # noqa: SLF001
    return runner


def _text(message) -> str:
    return "\n".join(str(m.get("content")) for m in message.payload["messages"])


CHILD = [{"tool_calls": [{"tool": "read_file", "args": {"path": "notes.md"}}]},
         {"text": "Dishwasher costs 500.\n- notes.md says 500"}]


class CrewsRunTogether(unittest.TestCase):
    async def _wall(self, parent_script, *, delay=0.15, together=0):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": parent_script, "*": CHILD}, delay={"*": delay, "t-root": 0.0},
                together=together, alone=("t-root",))
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h)
            root = _root()
            started = time.monotonic()
            outcome = await asyncio.wait_for(runner.run(root, user_text=root.user_text), timeout=30)
            wall = time.monotonic() - started
            await cognition.stop(); await gx.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        return wall, cognition, root, outcome

    @run
    async def test_three_read_only_members_beat_serial_by_far(self):
        spawned = [{"tool_calls": [_call(i, "spawn", brief=f"price of dishwasher {x}") for i, x in enumerate("ABC")]},
                   {"tool_calls": [_call(9, "await_agents", mode="all", timeout_s=20)]},
                   {"text": "All three cost 500."}]
        serial = [{"tool_calls": [_call(i, "delegate", job=f"price of dishwasher {x}") for i, x in enumerate("ABC")]},
                  {"text": "All three cost 500."}]
        # The three members meet at their first think (`together=3`): "by
        # far" as an order of events, since a wall-clock ratio went red on a
        # loaded machine. Delegated in turn, no two members' thinks overlap.
        _, cognition, root, _ = await self._wall(spawned, together=3)
        _, serial_cognition, _, _ = await self._wall(serial)
        self.assertFalse(cognition.apart, "the three members never had a think in flight together")
        firsts = [min(s for t, s, _ in cognition.spans if t == h) for h in ("t-root-h1", "t-root-h2", "t-root-h3")]
        first_end = min(e for t, _, e in cognition.spans if t != "t-root")
        self.assertLess(max(firsts), first_end, "a member waited for another to finish before it started")
        spans = sorted((s, e) for t, s, e in serial_cognition.spans if t != "t-root")
        self.assertEqual(len(spans), 6)
        self.assertTrue(all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:])),
                        "delegated members ran at once")
        last = _text(cognition.calls["t-root"][-1])
        for h in ("t-root-h1", "t-root-h2", "t-root-h3"):
            self.assertIn(f"{h} (research) ok", last)
        self.assertIn("notes.md says 500", last, "the typed report's findings came back")
        self.assertNotIn("Result of read_file", last, "a member's steps did not")
        # The wait was free: three spawns, the await given back, the answer.
        self.assertEqual(root.budget.steps_used, 2)

    @run
    async def test_writers_take_turns_and_readers_do_not_wait(self):
        async with Harness() as h:
            patch_child = [{"tool_calls": [{"tool": "read_file", "args": {"path": "a.py"}}]},
                           {"text": "Nothing to change.\n- a.py already does it"}]
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="fix a", agent="patch"),
                                           _call(2, "spawn", brief="fix b", agent="patch"),
                                           _call(3, "spawn", brief="look at c")]},
                           {"tool_calls": [_call(4, "await_agents", timeout_s=20)]},
                           {"text": "done"}],
                "*": patch_child}, delay={"*": 0.1, "t-root": 0.0},
                together=2, alone=("t-root",))   # the reader meets the first writer
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            root = _root()
            outcome = await asyncio.wait_for(_runner(h).run(root, user_text="x"), timeout=30)
            await cognition.stop(); await gx.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)

        def span(task):
            times = [(s, e) for t, s, e in cognition.spans if t == task]
            return min(s for s, _ in times), max(e for _, e in times)

        a, b, reader = span("t-root-h1"), span("t-root-h2"), span("t-root-h3")
        self.assertTrue(a[1] <= b[0] or b[1] <= a[0], f"two writers at once: {a} {b}")
        self.assertFalse(cognition.apart, "the reader did not run beside a writer")
        self.assertLess(reader[0], max(a[0], b[0]), "the reader waited for a writer")


class TheCrewBudget(unittest.TestCase):
    @run
    async def test_spent_out_cancels_every_member_and_the_root_gets_partial_reports(self):
        async with Harness() as h:
            loop = [{"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]}]
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="one"), _call(2, "spawn", brief="two")]},
                           {"tool_calls": [_call(3, "await_agents", timeout_s=20)]},
                           {"text": "Out of budget; here is what they found."}],
                "*": loop}, delay={"*": 0.02, "t-root": 0.0}, cost={"*": 0.02, "t-root": 0.0})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h, crew_max_usd=0.1, delegate_max_steps=40)
            root = _root()
            outcome = await asyncio.wait_for(runner.run(root, user_text="x"), timeout=30)
            await cognition.stop(); await gx.stop()
            events = await h.ledger.read("crew:t-root")
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        crew = runner._crews["t-root"]  # noqa: SLF001
        self.assertTrue(crew.exhausted.startswith("usd"), crew.exhausted)
        reports = [e.payload for e in events if e.type == topics.CREW_REPORT]
        self.assertEqual(sorted(r["handle"] for r in reports), ["t-root-h1", "t-root-h2"])
        self.assertEqual({r["report"]["status"] for r in reports}, {"partial"})
        self.assertEqual({m.status for m in crew.members.values()}, {"cancelled"})
        cancels = [e.payload for e in events if e.type == topics.CREW_CANCEL]
        self.assertTrue(cancels and all(c["reason"] == CREW_BUDGET for c in cancels))
        last = _text(cognition.calls["t-root"][-1])
        self.assertIn("crew budget ran out", last)

    def test_a_childs_budget_is_carved_from_what_is_left(self):
        async def go():
            clock = [0.0]
            crew = Crew("t", now=lambda: clock[0], max_usd=0.5, max_wall_s=100)
            first = await crew.admit(parent="t", agent="research", brief="a", depth=1,
                                     budget=crew.carve("t", MemberBudget(steps=5, usd=0.4)))
            self.assertEqual(first.budget.usd, 0.4)
            await crew.charge(first.handle, usd=0.3)
            clock[0] = 40.0
            second = crew.carve("t", MemberBudget(steps=5, usd=0.4))
            self.assertAlmostEqual(second.usd, 0.2)
            self.assertAlmostEqual(second.wall_s, 60.0)
            grandchild = crew.carve(first.handle, MemberBudget(steps=3))
            self.assertAlmostEqual(grandchild.usd, 0.1, msg="no more than the parent itself has left")
        asyncio.run(go())


class Cancelling(unittest.TestCase):
    def test_a_cancel_reaches_every_descendant_and_no_sibling(self):
        async def go():
            crew = Crew("t")
            a = await crew.admit(parent="t", agent="research", brief="a", depth=1, budget=MemberBudget())
            b = await crew.admit(parent="t", agent="research", brief="b", depth=1, budget=MemberBudget())
            a1 = await crew.admit(parent=a.handle, agent="research", brief="a1", depth=2, budget=MemberBudget())
            a11 = await crew.admit(parent=a1.handle, agent="research", brief="a11", depth=3, budget=MemberBudget())
            hit = await crew.cancel(a.handle, "enough")
            self.assertEqual(sorted(hit), sorted([a.handle, a1.handle, a11.handle]))
            self.assertFalse(crew.is_cancelled(b.handle))
            only = await crew.cancel(b.handle, "just b", cascade=False)
            self.assertEqual(only, [b.handle])
        asyncio.run(go())

    @run
    async def test_cancel_agent_stops_a_member_and_its_own_member(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="dig")]},
                           {"tool_calls": [_call(2, "cancel_agent", handle="t-root-h1", reason="found it myself")]},
                           {"tool_calls": [_call(3, "await_agents", timeout_s=20)]},
                           {"text": "done"}],
                "t-root-h1": [{"tool_calls": [_call(1, "spawn", brief="dig deeper")]},
                              {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                              {"text": "nothing"}],
                "*": [{"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]}],
            }, delay={"t-root": 0.3, "*": 0.05, "t-root-h1": 0.0})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h, delegate_max_steps=40)
            outcome = await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            crew = runner._crews["t-root"]  # noqa: SLF001
            grandchild = crew.members["t-root-h1-h1"]
            await asyncio.wait_for(grandchild.task, timeout=10)
            await cognition.stop(); await gx.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertEqual(crew.members["t-root-h1"].report.status, "cancelled")
        self.assertEqual(grandchild.report.status, "cancelled")
        self.assertEqual(grandchild.status, "cancelled")


class Talking(unittest.TestCase):
    @run
    async def test_ask_parent_gets_the_answer(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="convert the sizes")]},
                           {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                           {"tool_calls": [_call(3, "send_agent", to="t-root-h1", kind="answer", text="imperial")]},
                           {"tool_calls": [_call(4, "await_agents", timeout_s=20)]},
                           {"text": "done"}],
                "t-root-h1": [{"tool_calls": [_call(1, "ask_parent", question="metric or imperial?",
                                                    timeout_s=10, default="metric")]},
                              {"text": "Used imperial.\n- the parent said imperial"}],
            })
            await cognition.start()
            runner = _runner(h)
            outcome = await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            await cognition.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        root_saw = _text(cognition.calls["t-root"][2])
        self.assertIn("metric or imperial?", root_saw, "the question reached the parent")
        self.assertIn("your parent answered: imperial", _text(cognition.calls["t-root-h1"][1]))
        report = runner._crews["t-root"].members["t-root-h1"].report  # noqa: SLF001
        self.assertEqual(report.questions_unanswered, ())

    @run
    async def test_ask_parent_falls_back_to_the_default_on_timeout(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="convert the sizes")]},
                           {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                           {"tool_calls": [_call(3, "await_agents", timeout_s=20)]},
                           {"text": "done"}],
                "t-root-h1": [{"tool_calls": [_call(1, "ask_parent", question="metric or imperial?",
                                                    timeout_s=0.2, default="metric")]},
                              {"text": "Used metric, the default.\n- no answer came"}],
            })
            await cognition.start()
            runner = _runner(h)
            outcome = await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            await cognition.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertIn("go ahead with the default: metric", _text(cognition.calls["t-root-h1"][1]))
        report = runner._crews["t-root"].members["t-root-h1"].report  # noqa: SLF001
        self.assertEqual(report.questions_unanswered, ("metric or imperial?",))

    @run
    async def test_a_steer_changes_the_next_think_and_not_the_prefix(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="read the manual")]},
                           {"tool_calls": [_call(2, "send_agent", to="t-root-h1", text="look at chapter 3 instead")]},
                           {"tool_calls": [_call(3, "await_agents", timeout_s=20)]},
                           {"text": "done"}],
                "t-root-h1": CHILD}, delay={"t-root-h1": 0.3})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            outcome = await asyncio.wait_for(_runner(h).run(_root(), user_text="x"), timeout=30)
            await cognition.stop(); await gx.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        first, second = cognition.calls["t-root-h1"][:2]
        self.assertNotIn("chapter 3", _text(first))
        self.assertIn("chapter 3", _text(second), "the steer reached the member's next think")
        self.assertIn("(steer #", _text(second))
        # The cacheable prefix is byte-identical before and after the message:
        # the rules and every system block; the inbox is in the latest user turn.
        self.assertEqual(first.payload["task_rules"], second.payload["task_rules"])
        system = [[m for m in c.payload["messages"] if m["role"] == "system"] for c in (first, second)]
        self.assertEqual(system[0], system[1])
        self.assertEqual(first.payload["messages"][0], second.payload["messages"][0])
        self.assertNotIn("chapter 3", "\n".join(str(m["content"]) for m in second.payload["messages"][:-1]))

    @run
    async def test_progress_follows_the_report_policy(self):
        async with Harness() as h:
            member = [{"tool_calls": [_call(1, "report_progress", text="halfway")]},
                      {"tool_calls": [_call(2, "report_progress", text="found the manual", milestone=True)]},
                      {"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]},
                      {"text": "done.\n- x read"}]
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="a", report="milestones"),
                                           _call(2, "spawn", brief="b", report="every_steps:1"),
                                           _call(3, "spawn", brief="c", report="silent")]},
                           {"tool_calls": [_call(4, "await_agents", timeout_s=20)]},
                           {"text": "done"}],
                "*": member})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h)
            outcome = await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            await cognition.stop(); await gx.stop()
            events = await h.ledger.read("crew:t-root")
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        seen = _text(cognition.calls["t-root"][-1])
        self.assertIn("from t-root-h1 (milestone", seen)
        self.assertNotIn("from t-root-h1 (progress", seen, "`milestones` holds plain progress")
        self.assertIn("from t-root-h2 (progress", seen, "`every_steps:1` reports each step")
        self.assertNotIn("from t-root-h3", seen, "`silent` says nothing until asked")
        recorded = {e.payload["from"] for e in events if e.type == topics.CREW_MESSAGE}
        self.assertIn("t-root-h3", recorded, "held progress is still on the stream")


class Durability(unittest.TestCase):
    @run
    async def test_a_restart_mid_crew_resumes_and_the_root_gets_every_report(self):
        async with Harness() as h:
            first = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="fast one"), _call(2, "spawn", brief="slow one")]},
                           {"tool_calls": [_call(3, "await_agents", timeout_s=60)]}],
                "t-root-h1": [{"text": "Fast: 400.\n- from the fast source"}],
                "t-root-h2": [{"text": "never said"}]}, delay={"t-root-h2": 30.0})
            await first.start()
            runner = _runner(h)
            root_run = asyncio.ensure_future(runner.run(_root(), user_text="x"))
            for _ in range(500):
                await asyncio.sleep(0.02)
                crew = runner._crews.get("t-root")  # noqa: SLF001
                waiting = [e for e in await h.ledger.read("crew:t-root")
                           if e.type == "crew.member.status" and e.payload["handle"] == "t-root"]
                if crew and crew.members["t-root-h1"].report and waiting:
                    break
            # The process stops: nothing files a report, nothing says goodbye.
            root_run.cancel()
            crew.members["t-root-h2"].task.cancel()
            await asyncio.gather(root_run, crew.members["t-root-h2"].task, return_exceptions=True)
            await first.stop()

            second = CrewCognition(h.client("cognition2"), {
                "t-root": [{"text": "Fast is 400 and slow is 450."}],
                "t-root-h2": [{"text": "Slow: 450.\n- from the slow source"}]})
            await second.start()
            again = _runner(h)
            outcome = await asyncio.wait_for(again.run(_root(), user_text="x"), timeout=30)
            await second.stop()
            events = await h.ledger.read("crew:t-root")
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertEqual(len(second.calls["t-root"]), 1, "the root re-entered its wait, not its work")
        seen = _text(second.calls["t-root"][0])
        self.assertIn("from the fast source", seen, "the report filed before the stop")
        self.assertIn("from the slow source", seen, "the member that was resumed")
        self.assertEqual(len([e for e in events if e.type == topics.CREW_SPAWNED]), 2, "nobody spawned twice")
        folded = Crew.fold("t-root", events)
        self.assertEqual({m.status for m in folded.members.values()}, {"done"})


class Reports(unittest.TestCase):
    def test_the_brief_shape_parses_into_summary_and_findings(self):
        summary, findings, _ = parse_report_text(
            "It was released in 2009.\n- discography.md line 12 [ref: blob-1]\n- the label says so")
        self.assertEqual(summary, "It was released in 2009.")
        self.assertEqual([f.claim for f in findings], ["discography.md line 12", "the label says so"])
        self.assertEqual(findings[0].evidence_ref, "blob-1")

    def test_json_parses_too(self):
        summary, findings, artifacts = parse_report_text(
            '```json\n{"summary": "ok", "findings": [{"claim": "a"}], "artifacts": ["r1"]}\n```')
        self.assertEqual((summary, [f.claim for f in findings], artifacts), ("ok", ["a"], ["r1"]))

    def test_an_unparsed_answer_is_cut_and_the_rest_is_a_blob(self):
        blobs = {}

        async def put(data):
            blobs["r"] = data
            return "r"

        report = asyncio.run(build_report("x" * 3000, status="ok", put_blob=put))
        self.assertEqual(len(report.summary), 1200)
        self.assertEqual(report.artifacts, ("r",))
        self.assertEqual(len(blobs["r"]), 3000)

    def test_payloads_validate_against_the_contract(self):
        async def go():
            seen = []

            async def append(type_, payload):
                seen.append((type_, payload))

            crew = Crew("t", append=append)
            m = await crew.admit(parent="t", agent="research", brief="b", depth=1, budget=MemberBudget(steps=3))
            await crew.send(m.handle, "t", "progress", "half")
            await crew.file_report(m.handle, Report(status="ok", summary="s"))
            return seen
        seen = asyncio.run(go())
        checked = 0
        for type_, payload in seen:
            if type_ in (topics.CREW_SPAWNED, topics.CREW_MESSAGE, topics.CREW_REPORT):
                self.assertEqual(get_spec(type_).validate(payload), [], type_)
                checked += 1
        self.assertEqual(checked, 3)

    def test_the_member_cap_and_a_writer_under_a_writer_are_refused(self):
        async def go():
            crew = Crew("t", max_members=2)
            w = await crew.admit(parent="t", agent="patch", brief="a", depth=1, budget=MemberBudget(), writer=True)
            with self.assertRaises(CrewRefused):
                await crew.admit(parent=w.handle, agent="patch", brief="b", depth=2, budget=MemberBudget(), writer=True)
            await crew.admit(parent="t", agent="research", brief="c", depth=1, budget=MemberBudget())
            with self.assertRaises(CrewRefused):
                await crew.admit(parent="t", agent="research", brief="d", depth=1, budget=MemberBudget())
        asyncio.run(go())

    def test_the_inbox_hands_back_one_answer_and_keeps_the_rest(self):
        async def go():
            box = Inbox()
            box.put({"kind": "note", "seq": 1})
            box.put({"kind": "answer", "seq": 2, "reply_to": 7})
            self.assertEqual(box.take_answer(7)["seq"], 2)
            self.assertEqual([m["seq"] for m in box.drain()], [1])
        asyncio.run(go())


class DelegateAsBefore(unittest.TestCase):
    @run
    async def test_delegate_is_a_crew_member_with_the_old_report_line(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [{"tool": "delegate", "args": {"job": "find the year", "steps": 4}}]},
                           {"text": "2009."}],
                "t-root-h1": [{"text": "It was 2009.\n- the liner notes"}]})
            await cognition.start()
            root = _root()
            runner = _runner(h, keep=False)
            outcome = await asyncio.wait_for(runner.run(root, user_text="x"), timeout=30)
            await cognition.stop()
            events = await h.ledger.read("crew:t-root")
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertEqual(runner._crews, {}, "a finished crew is not kept in memory")  # noqa: SLF001
        self.assertTrue(root.steps[0].summary.startswith("Helper t-root-h1 (completed, 1 steps): It was 2009."))
        spawned = [e.payload for e in events if e.type == topics.CREW_SPAWNED]
        self.assertEqual((spawned[0]["via"], spawned[0]["budget"]), ("delegate", {"steps": 4}))
        child_tools = cognition.calls["t-root-h1"][0].payload["tools"]
        self.assertNotIn("ask_parent", child_tools, "a delegate helper is offered what it always was")


class TheConfigReachesTheCrew(unittest.TestCase):
    @run
    async def test_the_crew_keys_reach_the_runner(self):
        from simorgh.orchestration.config import Config
        from simorgh.orchestration.worker import Worker

        config = Config.from_mapping({"crew_max_members": 3, "crew_max_writers": 2, "crew_max_usd": 0.2,
                                      "crew_max_wall_s": 60, "crew_max_tokens": 900, "max_children_concurrent": 2})
        self.assertEqual(config.problems, ())
        async with Harness() as h:
            worker = Worker(h.client("orchestration"), h.ledger, max_children=config.max_children_concurrent,
                            crew_limits=(config.crew_max_members, config.crew_max_writers, config.crew_max_usd,
                                         config.crew_max_wall_s, config.crew_max_tokens))
        self.assertEqual(worker._runner._crew_limits, {  # noqa: SLF001
            "max_members": 3, "max_concurrent": 2, "max_writers": 2, "max_usd": 0.2, "max_wall_s": 60.0,
            "max_tokens": 900})
        self.assertEqual(Config().crew_max_usd, 0.5)


class ReviewFindings(unittest.TestCase):
    """What the stage 18 item 2 review found: each was a way past one of
    the plan's "What this must never do" lines."""

    @run
    async def test_an_await_on_members_already_done_costs_its_step(self):
        # Before: every await gave its step back, so a model that awaited
        # finished members again and again thought for ever, free.
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="one")]},
                           {"tool_calls": [_call(2, "await_agents", timeout_s=20)]},
                           {"tool_calls": [_call(3, "await_agents", timeout_s=20)]}],
                "*": [{"text": "One.\n- found it"}]})
            await cognition.start()
            root = _root()
            outcome = await asyncio.wait_for(_runner(h).run(root, user_text="x"), timeout=30)
            await cognition.stop()
        self.assertNotEqual(outcome.kind, "completed")
        self.assertEqual(root.budget.steps_used, root.budget.max_steps, "the step budget ended it")
        self.assertLessEqual(len(cognition.calls["t-root"]), root.budget.max_steps + 2)

    @run
    async def test_ask_parent_does_not_sleep_past_the_crews_wall_clock(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="ask")]},
                           {"tool_calls": [_call(2, "read_file", path="x")]},
                           {"text": "done"}],
                "t-root-h1": [{"tool_calls": [_call(1, "ask_parent", question="which?", timeout_s=600,
                                                    default="the first")]},
                              {"text": "Took the first.\n- no answer came"}]})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h, crew_max_wall_s=0.5)
            started = time.monotonic()
            await asyncio.wait_for(runner.run(_root(), user_text="x"), timeout=30)
            member = runner._crews["t-root"].members["t-root-h1"]  # noqa: SLF001
            await asyncio.wait_for(member.task, timeout=20)
            await cognition.stop(); await gx.stop()
        self.assertLess(time.monotonic() - started, 10, "the 600 s ask was cut to the crew's 0.5 s")
        self.assertEqual(member.report.status, "partial", "the wall-clock ran out: a typed partial")

    @run
    async def test_delegate_is_not_cut_by_crew_bounds_it_never_asked_for(self):
        # Before: a task's ninth delegate was refused by `crew_max_members`,
        # and a helper was cancelled by `crew_max_usd` -- neither existed.
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [{"tool": "delegate", "args": {"job": "first"}}]},
                           {"tool_calls": [{"tool": "delegate", "args": {"job": "second"}}]},
                           {"text": "both done"}],
                "*": [{"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]},
                      {"text": "Done.\n- read x"}]}, cost={"*": 0.05, "t-root": 0.0})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            root = _root()
            runner = _runner(h, crew_max_members=1, crew_max_usd=0.01)
            outcome = await asyncio.wait_for(runner.run(root, user_text="x"), timeout=30)
            await cognition.stop(); await gx.stop()
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertTrue(root.steps[0].summary.startswith("Helper t-root-h1 (completed, 2 steps)"), root.steps[0].summary)
        self.assertTrue(root.steps[1].summary.startswith("Helper t-root-h2 (completed, 2 steps)"), root.steps[1].summary)
        crew = runner._crews["t-root"]  # noqa: SLF001
        self.assertEqual(crew.exhausted, "")
        self.assertIsNone(crew.started, "a delegate-only crew has no wall-clock running")

    @run
    async def test_a_cancelled_root_takes_its_crew_with_it(self):
        cancelled: set = set()
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {
                "t-root": [{"tool_calls": [_call(1, "spawn", brief="dig")]},
                           {"tool_calls": [_call(2, "read_file", path="x")]}],
                "t-root-h1": [{"tool_calls": [_call(1, "spawn", brief="dig deeper")]},
                              {"tool_calls": [_call(2, "ask_parent", question="deeper?", timeout_s=60)]}],
                "*": [{"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]}],
            }, delay={"*": 0.05, "t-root": 0.3, "t-root-h1": 0.0})
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = _runner(h, delegate_max_steps=40, is_cancelled=lambda task_id: task_id in cancelled)
            root_run = asyncio.ensure_future(runner.run(_root(), user_text="x"))
            for _ in range(300):
                await asyncio.sleep(0.02)
                crew = runner._crews.get("t-root")  # noqa: SLF001
                if crew and "t-root-h1-h1" in crew.members and crew.members["t-root-h1"].status == "waiting":
                    break
            cancelled.add("t-root")  # `task.cancel` names the root only
            started = time.monotonic()
            outcome = await asyncio.wait_for(root_run, timeout=20)
            for handle in ("t-root-h1", "t-root-h1-h1"):
                await asyncio.wait_for(crew.members[handle].task, timeout=20)
            await cognition.stop(); await gx.stop()
        self.assertEqual(outcome.reason, "the task was cancelled")
        self.assertLess(time.monotonic() - started, 15, "the member asleep in ask_parent woke")
        for handle in ("t-root-h1", "t-root-h1-h1"):
            self.assertEqual(crew.members[handle].report.status, "cancelled", handle)

    def test_a_report_filed_before_a_stop_is_not_run_again(self):
        async def go():
            events = []

            async def append(type_, payload):
                events.append(type("E", (), {"type": type_, "payload": dict(payload)})())

            crew = Crew("t", append=append)
            m = await crew.admit(parent="t", agent="research", brief="b", depth=1, budget=MemberBudget(steps=3))
            await crew.set_status(m.handle, "running")
            await crew.file_report(m.handle, Report(status="ok", summary="s"))
            # The process stopped between the report and its status event.
            return [e for e in events if not (e.type == "crew.member.status" and e.payload["status"] == "done")]
        folded = Crew.fold("t", asyncio.run(go()))
        self.assertEqual(folded.members["t-h1"].status, "done")
        self.assertEqual(folded.live(), [], "nothing for a restart to run twice")

    @run
    async def test_a_resumed_member_still_acts_for_the_person_who_asked(self):
        async with Harness() as h:
            runner = _runner(h)
            root = _root()
            root.speaker, root.channel = "Ira", "voice"
            crew = await runner._crew_for(root)  # noqa: SLF001
            member = await crew.admit(parent=root.task_id, agent="research", brief="b", depth=1,
                                      budget=MemberBudget(steps=3), requester=root.speaker,
                                      requester_channel=root.channel)
            events = await h.ledger.read("crew:t-root")
            folded = Crew.fold("t-root", events)
            again = folded.members[member.handle]
            child = runner._member_session(None, again, profiles.RESEARCH)  # noqa: SLF001
        self.assertEqual((child.speaker, child.channel), ("Ira", "voice"),
                         "not the owner's console after a restart")


if __name__ == "__main__":
    unittest.main()
