import unittest

from simorgh.contracts.protocols import Health
from simorgh.kernel.api import Supervised
from simorgh.kernel.supervisor import SAFETY_CRITICAL, BootFailed, BootTimeout, Supervisor
from tests.simorgh.helpers import FakeClock


class _NullLogger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _FakeService:
    """A minimal `Subsystem`. `health_sequence` is popped one value per
    `health()` call (holding the last entry once exhausted) so a test can
    script "boots ok, then goes down on the third poll"."""

    name = "toy"
    version = "0.1.0"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self, health_sequence: list[Health] | None = None, *, start_error: Exception | None = None):
        self._sequence = list(health_sequence or [Health.ok()])
        self._start_error = start_error
        self.started = False
        self.stopped = False

    async def start(self, ctx) -> None:
        if self._start_error is not None:
            raise self._start_error
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def health(self) -> Health:
        if len(self._sequence) > 1:
            return self._sequence.pop(0)
        return self._sequence[0]


def _make_context(name: str):
    return object()  # Supervisor only threads this through to service.start(ctx); a stub is enough


class TestStartLayer(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_services_boot_and_are_recorded(self):
        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=3)
        services = {"a": _FakeService(), "b": _FakeService()}
        await sup.start_layer(("a", "b"), _make_context, {n: (lambda n=n: services[n]) for n in services})
        self.assertTrue(services["a"].started)
        self.assertTrue(services["b"].started)
        self.assertEqual(sup.services["a"].status, "ok")
        self.assertTrue(sup.services["a"].boot_ok)

    async def test_degraded_boot_still_counts_as_ok_to_proceed(self):
        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=3)
        services = {"a": _FakeService([Health.degraded("slow start")])}
        await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})
        self.assertTrue(sup.services["a"].boot_ok)
        self.assertEqual(sup.services["a"].status, "degraded")

    async def test_down_health_after_start_raises_boot_failed(self):
        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=3)
        services = {"a": _FakeService([Health.down("no db")])}
        with self.assertRaises(BootFailed):
            await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})

    async def test_start_raising_wraps_as_boot_failed_naming_the_service(self):
        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=3)
        services = {"a": _FakeService(start_error=RuntimeError("boom"))}
        with self.assertRaises(BootFailed) as ctx:
            await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})
        self.assertIn("a", str(ctx.exception))

    async def test_start_hang_raises_boot_timeout(self):
        import asyncio

        class _HangingService(_FakeService):
            async def start(self, ctx) -> None:
                await asyncio.sleep(10)

        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,),
                         max_restarts_per_window=3, boot_timeout_s=0.01)
        services = {"a": _HangingService()}
        with self.assertRaises(BootTimeout):
            await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})


class TestPollOnce(unittest.IsolatedAsyncioTestCase):
    async def test_poll_reports_no_change_when_status_is_stable(self):
        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=3)
        services = {"a": _FakeService([Health.ok()])}
        await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})
        changed = await sup.poll_once()
        self.assertEqual(changed, [])

    async def test_poll_reports_change_and_triggers_restart_on_down(self):
        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(0.5,), max_restarts_per_window=3)
        services = {"a": _FakeService([Health.ok(), Health.down("crashed")])}
        await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})
        changed = await sup.poll_once()
        self.assertEqual([s.name for s in changed], ["a"])
        self.assertEqual(sup.services["a"].status, "degraded")  # _restart() left it degraded, mid-backoff
        self.assertTrue(services["a"].stopped)
        self.assertEqual(sup.services["a"].restarts, 1)

    async def test_health_raising_is_treated_as_down(self):
        class _ExplodingService(_FakeService):
            async def health(self) -> Health:
                raise RuntimeError("health check itself is broken")

        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(0.1,), max_restarts_per_window=3)
        services = {"a": _ExplodingService()}
        sup.services["a"] = Supervised(
            name="a", service=services["a"], status="ok",
        )
        changed = await sup.poll_once()
        self.assertEqual([s.name for s in changed], ["a"])


class TestRestartBackoffAndDownThreshold(unittest.IsolatedAsyncioTestCase):
    async def test_backoff_delay_uses_table_indexed_by_restart_count_clamped_to_last_entry(self):
        clock = FakeClock()
        sup = Supervisor(clock=clock, logger=_NullLogger(), backoff_s=(1.0, 2.0, 5.0), max_restarts_per_window=10)
        service = _FakeService()
        sup.services["a"] = Supervised(
            name="a", service=service, status="ok",
        )
        supervised = sup.services["a"]

        await sup._restart(supervised)  # noqa: SLF001 -- restarts=0 -> backoff[0]=1.0, then restarts becomes 1
        self.assertEqual(clock.now(), 1_700_000_001.0)
        await sup._restart(supervised)  # noqa: SLF001 -- restarts=1 -> backoff[1]=2.0
        self.assertEqual(clock.now(), 1_700_000_003.0)
        await sup._restart(supervised)  # noqa: SLF001 -- restarts=2 -> backoff[2]=5.0
        self.assertEqual(clock.now(), 1_700_000_008.0)
        await sup._restart(supervised)  # noqa: SLF001 -- restarts=3, clamped to backoff[-1]=5.0
        self.assertEqual(clock.now(), 1_700_000_013.0)

    async def test_exceeding_max_restarts_in_window_marks_down_without_sleeping(self):
        clock = FakeClock()
        sup = Supervisor(clock=clock, logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=2)
        service = _FakeService()
        sup.services["a"] = Supervised(name="a", service=service, status="ok")
        supervised = sup.services["a"]

        await sup._restart(supervised)  # noqa: SLF001 -- 1st restart, within budget
        await sup._restart(supervised)  # noqa: SLF001 -- 2nd restart, within budget
        before = clock.now()
        await sup._restart(supervised)  # noqa: SLF001 -- 3rd: over max_restarts_per_window=2
        self.assertEqual(supervised.status, "down")
        self.assertEqual(clock.now(), before)  # gave up without another backoff sleep

    async def test_restart_window_forgets_restarts_older_than_ten_minutes(self):
        clock = FakeClock()
        sup = Supervisor(clock=clock, logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=1)
        service = _FakeService()
        sup.services["a"] = Supervised(name="a", service=service, status="ok")
        supervised = sup.services["a"]

        await sup._restart(supervised)  # noqa: SLF001 -- uses up the budget of 1
        clock.advance(601.0)  # past the 10-minute restart window
        await sup._restart(supervised)  # noqa: SLF001 -- old restart has aged out, budget is fresh again
        self.assertNotEqual(supervised.status, "down")

    async def test_guardian_down_past_budget_invokes_on_critical_down(self):
        clock = FakeClock()
        called: list[str] = []

        async def _on_critical_down(name: str) -> None:
            called.append(name)

        sup = Supervisor(clock=clock, logger=_NullLogger(), backoff_s=(1.0,),
                         max_restarts_per_window=0, on_critical_down=_on_critical_down)
        service = _FakeService()
        sup.services["guardian"] = Supervised(name="guardian", service=service, status="ok")
        await sup._restart(sup.services["guardian"])  # noqa: SLF001
        self.assertEqual(called, ["guardian"])

    async def test_non_critical_down_past_budget_does_not_invoke_on_critical_down(self):
        clock = FakeClock()
        called: list[str] = []

        async def _on_critical_down(name: str) -> None:
            called.append(name)

        sup = Supervisor(clock=clock, logger=_NullLogger(), backoff_s=(1.0,),
                         max_restarts_per_window=0, on_critical_down=_on_critical_down)
        service = _FakeService()
        sup.services["curiosity"] = Supervised(name="curiosity", service=service, status="ok")
        await sup._restart(sup.services["curiosity"])  # noqa: SLF001
        self.assertEqual(called, [])

    def test_safety_critical_set_is_guardian_and_execution(self):
        self.assertEqual(SAFETY_CRITICAL, frozenset({"guardian", "execution"}))


class TestStopAll(unittest.IsolatedAsyncioTestCase):
    async def test_stops_every_service_across_layers_in_reverse_order(self):
        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=3)
        services = {"a": _FakeService(), "b": _FakeService()}
        await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})
        await sup.start_layer(("b",), _make_context, {"b": lambda: services["b"]})
        await sup.stop_all([("b",), ("a",)], grace_s=1.0)
        self.assertTrue(services["a"].stopped)
        self.assertTrue(services["b"].stopped)
        self.assertEqual(sup.services["a"].status, "stopped")
        self.assertEqual(sup.services["b"].status, "stopped")

    async def test_grace_timeout_is_swallowed_not_raised(self):
        import asyncio

        class _SlowStopService(_FakeService):
            async def stop(self) -> None:
                await asyncio.sleep(10)

        sup = Supervisor(clock=FakeClock(), logger=_NullLogger(), backoff_s=(1.0,), max_restarts_per_window=3)
        services = {"a": _SlowStopService()}
        await sup.start_layer(("a",), _make_context, {"a": lambda: services["a"]})
        await sup.stop_all([("a",)], grace_s=0.01)  # must not raise


if __name__ == "__main__":
    unittest.main()
