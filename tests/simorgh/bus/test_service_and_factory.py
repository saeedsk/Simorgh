import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simorgh.bus import Service
from simorgh.bus.api import BackendUnavailable
from simorgh.bus.backends.memory import InMemoryBackend
from simorgh.bus.backends.sqlite import SqliteBackend
from simorgh.bus.config import Config
from simorgh.bus.factory import make_backend, make_bus, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context, Health

from tests.simorgh.helpers import FakeClock, make_message

from .fakes import FakeLedger
from .harness import Harness, run


class TestConfig(unittest.TestCase):
    def test_defaults_and_mapping(self):
        cfg = Config.from_mapping({"backend": "sqlite", "max_deliveries": 7, "sqlite": {"poll_interval_ms": 10}}, data_dir="/d")
        self.assertEqual(cfg.backend, "sqlite")
        self.assertEqual(cfg.max_deliveries, 7)
        self.assertEqual(cfg.sqlite.path, "/d/bus.sqlite")
        self.assertEqual(cfg.sqlite.poll_interval_ms, 10)
        self.assertEqual(Config.from_mapping(None).backend, "memory")

    def test_env_overrides(self):
        with patch.dict(os.environ, {"SIMORGH_BUS_BACKEND": "sqlite", "SIMORGH_BUS_SQLITE_PATH": "/x/y.db"}):
            cfg = Config.from_mapping({})
        self.assertEqual(cfg.backend, "sqlite")
        self.assertEqual(cfg.sqlite.path, "/x/y.db")


class TestFactory(unittest.TestCase):
    def test_backend_selection(self):
        self.assertIsInstance(make_backend(Config(backend="memory")), InMemoryBackend)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config.from_mapping({"backend": "sqlite"}, data_dir=tmp)
            self.assertIsInstance(make_backend(cfg), SqliteBackend)
        with self.assertRaises(BackendUnavailable):
            make_backend(Config(backend="carrier-pigeon"))

    @run
    async def test_make_bus_and_clients_share_one_backend(self):
        kernel = make_bus(Config(metrics_interval_seconds=0), source="kernel")
        other = make_client(kernel.backend, source="planning", config=Config(metrics_interval_seconds=0))
        await kernel.start()
        seen: list = []

        async def h(m):
            seen.append(m.source)

        await kernel.subscribe("task.*", h)
        await other.publish(make_message(topics.TASK_STARTED, source="planning"))
        await asyncio.sleep(0.03)
        self.assertEqual(seen, ["planning"])
        await kernel.stop()


class TestService(unittest.TestCase):
    @run
    async def test_declares_produces_and_reports_health(self):
        async with Harness("memory") as h:
            bus = h.client("bus")
            svc = Service(bus, metrics_interval=0)
            self.assertEqual(svc.name, "bus")
            self.assertEqual(set(svc.produces), {topics.SYSTEM_HEALTH, topics.SYSTEM_METRICS})
            self.assertEqual(svc.consumes, ())
            ctx = Context(name="bus", instance_id="", run_id="r", mode="single", bus=bus, ledger=h.ledger, config={},
                          secrets={}, clock=h.clock, logger=None, data_dir=Path("."))  # type: ignore[arg-type]
            await svc.start(ctx)
            self.assertEqual((await svc.health()).status, "ok")
            bus.metrics.inc("dead", "x")
            self.assertEqual((await svc.health()).status, "degraded")
            self.assertEqual((await svc.health()).status, "ok")  # only the window in which it grew
            h.ledger.fail = True
            bus.trace.write(make_message(topics.TASK_STEP))
            await bus.trace.flush()
            self.assertEqual((await svc.health()).status, "degraded")
            await svc.stop()


if __name__ == "__main__":
    unittest.main()
