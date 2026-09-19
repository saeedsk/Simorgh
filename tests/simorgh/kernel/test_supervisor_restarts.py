"""The Supervisor supervises (2026-09-18 evaluation, B10).

Until 2026-09-19 `_restart` stopped a service and never started it, and
nothing in production called `poll_once`. Pinned: a service that reports
`down` is stopped, started again with a fresh Context, and polled healthy;
the ticker drives that on `health_every_s`.
"""

import asyncio
import unittest

import pytest

from simorgh.contracts.protocols import Health
from simorgh.kernel.supervisor import Supervisor

pytestmark = pytest.mark.contract


class _Flaky:
    """Healthy, then `down` once, then healthy again after a restart."""

    name = "flaky"

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.contexts: list = []
        self._down = False

    async def start(self, ctx) -> None:
        self.starts += 1
        self.contexts.append(ctx)
        self._down = False

    async def stop(self) -> None:
        self.stops += 1

    async def health(self) -> Health:
        return Health.down("boom") if self._down else Health.ok("fine")

    def fail(self) -> None:
        self._down = True


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s
        await asyncio.sleep(0)


class _Log:
    def __init__(self) -> None:
        self.events: list[str] = []

    def info(self, event, **f): self.events.append(event)
    def debug(self, event, **f): self.events.append(event)
    def warning(self, event, **f): self.events.append(event)
    def error(self, event, **f): self.events.append(event)


class ARestartRestarts(unittest.IsolatedAsyncioTestCase):
    async def test_a_down_service_is_stopped_started_with_a_fresh_context_and_polled_ok(self):
        svc = _Flaky()
        clock = _Clock()
        sup = Supervisor(clock=clock, logger=_Log(), backoff_s=(0.1,), max_restarts_per_window=3)
        contexts = []

        def make_context(name):
            ctx = object()
            contexts.append(ctx)
            return ctx

        await sup.start_layer(("flaky",), make_context, {"flaky": lambda: svc})
        self.assertEqual(svc.starts, 1)

        svc.fail()
        changed = await sup.poll_once()
        self.assertEqual([s.name for s in changed], ["flaky"])
        self.assertEqual((svc.stops, svc.starts), (1, 2), "stopped once, started again")
        self.assertIs(svc.contexts[-1], contexts[-1], "the restart gets a fresh Context")
        self.assertEqual(sup.services["flaky"].status, "ok")
        self.assertEqual(sup.services["flaky"].restarts, 1)

    async def test_the_ticker_polls_and_reports_changes(self):
        svc = _Flaky()
        clock = _Clock()
        sup = Supervisor(clock=clock, logger=_Log(), backoff_s=(0.1,), max_restarts_per_window=3)
        await sup.start_layer(("flaky",), lambda name: object(), {"flaky": lambda: svc})
        seen: list[str] = []

        async def on_change(supervised):
            seen.append(f"{supervised.name}:{supervised.status}")

        task = asyncio.create_task(sup.run_ticker(5.0, on_change))
        try:
            svc.fail()
            for _ in range(50):
                await asyncio.sleep(0)
                if svc.starts >= 2:
                    break
            self.assertGreaterEqual(svc.starts, 2, "the ticker restarted the service")
            self.assertIn("flaky:ok", seen)
            self.assertIn(5.0, clock.sleeps)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
