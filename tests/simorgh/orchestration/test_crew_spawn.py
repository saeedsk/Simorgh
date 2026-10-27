"""`crew.spawn` answered (stage 18 items 4 and 10): a member started from
outside any session, and a project's plan nodes running as one crew.

The last case is item 4's acceptance end to end: Planning with
`project_crews` on and Orchestration's real Service on one bus, a three-node
independent plan, fake providers with a fixed delay per node. Nothing here
calls a model."""

from __future__ import annotations

import asyncio
import time
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.orchestration.config import Config
from simorgh.orchestration.crew import CrewRefused
from simorgh.orchestration.service import Service as OrchestrationService
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeGuardianExecution, FakeVerification
from .harness import Harness, run
from .test_crews import CHILD, CrewCognition


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


def _ctx(h: Harness, name: str, config=None) -> Context:
    return Context(name=name, instance_id="", run_id="test", mode="single", bus=h.client(name), ledger=h.ledger,
                   config=config or {}, secrets={}, clock=h.clock, logger=_Logger(), data_dir=Path("."))


def _node(handle: str, brief: str, **kw) -> dict:
    return {"agent": "research", "brief": brief, "requester": "", "requester_channel": "planning",
            "context_id": "proj-1", "handle": handle, "plan_node": True, **kw}


class SpawnDetached(unittest.TestCase):
    @run
    async def test_plan_nodes_run_together_as_one_crew_under_their_own_handles(self):
        async with Harness() as h:
            cognition = CrewCognition(h.client("cognition"), {"*": CHILD},
                                      delay={"node-a": 0.15, "node-b": 0.25, "node-c": 0.2}, together=3)
            gx = FakeGuardianExecution(h.client("guardian"))
            verify = FakeVerification(h.client("verification"))
            for f in (cognition, gx, verify):
                await f.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now,
                                   assemble_timeout_s=0.05, think_timeout_s=30.0)
            reports = {}
            done = asyncio.Event()

            async def _report(message):
                reports[message.payload["handle"]] = (message.payload["report"], time.monotonic())
                if len(reports) == 3:
                    done.set()
            await h.client("planning").subscribe(topics.CREW_REPORT, _report)
            got = [await runner.spawn_detached(_node(f"node-{x}", f"find the {x} day",
                                                     acceptance=[f"the {x} day is named"]), plan_node=True)
                   for x in "abc"]
            await asyncio.wait_for(done.wait(), 20)
            for f in (cognition, gx, verify):
                await f.stop()
            events = await h.ledger.read("crew:proj-1")
            subjects = [(await h.ledger.get_blob(r.payload["subject_ref"])).decode("utf-8")
                        for r in verify.requests]
        self.assertEqual(got, [("proj-1", "node-a"), ("proj-1", "node-b"), ("proj-1", "node-c")])
        self.assertEqual({r["status"] for r, _ in reports.values()}, {"ok"})
        # Together, not in turn: every node's first think was in flight at
        # once (`together=3`), which a load-free wall bound only implied.
        self.assertFalse(cognition.apart, "the nodes did not run together")
        firsts = [min(s for t, s, _ in cognition.spans if t == x) for x in ("node-a", "node-b", "node-c")]
        first_end = min(e for _, _, e in cognition.spans)
        self.assertLess(max(firsts), first_end, "a node waited for another to finish before it started")
        spawned = [e.payload for e in events if e.type == topics.CREW_SPAWNED]
        self.assertEqual({p["via"] for p in spawned}, {"project"})
        self.assertEqual({p["parent"] for p in spawned}, {"proj-1"})
        # Verified, as the queued task would have been, against its criteria.
        self.assertEqual(len(verify.requests), 3)
        self.assertTrue(any("the a day is named" in text for text in subjects), subjects[0][:400])
        # The node's own stream holds its steps, as when a Worker ran it.
        streams = {e.stream for e in await h.ledger.read("task:node-a")}
        self.assertEqual(streams, {"task:node-a"})

    @run
    async def test_a_node_is_outside_the_crews_dollar_and_member_bounds(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now,
                                   assemble_timeout_s=0.05, crew_max_members=1, crew_max_usd=0.0001)
            runner._start_member = lambda *a, **k: None  # noqa: SLF001 -- admission only
            for i in range(3):
                await runner.spawn_detached(_node(f"n{i}", "x"), plan_node=True)
            crew = runner._crews["proj-1"]  # noqa: SLF001
            self.assertEqual(len(crew.members), 3)
            await crew.charge("n0", usd=1.0)
            self.assertEqual(crew.exhausted, "")

    @run
    async def test_refusals(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05)
            with self.assertRaises(ValueError):
                await runner.spawn_detached({"agent": "nobody", "brief": "x", "requester": "", "requester_channel": "a2a"})
            with self.assertRaises(ValueError):
                await runner.spawn_detached({"agent": "research", "brief": "x", "requester": "Ira",
                                             "requester_channel": ""})
            gate = asyncio.Event()

            async def hold(*a, **k):
                await gate.wait()
            runner.run = hold  # the member stays running
            await runner.spawn_detached(_node("n1", "x"), plan_node=True)
            with self.assertRaises(CrewRefused):
                await runner.spawn_detached(_node("n1", "x"), plan_node=True)
            gate.set()


class TheServiceAnswers(unittest.TestCase):
    @run
    async def test_who_may_ask_for_what(self):
        async with Harness() as h:
            service = OrchestrationService(Config(workers=1, metrics_interval_s=0))
            await service.start(_ctx(h, "orchestration"))
            for w in service._workers:  # noqa: SLF001 -- admission only, no member runs
                w._runner._start_member = lambda *a, **k: None  # noqa: SLF001

            async def ask(source, payload):
                reply = await h.client(source).request(Message.new(topics.CREW_SPAWN, source=source,
                                                                   payload=payload), timeout=2.0)
                return reply.payload

            ok = await ask("planning", _node("n1", "find it"))
            self.assertEqual(ok, {"crew_id": "proj-1", "handle": "n1"})
            forged = await ask("interface", _node("n2", "find it"))
            self.assertIs(forged.get("ok"), False)
            self.assertIn("only Planning", forged["error"]["detail"])
            a2a = await ask("interface", {"agent": "research", "brief": "look", "requester": "Ira",
                                          "requester_channel": "a2a", "background": True})
            self.assertTrue(a2a["crew_id"].startswith("crew-"))
            self.assertTrue(a2a["handle"].startswith(a2a["crew_id"] + "-h"))
            console = await ask("interface", {"agent": "research", "brief": "look", "requester": "",
                                              "requester_channel": ""})
            self.assertIs(console.get("ok"), False)
            await service.stop()


class AThreeNodeProjectEndToEnd(unittest.TestCase):
    """Stage 18 item 4's acceptance: Planning and Orchestration together,
    the same three-node plan run on a crew and on the queue (one Worker)."""

    DELAYS = {"bin": 0.2, "recycling": 0.4, "garden": 0.3}   # per think; each node thinks twice

    async def _run_project(self, *, crews: bool):
        from simorgh.planning import planmode
        from simorgh.planning.config import Config as PlanningConfig
        from simorgh.planning.model import AVAILABLE, Step
        from simorgh.planning.service import Service as PlanningService

        async with Harness() as h:
            planning = PlanningService(PlanningConfig(project_crews=crews))
            await planning.start(_ctx(h, "planning"))
            orchestration = OrchestrationService(Config(workers=1, metrics_interval_s=0, worktrees=False))
            await orchestration.start(_ctx(h, "orchestration"))
            delays = {}
            # On a crew the three nodes meet at their first think; on the
            # queue's one Worker they cannot, so nothing waits there.
            cognition = CrewCognition(h.client("cognition"), {"*": CHILD}, delay=delays,
                                      together=3 if crews else 0)
            gx = FakeGuardianExecution(h.client("guardian"))
            verify = FakeVerification(h.client("verification"))
            for f in (cognition, gx, verify):
                await f.start()
            finished = asyncio.Event()
            outcome = {}

            async def _done(message):
                outcome["type"], outcome["payload"] = message.type, dict(message.payload)
                finished.set()
            await h.client("interface").subscribe(topics.PROJECT_COMPLETED, _done)
            await h.client("interface").subscribe(topics.PROJECT_FAILED, _done)

            store = planning._store  # noqa: SLF001
            project = await store.create(kind="project", description="sort the bins", origin="human",
                                         mode="plan", initial_status=AVAILABLE)
            steps = [Step(f"s{i}", "research", f"find the {x} collection day") for i, x in
                     enumerate(self.DELAYS)]
            state = planmode.PlanState(plan_id="p1", task_id=project.id, goal="sort the bins", steps=steps,
                                       risk="low")
            planning._plans["p1"] = state  # noqa: SLF001
            planning._plan_by_task[project.id] = "p1"  # noqa: SLF001
            original = store.create

            async def create(**kw):
                task = await original(**kw)
                if kw.get("parent_id") == project.id:
                    delays[task.id] = self.DELAYS[kw["description"].split()[2]]
                return task
            store.create = create
            await planning._approve_plan(state, approved_by="auto")  # noqa: SLF001
            await asyncio.wait_for(finished.wait(), 30)
            children = store.children(project.id)
            for f in (cognition, gx, verify):
                await f.stop()
            await orchestration.stop()
            await planning.stop()
        return outcome, children, cognition

    @run
    async def test_it_finishes_in_about_the_time_of_its_longest_node(self):
        from simorgh.planning.model import COMPLETED

        outcome, children, cognition = await self._run_project(crews=True)
        queue_outcome, queue_children, queue_cognition = await self._run_project(crews=False)
        self.assertEqual(outcome["type"], topics.PROJECT_COMPLETED, outcome)
        self.assertEqual(outcome["payload"]["done"], 3)
        self.assertEqual(queue_outcome["type"], topics.PROJECT_COMPLETED, queue_outcome)
        self.assertEqual({c.status for c in children}, {COMPLETED})
        # "About the time of its longest node" holds because the three run at
        # once. That is asserted as an order of events, not a wall-clock
        # bound: a loaded machine (the core tier under -n auto) turned the
        # bound red. The measured times are in stage 18 item 4's note.
        self.assertFalse(cognition.apart, "the crew's nodes never had a think in flight together")
        self.assertEqual(sorted(cognition.calls), sorted(c.id for c in children),
                         "every think was a node's own, under its task id")
        firsts = sorted(min(s for t, s, _ in cognition.spans if t == c.id) for c in children)
        first_end = min(max(e for t, _, e in cognition.spans if t == c.id) for c in children)
        self.assertLess(firsts[-1], first_end, "a node waited for another to finish before it started")
        # The queue's one Worker ran the same three nodes in turn.
        self.assertEqual(len(queue_children), 3)
        spans = sorted((s, e) for _, s, e in queue_cognition.spans)
        self.assertTrue(all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:])),
                        "the queue's one Worker had two thinks in flight")

class ReviewFindings(unittest.TestCase):
    """The stage 18 item 4 review (2026-10-27)."""

    @run
    async def test_a_plan_node_keeps_the_per_attempt_limits_a_claimed_task_has(self):
        async with Harness() as h:
            service = OrchestrationService(Config(workers=1, metrics_interval_s=0, attempt_max_tokens=900,
                                                  attempt_max_usd=0.25, attempt_max_wall_s=120.0))
            await service.start(_ctx(h, "orchestration"))
            children = []
            for w in service._workers:  # noqa: SLF001 -- admission only
                w._runner._start_member = lambda crew, member, child, *a: children.append(child)  # noqa: SLF001
            reply = await h.client("planning").request(Message.new(
                topics.CREW_SPAWN, source="planning", payload=_node("n1", "find it")), timeout=2.0)
            self.assertEqual(reply.payload["handle"], "n1")
            await service.stop()
        b = children[0].budget
        self.assertEqual((b.max_tokens, b.max_usd, b.max_wall_s), (900, 0.25, 120.0))

    @run
    async def test_one_crew_lives_in_one_worker(self):
        async with Harness() as h:
            service = OrchestrationService(Config(workers=3, metrics_interval_s=0))
            await service.start(_ctx(h, "orchestration"))
            gate = asyncio.Event()

            async def hold(*a, **k):
                await gate.wait()
            for w in service._workers:  # noqa: SLF001 -- members stay running
                w._runner.run = hold  # noqa: SLF001
            for i in range(3):
                reply = await h.client("planning").request(Message.new(
                    topics.CREW_SPAWN, source="planning", payload=_node(f"n{i}", "find it")), timeout=2.0)
                self.assertEqual(reply.payload["crew_id"], "proj-1")
            holders = [w for w in service._workers if "proj-1" in w._runner._crews]  # noqa: SLF001
            self.assertEqual(len(holders), 1)
            self.assertEqual(len(holders[0]._runner._crews["proj-1"].members), 3)  # noqa: SLF001
            gate.set()
            await asyncio.sleep(0.05)
            await service.stop()

    @run
    async def test_an_outside_caller_neither_names_a_handle_nor_joins_anothers_crew(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05)
            runner._start_member = lambda *a, **k: None  # noqa: SLF001 -- admission only
            crew_id, handle = await runner.spawn_detached({
                "agent": "research", "brief": "x", "requester": "Ira", "requester_channel": "a2a",
                "handle": "some-task-id"})
            self.assertNotEqual(handle, "some-task-id")
            # The same person on the same channel may come back to the crew.
            again = await runner.spawn_detached({"agent": "research", "brief": "y", "requester": "Ira",
                                                 "requester_channel": "a2a", "context_id": crew_id})
            self.assertEqual(again[0], crew_id)
            # Somebody else, or a project's node, may not.
            with self.assertRaises(CrewRefused):
                await runner.spawn_detached({"agent": "research", "brief": "z", "requester": "Aran",
                                             "requester_channel": "a2a", "context_id": crew_id})
            with self.assertRaises(CrewRefused):
                await runner.spawn_detached(_node("n9", "x", context_id=crew_id), plan_node=True)
            # Nor into a project's crew.
            await runner.spawn_detached(_node("n1", "x"), plan_node=True)
            with self.assertRaises(CrewRefused):
                await runner.spawn_detached({"agent": "research", "brief": "z", "requester": "Ira",
                                             "requester_channel": "a2a", "context_id": "proj-1"})
            # Nor into a running session's own crew; a refused crew is not kept.
            runner._open["sess-1"] = object()  # noqa: SLF001
            with self.assertRaises(CrewRefused):
                await runner.spawn_detached({"agent": "research", "brief": "z", "requester": "Ira",
                                             "requester_channel": "a2a", "context_id": "sess-1"})
            self.assertNotIn("sess-1", runner._crews)  # noqa: SLF001
            runner._open.pop("sess-1")  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
