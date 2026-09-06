import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.bus.client import BusClient
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Health
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import PAUSED, RUNNING, STOPPED
from tests.simorgh.helpers import FakeClock


def _make_kernel(tmp: str) -> Kernel:
    config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
    return Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())


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


if __name__ == "__main__":
    unittest.main()
