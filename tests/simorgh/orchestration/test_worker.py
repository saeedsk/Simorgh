"""Worker-level tests: the claim loop, terminal reporting, and resume on
a second Worker after a simulated crash (S5/S7, 16 section 6/9)."""

import asyncio
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.orchestration.config import Config
from simorgh.orchestration.service import Service as OrchestrationService
from simorgh.orchestration.worker import Worker

from .fakes import FakeCognition, FakeGuardianExecution, FakePlanning, FakeVerification
from .harness import Harness, run


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


def _stub_context(h: "Harness", *, name: str = "orchestration") -> Context:
    return Context(
        name=name, instance_id="", run_id="test", mode="single",
        bus=h.client(name), ledger=h.ledger, config={}, secrets={}, clock=h.clock,
        logger=_Logger(), data_dir=Path("."),
    )


class TestWorkerClaimLoop(unittest.TestCase):
    @run
    async def test_claims_a_known_task_and_completes_it(self):
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))
            planning.add_task("t1", kind="chat", mode="execute", description="hi")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "hello back"}])
            await planning.start()
            await cognition.start()

            # A tiny assemble timeout: no self/persona/memory subsystem is
            # running in this test, so Assembler.assemble() must degrade via
            # a real asyncio.wait_for timeout (03 section 9) -- keep that
            # real wait short so the test doesn't need to pump for long.
            worker = Worker(
                h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                assemble_timeout_s=0.01,
            )
            await worker.start()

            completed = {}

            async def _on_turn(message):
                completed["turn"] = message

            sub = await h.client("interface").subscribe(topics.TURN_COMPLETED, _on_turn)

            from simorgh.contracts.envelope import Message
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            # The worker's claim + THINK round-trip runs as a detached task
            # (dispatched by the bus, not awaited here) -- real_delay lets
            # its real assemble-timeout waits actually elapse.
            await h.pump(30, real_delay=0.01)

            self.assertIn("turn", completed)
            self.assertEqual(completed["turn"].payload["text"], "hello back")

            await sub.unsubscribe()
            await worker.stop()
            await planning.stop()
            await cognition.stop()

    @run
    async def test_an_unknown_task_id_is_not_granted_and_worker_does_not_crash(self):
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))  # no tasks registered
            await planning.start()
            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1")
            await worker.start()

            from simorgh.contracts.envelope import Message
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "ghost", "kind": "chat", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            await h.pump(10)  # must not raise / hang

            await worker.stop()
            await planning.stop()


class TestLongReplyDoesNotGetLostAtTheLedger(unittest.TestCase):
    """Live-caught (the creator's own real use): a long real answer made
    the CLI narrate a completed step and then sit on "still thinking"
    for over a minute -- the reply never arrived. Cause: `_report`
    appended `result_summary` to the Ledger inline, and the Ledger
    refuses any inline string over `inline_threshold` (4096 chars) --
    `ValidationError` raised there, before either TASK_COMPLETED or
    TURN_COMPLETED ever published. `07-post-cutover-review.md`-class bug:
    built and tested at every layer except with content long enough to
    hit a real limit."""

    @run
    async def test_a_reply_longer_than_the_inline_threshold_still_arrives_in_full(self):
        async with Harness() as h:
            long_reply = "x" * 5000  # over the Ledger's 4096-char inline_threshold
            planning = FakePlanning(h.client("planning"))
            planning.add_task("t1", kind="chat", mode="execute", description="hi")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": long_reply}])
            await planning.start()
            await cognition.start()

            worker = Worker(
                h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                assemble_timeout_s=0.01,
            )
            await worker.start()

            completed = {}

            async def _on_turn(message):
                completed["turn"] = message

            sub = await h.client("interface").subscribe(topics.TURN_COMPLETED, _on_turn)

            from simorgh.contracts.envelope import Message
            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            await h.pump(30, real_delay=0.01)

            self.assertIn("turn", completed, "no turn.completed ever arrived -- the reply was lost")
            self.assertEqual(completed["turn"].payload["text"], long_reply)  # the bus keeps the full text

            events = await h.ledger.read("task:t1")
            [event] = [e for e in events if e.type == topics.TASK_COMPLETED]
            # The Ledger's own copy keeps a short preview (so a log viewer
            # still shows something) plus a ref to the full text -- it
            # never re-raises ValidationError by staying oversized inline.
            self.assertLess(len(event.payload["result_summary"]), len(long_reply))
            self.assertTrue(long_reply.startswith(event.payload["result_summary"][:-1]))  # real prefix, not fabricated
            self.assertIn("result_summary_ref", event.payload)
            self.assertTrue(event.payload["result_summary_ref"].startswith("blob:"))
            blob = await h.ledger.backend.get_blob(event.payload["result_summary_ref"])
            self.assertEqual(blob.decode("utf-8"), long_reply)  # the Ledger's blob also keeps the full text

            await sub.unsubscribe()
            await worker.stop()
            await planning.stop()
            await cognition.stop()


class TestPerceptTextRunsAChatTurnWithNoPlanningTask(unittest.TestCase):
    @run
    async def test_percept_text_received_produces_turn_completed_with_no_task_ever_created(self):
        """Flow 1 (02 section 5): plain conversational text has no
        `intent.goal.stated`/Planning task behind it -- only the
        `batch`/`evolve`/`plan` commands do. Before this test existed,
        nothing in Orchestration consumed `percept.text.received` at
        all, so a plain chat message from Interface got zero reply
        (Interface's own `_handle_chat` timed out with "no response --
        the reasoning subsystem isn't built yet this session")."""
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))  # deliberately: no task registered anywhere
            await planning.start()
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "hello back"}])
            await cognition.start()

            service = OrchestrationService(Config(workers=1))
            ctx = _stub_context(h)
            await service.start(ctx)

            completed = {}

            async def _on_turn(message):
                completed["turn"] = message

            sub = await h.client("interface").subscribe(topics.TURN_COMPLETED, _on_turn)

            from simorgh.contracts.envelope import Message
            await h.client("interface").publish(Message.new(
                topics.PERCEPT_TEXT_RECEIVED, source="interface",
                payload={"channel": "cli", "text": "hi there", "session_id": "sess-1"},
                clock=h.clock.now,
            ))
            # No worldmodel/persona/memory fake is running in this harness,
            # so Assembler.assemble()'s three sequential requests
            # (self.summary, persona.voice, memory.retrieve) each degrade
            # via a real 0.25s asyncio.wait_for -- give it real headroom.
            await h.pump(150, real_delay=0.02)

            self.assertIn("turn", completed)
            self.assertEqual(completed["turn"].payload["session_id"], "sess-1")
            self.assertEqual(completed["turn"].payload["text"], "hello back")
            self.assertEqual(planning._tasks, {})  # confirms this never touched Planning's task store

            await sub.unsubscribe()
            await service.stop()
            await cognition.stop()
            await planning.stop()

    @run
    async def test_empty_percept_text_is_ignored_not_a_crash(self):
        async with Harness() as h:
            service = OrchestrationService(Config(workers=1))
            ctx = _stub_context(h)
            await service.start(ctx)

            from simorgh.contracts.envelope import Message
            await h.client("interface").publish(Message.new(
                topics.PERCEPT_TEXT_RECEIVED, source="interface",
                payload={"channel": "cli", "text": "", "session_id": "sess-2"},
                clock=h.clock.now,
            ))
            await h.pump(10)  # must not raise / hang

            await service.stop()


class TestWorkerIdReflectsTheRealInstanceId(unittest.TestCase):
    """`local-multi` mode gives its Context a real per-process
    `instance_id` (the operator's own `--id`, kernel/service.py's
    `ctx_factory.build("orchestration", instance_id=self.worker_id)`).
    Before this test, `Service.start` always synthesized
    `f"{ctx.name}-{i}"`, so every worker process reported the identical
    `worker_id` ("orchestration-0") regardless of `--id` -- status,
    leases, and logs could not tell two worker processes apart
    (observer, 2026-09-08)."""

    @run
    async def test_an_instance_id_on_the_context_is_used_verbatim(self):
        async with Harness() as h:
            service = OrchestrationService(Config(workers=1))
            ctx = _stub_context(h)
            ctx = Context(
                name=ctx.name, instance_id="worker-7", run_id=ctx.run_id, mode=ctx.mode,
                bus=ctx.bus, ledger=ctx.ledger, config=ctx.config, secrets=ctx.secrets,
                clock=ctx.clock, logger=ctx.logger, data_dir=ctx.data_dir,
            )
            await service.start(ctx)
            self.assertEqual([w.worker_id for w in service._workers], ["worker-7"])
            await service.stop()

    @run
    async def test_no_instance_id_keeps_the_synthetic_in_process_naming(self):
        async with Harness() as h:
            service = OrchestrationService(Config(workers=2, metrics_interval_s=0))
            ctx = _stub_context(h)  # instance_id="" -- single mode
            await service.start(ctx)
            self.assertEqual(
                [w.worker_id for w in service._workers], ["orchestration-0", "orchestration-1"],
            )
            await service.stop()


class TestWorkerBusyTrackingAndMetrics(unittest.TestCase):
    """A dashboard's "what is each worker doing right now" view needs
    `Worker.current_task_id`/`current_kind` set while a session is
    in-flight and cleared once it ends, and `Service._publish_metrics`
    to put that onto the bus as `system.metrics{subsystem:
    "orchestration"}` the way `simorgh.bus.service` already does for its
    own gauges."""

    @run
    async def test_current_task_is_set_while_running_and_cleared_after(self):
        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))
            await planning.start()
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "hello back"}])
            await cognition.start()

            service = OrchestrationService(Config(workers=1, metrics_interval_s=0))
            ctx = _stub_context(h)
            await service.start(ctx)
            worker = service._workers[0]  # noqa: SLF001
            self.assertIsNone(worker.current_task_id)

            from simorgh.contracts.envelope import Message
            await h.client("interface").publish(Message.new(
                topics.PERCEPT_TEXT_RECEIVED, source="interface",
                payload={"channel": "cli", "text": "hi there", "session_id": "sess-busy"},
                clock=h.clock.now,
            ))
            await h.pump(5)  # past dispatch into Worker.run(), before the assemble timeouts resolve
            self.assertEqual(worker.current_task_id, "sess-busy")
            self.assertEqual(worker.current_kind, "chat")

            await h.pump(150, real_delay=0.02)  # let the session actually finish
            self.assertIsNone(worker.current_task_id)
            self.assertIsNone(worker.current_kind)

            await service.stop()
            await cognition.stop()
            await planning.stop()

    @run
    async def test_publish_metrics_puts_worker_snapshot_on_the_bus(self):
        async with Harness() as h:
            service = OrchestrationService(Config(workers=2, metrics_interval_s=0))
            ctx = _stub_context(h)
            await service.start(ctx)
            service._workers[0].current_task_id = "t1"  # noqa: SLF001
            service._workers[0].current_kind = "patch"  # noqa: SLF001

            seen = {}

            async def _on_metrics(message):
                if message.payload.get("subsystem") == "orchestration":
                    seen["message"] = message

            sub = await h.client("kernel").subscribe(topics.SYSTEM_METRICS, _on_metrics)
            await service._publish_metrics()  # noqa: SLF001
            await h.pump(5)
            await sub.unsubscribe()

            self.assertIn("message", seen)
            gauges = seen["message"].payload["gauges"]
            self.assertEqual(gauges["workers.total"], 2)
            self.assertEqual(gauges["workers.busy"], 1)
            busy = [w for w in gauges["workers"] if w["task_id"] == "t1"]
            self.assertEqual(len(busy), 1)
            self.assertEqual(busy[0]["kind"], "patch")

            await service.stop()


class TestResumeOnASecondWorker(unittest.TestCase):
    @run
    async def test_a_second_worker_does_not_redo_completed_steps(self):
        """S5/S7: w1 runs one tool-call step and its `task.step` is
        durable; a fresh Worker (simulating a restart) resuming the same
        task_id restores the step count from the Ledger before running,
        so its own budget correctly reflects the work already done."""
        async with Harness() as h:
            gx = FakeGuardianExecution(h.client("guardian"))
            await gx.start()

            cognition1 = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]},
            ])
            await cognition1.start()
            w1 = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1")
            from simorgh.orchestration import profiles
            from simorgh.orchestration.api import Session
            from simorgh.orchestration.resume import restore_step_count
            from simorgh.orchestration.session import SessionRunner

            session1 = Session(task_id="t9", kind="chat", mode="execute", profile=profiles.CHAT)
            session1.budget.max_steps = 2  # force a stop after exactly one step this "run"
            runner1 = SessionRunner(w1._bus, h.ledger, clock=h.clock.now, worker_id="w1")
            await runner1.run(session1, user_text="hi")  # completes at max_steps with floor/final text
            await cognition1.stop()

            steps_after_first_run = len((await h.ledger.read("task:t9")))
            self.assertGreaterEqual(steps_after_first_run, 1)

            # A fresh session object (simulating a second Worker after a
            # restart) restores its step count from the same stream.
            session2 = Session(task_id="t9", kind="chat", mode="execute", profile=profiles.CHAT)
            restored = await restore_step_count(session2, h.ledger)
            self.assertGreaterEqual(restored, 1)
            self.assertEqual(session2.budget.steps_used, restored)

            await gx.stop()


class TestMultiProcessSourceAttribution(unittest.TestCase):
    """`local-multi` mode (03-kernel.md section 5.6): every message a
    Worker publishes used to hardcode `source="orchestration"` (worker.py/
    session.py), no matter what per-process identity its own `BusClient`
    was bound to. A `ReservedTopologyPolicy` built with `identities` set
    (any mode other than `single`) authenticates only the *exact* source
    string a process's `IdentityRegistry` issued a token for
    (`orchestration@w1` for a `simorgh worker --id w1` process, see
    `kernel.context.ContextFactory.build`) -- so every one of those
    publishes raised `PolicyViolation: '...' is not authenticated`
    before `worker.py`/`session.py` were changed to publish under
    `self._bus.source` instead of the literal.
    """

    @run
    async def test_a_worker_bound_to_an_instance_qualified_source_completes_under_a_strict_policy(self):
        from simorgh.bus.enforcement import IdentityRegistry, ReservedTopologyPolicy
        from simorgh.bus.factory import make_client as make_bus_client

        async with Harness() as h:
            identities = IdentityRegistry(b"test-secret", "run-1")
            policy = ReservedTopologyPolicy(identities)
            # Every source this scenario touches self-authenticates exactly
            # once, mirroring `ContextFactory.build` -- a strict stand-in
            # for what a real multi-process boot does per process.
            for name, instance_id in (
                ("planning", ""), ("cognition", ""), ("guardian", ""), ("execution", ""),
                ("interface", ""), ("orchestration", "w1"),
            ):
                source = f"{name}@{instance_id}" if instance_id else name
                policy.authenticate(source, identities.issue(name, instance_id))

            def client(source: str):
                return make_bus_client(h._bus_backend, source=source, ledger=h.ledger,  # noqa: SLF001
                                       clock=h.clock.now, policy=policy)

            planning = FakePlanning(client("planning"))
            planning.add_task("t1", kind="chat", mode="execute", description="hi")
            cognition = FakeCognition(client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]},
                {"text": "hello back"},
            ])
            gx = FakeGuardianExecution(client("guardian"))
            await planning.start()
            await cognition.start()
            await gx.start()

            worker = Worker(client("orchestration@w1"), h.ledger, clock=h.clock.now, worker_id="w1",
                            assemble_timeout_s=0.01)
            await worker.start()

            completed = {}

            async def _on_turn(message):
                completed["turn"] = message

            sub = await client("interface").subscribe(topics.TURN_COMPLETED, _on_turn)

            from simorgh.contracts.envelope import Message
            await client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            await h.pump(60, real_delay=0.01)

            self.assertIn("turn", completed)  # no PolicyViolation ever reached a handler's except-all
            self.assertEqual(completed["turn"].payload["text"], "hello back")
            self.assertEqual(len(gx.proposals), 1)  # the read_file step actually reached Guardian/Execution
            self.assertEqual(gx.proposals[0].source, "orchestration@w1")  # attributed, not the bare literal

            await sub.unsubscribe()
            await worker.stop()
            await gx.stop()
            await cognition.stop()
            await planning.stop()


class _SlowFakeCognition(FakeCognition):
    """Like `FakeCognition`, but sleeps a real `delay_s` before replying
    -- stands in for a single step that itself outlives `lease_seconds`
    (a full `run_tests`, a stuck `web_fetch`, a cold-start
    `cognition.think`), without needing a real slow tool."""

    def __init__(self, bus, script, *, delay_s: float, floor: bool = False) -> None:
        super().__init__(bus, script, floor=floor)
        self._delay_s = delay_s

    async def _on(self, message) -> None:
        await asyncio.sleep(self._delay_s)
        await super()._on(message)


class _LeaseTrackingPlanning:
    """A minimal stand-in for `planning.store.TaskStore` +
    `planning.scheduler.Scheduler`'s own lease bookkeeping: grants a
    claim, and tracks `lease_until` against the *same* `FakeClock` the
    test drives directly, the way `TaskStore.claim`/`refresh_lease` set
    `now() + lease_seconds` for real. `lease_expired_at(t)` answers
    exactly what `Scheduler.scan_leases` asks: is `lease.until <= t`.
    """

    def __init__(self, bus, clock, *, lease_seconds: float) -> None:
        self._bus = bus
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._tasks: dict[str, dict] = {}
        self.lease_until: float | None = None
        self.refresh_count = 0
        self._subs: list = []

    def add_task(self, task_id: str, **fields) -> None:
        self._tasks[task_id] = fields

    async def start(self) -> None:
        self._subs.append(await self._bus.subscribe(topics.TASK_CLAIM, self._on_claim))
        self._subs.append(await self._bus.subscribe(topics.TASK_LEASE_HEARTBEAT, self._on_refresh))
        self._subs.append(await self._bus.subscribe(topics.TASK_STEP, self._on_refresh))

    async def stop(self) -> None:
        for s in self._subs:
            await s.unsubscribe()

    async def _on_claim(self, message: Message) -> None:
        task_id = message.payload["task_id"]
        task = self._tasks.get(task_id)
        if task is not None:
            self.lease_until = self._clock.now() + self._lease_seconds
        await self._bus.reply(message, type=topics.TASK_CLAIM_REPLY,
                               payload={"granted": task is not None, "task": task or {}})

    async def _on_refresh(self, message: Message) -> None:
        self.refresh_count += 1
        self.lease_until = self._clock.now() + self._lease_seconds

    def lease_expired_at(self, t: float) -> bool:
        return self.lease_until is not None and self.lease_until <= t


class TestLeaseHeartbeatSurvivesASlowSingleStep(unittest.TestCase):
    """The documented gap this fix closes: `task.step` (`_on_task_step`
    -> `TaskStore.refresh_lease`) only fires once a tool call
    *completes*, so a single step slower than `lease_seconds` used to
    get no renewal at all until it finished -- `Scheduler.scan_leases`
    would then see an expired lease mid-step and treat the task_id as
    available for a second worker to claim, even though the first
    worker was still running it (observer, 2026-09-08).

    `Worker._heartbeat_loop` now publishes `task.lease_heartbeat` on a
    real-wall-clock timer for as long as a task is claimed, independent
    of step completion. This proves it: the `FakeClock` is advanced
    past the original `lease_seconds` *while* a single `cognition.think`
    call is still in flight (real wall-clock sleep), and the lease is
    still not expired by the time the step finally completes.
    """

    @run
    async def test_lease_is_renewed_mid_step_before_it_would_expire(self):
        async with Harness() as h:
            lease_seconds = 2.0  # in FakeClock units, driven by the test below
            step_delay_s = 0.2  # real wall-clock seconds the "step" takes

            planning = _LeaseTrackingPlanning(h.client("planning"), h.clock, lease_seconds=lease_seconds)
            planning.add_task("t1", kind="chat", mode="execute", description="hi")
            await planning.start()

            cognition = _SlowFakeCognition(
                h.client("cognition"), script=[{"text": "hello back"}], delay_s=step_delay_s,
            )
            await cognition.start()

            # `heartbeat_s` real-wall-clock small enough to fire several
            # times inside `step_delay_s`; the Worker itself additionally
            # never waits longer than lease_seconds/3 (see
            # `_heartbeat_loop`), so this also proves that floor works
            # from a `heartbeat_s` that is not specially tuned to the
            # test's own `lease_seconds`.
            worker = Worker(
                h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                assemble_timeout_s=0.01, heartbeat_s=0.05,
            )
            await worker.start()

            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": lease_seconds},
                clock=h.clock.now,
            ))
            # Let the claim complete and the slow step actually start.
            await asyncio.sleep(0.02)
            self.assertIsNotNone(planning.lease_until, "the claim never granted -- nothing to test")

            # Advance the FakeClock past what the ORIGINAL lease_until
            # would be, still well inside the step's real 0.2s delay --
            # this is the moment `Scheduler.scan_leases` would have
            # expired the lease before this fix (nothing but `task.step`,
            # which hasn't fired yet, ever refreshed it).
            original_lease_until = planning.lease_until
            h.clock.advance(lease_seconds + 1.0)
            self.assertTrue(
                planning.lease_expired_at(h.clock.now()),
                "test setup bug: the original lease should already read as expired at this clock time",
            )

            # Give the real-wall-clock heartbeat loop a chance to fire at
            # least once against the NEW clock time before the step
            # finishes.
            await asyncio.sleep(step_delay_s)  # >= step_delay_s so the think call also completes
            await h.pump(10, real_delay=0.01)

            self.assertGreater(planning.refresh_count, 0, "no heartbeat was ever published mid-step")
            self.assertGreater(
                planning.lease_until, original_lease_until,
                "the lease was never renewed while the step was in flight",
            )
            self.assertFalse(
                planning.lease_expired_at(h.clock.now()),
                "the lease reads as expired -- a second worker could have claimed t1 mid-step",
            )

            await worker.stop()
            await cognition.stop()
            await planning.stop()

    @run
    async def test_heartbeat_loop_stops_once_the_task_ends(self):
        """The loop must not outlive the session it is renewing -- a
        leaked timer would keep refreshing a lease for a task that is
        already terminal, masking a real stuck/crashed worker."""
        async with Harness() as h:
            planning = _LeaseTrackingPlanning(h.client("planning"), h.clock, lease_seconds=60.0)
            planning.add_task("t1", kind="chat", mode="execute", description="hi")
            await planning.start()
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "hello back"}])
            await cognition.start()

            worker = Worker(
                h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                assemble_timeout_s=0.01, heartbeat_s=0.02,
            )
            await worker.start()

            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            await h.pump(30, real_delay=0.01)  # the (fast) session finishes well inside this

            count_after_completion = planning.refresh_count
            await asyncio.sleep(0.1)  # several heartbeat_s intervals, if the loop leaked
            self.assertEqual(
                planning.refresh_count, count_after_completion,
                "the heartbeat loop kept publishing after the task it belonged to had already finished",
            )

            await worker.stop()
            await cognition.stop()
            await planning.stop()


if __name__ == "__main__":
    unittest.main()


class TestTurnCompletedFiresForEveryKindNotJustChat(unittest.TestCase):
    """`turn.completed` used to publish only for `session.kind == "chat"`,
    and Memory's `_on_turn_completed` is the ONLY thing in the system
    that ever writes episodic memory -- so every research/patch/skill/
    project outcome went unrecorded. An observer proved it live
    2026-09-08: a real research task ran real searches, answered,
    completed, and a follow-up task asking "what did you find out
    before" got nothing back and re-did the whole search from scratch.

    Broadening the publish to every kind is safe for Interface, whose
    own `_on_turn_completed` only resolves a future keyed by
    `session_id` in `_pending_turns` -- nothing but a live chat prompt
    populates that map, so a non-chat task_id simply finds no waiter.
    """

    @run
    async def test_a_research_tasks_completion_publishes_turn_completed(self):
        from simorgh.contracts.envelope import Message

        async with Harness() as h:
            planning = FakePlanning(h.client("planning"))
            planning.add_task("t1", kind="research", mode="execute", description="what is X")
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "X is Y"}])
            verification = FakeVerification(h.client("verification"), verdicts=["pass"])
            await planning.start()
            await cognition.start()
            await verification.start()

            worker = Worker(h.client("orchestration"), h.ledger, clock=h.clock.now, worker_id="w1",
                            assemble_timeout_s=0.01)
            await worker.start()

            turns = []
            sub = await h.client("memory").subscribe(topics.TURN_COMPLETED, lambda m: turns.append(m) or None)

            await h.client("planning").publish(Message.new(
                topics.TASK_AVAILABLE, source="planning",
                payload={"task_id": "t1", "kind": "research", "lease_seconds": 60.0},
                clock=h.clock.now,
            ))
            await h.pump(30, real_delay=0.01)

            self.assertTrue(turns, "a non-chat task's completion must still publish turn.completed, "
                                   "or nothing ever writes episodic memory for it")
            self.assertEqual(turns[0].payload["text"], "X is Y")
            self.assertEqual(turns[0].payload["task_id"], "t1")

            await sub.unsubscribe()
            await worker.stop()
            await planning.stop()
            await cognition.stop()
            await verification.stop()
