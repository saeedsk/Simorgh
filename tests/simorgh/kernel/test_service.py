import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.bus.client import BusClient
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Health
from simorgh.kernel.config import ConfigError, LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel, KernelBootError, WorkerKernel
from simorgh.kernel.state import PAUSED, RUNNING, STOPPED
from tests.simorgh.helpers import FakeClock


def _make_kernel(tmp: str) -> Kernel:
    config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
    return Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())


def _local_multi_config(tmp: str, **extra_runtime) -> LoadedConfig:
    runtime = {"mode": "local-multi", "data_dir": tmp, **extra_runtime}
    return LoadedConfig({"runtime": runtime, "bus": {"backend": "sqlite"}, "ledger": {"backend": "sqlite"}}, None)


async def _pump(n: int = 30) -> None:
    """Bus dispatch runs on a background task, not inline with publish(),
    so a handler needs several event-loop turns to actually run."""
    for _ in range(n):
        await asyncio.sleep(0)


class TestBootAndShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_boot_reaches_running_with_bus_and_ledger_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                self.assertEqual(kernel.state.state, RUNNING)
                self.assertEqual(kernel._supervisor.services["bus"].status, "ok")  # noqa: SLF001
                self.assertEqual(kernel._supervisor.services["ledger"].status, "ok")  # noqa: SLF001
            finally:
                await kernel.shutdown()

    async def test_boot_publishes_system_started_and_state_changed(self):
        # Both are published *during* boot() itself, before a subscriber
        # created afterward could ever see them (broadcast, not buffered) --
        # so spy on BusClient.publish directly rather than subscribing.
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            published: list[str] = []
            original = BusClient.publish

            async def _spy(self, message, **kwargs):
                published.append(message.type)
                return await original(self, message, **kwargs)

            with mock.patch.object(BusClient, "publish", new=_spy):
                await kernel.boot()
            try:
                self.assertIn(topics.SYSTEM_STARTED, published)
                self.assertIn(topics.SYSTEM_STATE_CHANGED, published)
            finally:
                await kernel.shutdown()

    async def test_boot_writes_a_system_state_event_to_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                events = await kernel.ledger.read("system")
                self.assertTrue(any(e.payload["state"] == RUNNING for e in events))
            finally:
                await kernel.shutdown()

    async def test_shutdown_reaches_stopped_and_stops_every_subsystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            await kernel.shutdown()
            self.assertEqual(kernel.state.state, STOPPED)
            self.assertEqual(kernel._supervisor.services["bus"].status, "stopped")  # noqa: SLF001
            self.assertEqual(kernel._supervisor.services["ledger"].status, "stopped")  # noqa: SLF001

    async def test_data_dir_is_created_under_the_configured_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                self.assertTrue((Path(tmp)).is_dir())
            finally:
                await kernel.shutdown()


class TestInteractiveFlag(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_to_not_interactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_make_kernel(tmp)._interactive)  # noqa: SLF001

    async def test_interactive_true_is_threaded_through_to_the_interface_factory(self):
        # Only constructs the factory dict (never boots) so this stays a
        # fast, deterministic check -- booting with run_repl=True would
        # spawn a real REPL thread reading this test process's own stdin.
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
            kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock(), interactive=True)
            self.assertTrue(kernel._interactive)  # noqa: SLF001
            from simorgh.kernel.registry import build_factories

            factories = build_factories(bus_client=object(), ledger_client=object(), run_repl=kernel._interactive)
            self.assertTrue(factories["interface"]()._run_repl)  # noqa: SLF001


class TestExecutionConfigFromSimorghToml(unittest.IsolatedAsyncioTestCase):
    """`execution/README.md`'s "MCP servers" section, step 1: `simorgh.
    toml`'s `[execution]` section now reaches the real `execution.Config`
    a booted Kernel's Execution subsystem runs with -- `registry.
    build_factories`'s `execution_config` parameter, threaded from
    `Kernel.boot` via `self.config.section("execution")`, the same
    pattern `bus`/`ledger`/`orchestration` already use."""

    async def test_an_mcp_servers_entry_in_simorgh_toml_reaches_the_booted_execution_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({
                "runtime": {"data_dir": tmp},
                "execution": {"mcp_servers": [{
                    # A command that can never actually launch -- proves
                    # the config reached Execution without needing a real
                    # MCP server (or network) in this test; Execution's
                    # own graceful-degradation is covered separately in
                    # tests/simorgh/execution/test_service.py.
                    "name": "ddg_search", "command": "/no/such/binary-xyz", "args": ["-y", "ddg-search-mcp"],
                }]},
            }, None)
            kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
            await kernel.boot()
            try:
                execution = kernel._supervisor.services["execution"].service  # noqa: SLF001
                self.assertEqual(len(execution._config.mcp_servers), 1)  # noqa: SLF001
                self.assertEqual(execution._config.mcp_servers[0].name, "ddg_search")  # noqa: SLF001
                self.assertEqual(execution._config.mcp_servers[0].args, ("-y", "ddg-search-mcp"))  # noqa: SLF001
            finally:
                await kernel.shutdown()


class TestPauseResumeStop(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.kernel = _make_kernel(self._tmp.name)
        await self.kernel.boot()

    async def asyncTearDown(self):
        await self.kernel.shutdown()
        self._tmp.cleanup()

    async def test_pause_message_moves_state_to_paused(self):
        await self.kernel.bus.publish(Message.new(
            topics.SYSTEM_PAUSE, source="interface",
            payload={"reason": "human", "requested_by": "interface"}, priority=9,
        ))
        await _pump()
        self.assertEqual(self.kernel.state.state, PAUSED)

    async def test_resume_message_moves_state_back_to_running(self):
        await self.kernel.bus.publish(Message.new(
            topics.SYSTEM_PAUSE, source="interface",
            payload={"reason": "human", "requested_by": "interface"}, priority=9,
        ))
        await self.kernel.bus.publish(Message.new(
            topics.SYSTEM_RESUME, source="interface",
            payload={"reason": "human", "requested_by": "interface"}, priority=9,
        ))
        await _pump()
        self.assertEqual(self.kernel.state.state, RUNNING)

    async def test_stop_message_sets_the_stop_event(self):
        await self.kernel.bus.publish(Message.new(
            topics.SYSTEM_STOP, source="interface",
            payload={"reason": "shutdown", "requested_by": "interface"}, priority=9,
        ))
        await asyncio.wait_for(self.kernel.wait_for_stop(), timeout=1.0)


class TestCriticalDown(unittest.IsolatedAsyncioTestCase):
    async def test_a_safety_critical_subsystem_going_down_pauses_the_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                self.assertEqual(kernel.state.state, RUNNING)
                await kernel._on_critical_down("guardian")  # noqa: SLF001
                self.assertEqual(kernel.state.state, PAUSED)
            finally:
                await kernel.shutdown()

    async def test_critical_down_while_already_paused_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                await kernel._on_critical_down("guardian")  # noqa: SLF001
                events_before = len(await kernel.ledger.read("system"))
                await kernel._on_critical_down("execution")  # noqa: SLF001 -- already paused, must not double-append
                events_after = len(await kernel.ledger.read("system"))
                self.assertEqual(events_before, events_after)
            finally:
                await kernel.shutdown()


class TestHealthAndStatus(unittest.IsolatedAsyncioTestCase):
    async def test_health_is_down_before_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            health = await kernel.health()
            self.assertEqual(health.status, "down")

    async def test_health_is_ok_when_everything_is_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                health = await kernel.health()
                self.assertEqual(health.status, "ok")
            finally:
                await kernel.shutdown()

    async def test_status_snapshot_before_boot_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            self.assertEqual(kernel.status_snapshot(), {})

    async def test_status_snapshot_after_boot_has_run_id_mode_and_subsystems(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                snap = kernel.status_snapshot()
                self.assertEqual(snap["run_id"], kernel.run_id)
                self.assertEqual(snap["mode"], "single")
                self.assertEqual(snap["state"], RUNNING)
                # Was {"bus", "ledger"} when this test was first written
                # (Phase 0) -- stale the moment the other twelve
                # subsystems were wired into the registry (docs/EVOLUTION.md
                # milestone 103). _make_kernel boots the real, unpatched
                # registry, so the snapshot now genuinely reflects every
                # subsystem LAYERS names.
                from simorgh.kernel.registry import LAYERS

                names = {s["name"] for s in snap["subsystems"]}
                self.assertEqual(names, {name for layer in LAYERS for name in layer})
            finally:
                await kernel.shutdown()

    async def test_status_snapshot_subsystems_carry_health_detail_layer_and_restarts(self):
        """A dashboard needs more than a bare ok/degraded/down per
        subsystem to be useful -- each `health()`'s own `detail` string
        (e.g. guardian's "posture=guarded", orchestration's "0/1 worker(s) busy")
        was already being computed and simply never left the Supervisor;
        `layer` lets a UI group by boot order without duplicating
        `LAYERS` itself; `restarts` surfaces supervisor activity."""
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                snap = kernel.status_snapshot()
                by_name = {s["name"]: s for s in snap["subsystems"]}
                self.assertEqual(by_name["bus"]["layer"], 0)
                self.assertEqual(by_name["orchestration"]["layer"], 5)
                for s in snap["subsystems"]:
                    self.assertIsInstance(s["detail"], str)
                    self.assertEqual(s["restarts"], 0)
            finally:
                await kernel.shutdown()


class TestLocalMultiMode(unittest.IsolatedAsyncioTestCase):
    """`local-multi` mode (03-kernel.md section 5.6): `simorgh run` boots
    everything except `orchestration`; a real subsystem token round-trip
    (identities issued and *authenticated*, `bus/enforcement.py`) must
    not raise `PolicyViolation` on the very first publish/subscribe --
    that was unconditionally broken before this fix, since nothing ever
    called `ReservedTopologyPolicy.authenticate()`."""

    async def test_orchestration_is_excluded_from_the_main_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Kernel(_local_multi_config(tmp), clock=FakeClock())
            await kernel.boot()
            try:
                self.assertNotIn("orchestration", kernel._supervisor.services)  # noqa: SLF001
                self.assertIn("guardian", kernel._supervisor.services)  # noqa: SLF001
                self.assertIn("execution", kernel._supervisor.services)  # noqa: SLF001
            finally:
                await kernel.shutdown()

    async def test_boot_reaches_running_without_a_policy_violation(self):
        # Regression: every subsystem's first bus call used to raise
        # `PolicyViolation("... is not authenticated on this bus")` in any
        # mode other than `single`, because `authenticate()` was never
        # called anywhere -- `ContextFactory.build` issued a token and
        # simply discarded it.
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Kernel(_local_multi_config(tmp), clock=FakeClock())
            await kernel.boot()
            try:
                self.assertEqual(kernel.state.state, RUNNING)
            finally:
                await kernel.shutdown()

    async def test_single_mode_still_boots_orchestration_in_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                self.assertIn("orchestration", kernel._supervisor.services)  # noqa: SLF001
            finally:
                await kernel.shutdown()

    async def test_memory_bus_backend_is_refused_in_local_multi_mode(self):
        # local-multi's entire premise is a shared cross-process backend;
        # `memory` is in-process only and a worker against it would just
        # never see anything -- fail loud at boot, not silently.
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"mode": "local-multi", "data_dir": tmp}}, None)
            kernel = Kernel(config, clock=FakeClock())
            with self.assertRaises(ConfigError):
                await kernel.boot()

    async def test_shutdown_after_sqlite_ledger_boot_does_not_raise(self):
        # Regression: `Kernel.shutdown()` used to append the final
        # `system.state` event *after* `stop_all` had already closed the
        # ledger's own backend connection via `ledger.service.Service.
        # stop()` -- silently tolerated by `memory`/`jsonl`, but `sqlite`
        # enforces "not started" and raised on every clean shutdown, in
        # *any* mode (reproducible in plain `single` mode too).
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp}, "ledger": {"backend": "sqlite"}}, None)
            kernel = Kernel(config, clock=FakeClock())
            await kernel.boot()
            await kernel.shutdown()  # must not raise LedgerUnavailable
            self.assertEqual(kernel.state.state, STOPPED)


class TestWorkerKernel(unittest.IsolatedAsyncioTestCase):
    """The `simorgh worker --id wN` process (`WorkerKernel`): only
    `orchestration`, no HMAC approval secret, self-consistent identity
    authentication."""

    async def test_requires_local_multi_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)  # mode defaults to "single"
            with self.assertRaises(KernelBootError):
                WorkerKernel(config, worker_id="w1")

    async def test_boots_only_orchestration_and_reports_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = WorkerKernel(_local_multi_config(tmp), worker_id="w1", clock=FakeClock())
            await worker.boot()
            try:
                health = await worker.health()
                self.assertEqual(health.status, "ok")
                self.assertEqual(worker._ctx.name, "orchestration")  # noqa: SLF001
                self.assertEqual(worker._ctx.instance_id, "w1")  # noqa: SLF001
            finally:
                await worker.shutdown()

    async def test_never_receives_the_hmac_approval_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = WorkerKernel(_local_multi_config(tmp), worker_id="w1", clock=FakeClock())
            await worker.boot()
            try:
                self.assertEqual(worker._ctx.secrets.get("__hmac__"), None)  # noqa: SLF001
            finally:
                await worker.shutdown()

    async def test_a_worker_and_the_main_kernel_share_one_sqlite_bus_and_ledger(self):
        """Both processes point at the same `simorgh.toml`-derived
        `${data_dir}` -- proving the paths actually agree is the
        precondition for the real cross-process crash/resume drill in
        `tests/simorgh/integration/`."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _local_multi_config(tmp)
            kernel = Kernel(config, clock=FakeClock())
            await kernel.boot()
            worker = WorkerKernel(config, worker_id="w1", clock=FakeClock())
            await worker.boot()
            try:
                self.assertEqual(kernel._bus_backend._path, worker._bus_backend._path)  # noqa: SLF001
                self.assertEqual(str(kernel.ledger.backend.path), str(worker.ledger.backend.path))
            finally:
                await worker.shutdown()
                await kernel.shutdown()

    async def test_worker_process_publishes_without_a_policy_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = WorkerKernel(_local_multi_config(tmp), worker_id="w1", clock=FakeClock())
            await worker.boot()
            try:
                # Orchestration's own Service already exercises publish/
                # subscribe during start() (task.available, system.state.
                # changed); a direct publish on its own Context bus proves
                # the same self-issued token is accepted for a type it is
                # actually allowed to produce.
                await worker.bus.publish(Message.new(
                    topics.SYSTEM_METRICS, source="orchestration@w1",
                    payload={"subsystem": "orchestration", "counters": {}, "gauges": {}},
                ))
            finally:
                await worker.shutdown()


if __name__ == "__main__":
    unittest.main()
