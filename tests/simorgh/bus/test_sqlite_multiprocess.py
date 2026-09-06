"""Two processes share one SQLite bus file: a consumer process claims a
durable competing delivery enqueued by the parent, and a lease held by a
dead process is reaped so another consumer picks the message up
(docs/blueprint/subsystems/01-bus.md section 5.4; Flow 7)."""

import asyncio
import json
import multiprocessing as mp
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.bus.backends.sqlite import SqliteBackend
from simorgh.bus.client import BusClient
from simorgh.bus.config import Config
from simorgh.contracts import topics

from tests.simorgh.helpers import make_message


def _consumer(path: str, out: str, source: str) -> None:
    async def main():
        backend = SqliteBackend(path, clock=time.time, poll_interval_ms=5)
        bus = BusClient(backend, source=source, clock=time.time, config=Config(metrics_interval_seconds=0))
        done = asyncio.Event()

        async def handler(m):
            Path(out).write_text(json.dumps({"id": m.id, "pid": os.getpid()}))
            done.set()

        await bus.start()
        await bus.subscribe(topics.TASK_AVAILABLE, handler, group="workers", durable=True)
        try:
            await asyncio.wait_for(done.wait(), timeout=10)
        finally:
            await bus.stop()

    asyncio.run(main())


class TestSqliteMultiprocess(unittest.TestCase):
    def test_child_process_consumes_a_durable_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bus.sqlite")
            out = str(Path(tmp) / "out.json")
            ctx = mp.get_context("spawn")

            async def parent():
                backend = SqliteBackend(path, clock=time.time, poll_interval_ms=5)
                bus = BusClient(backend, source="planning", clock=time.time, config=Config(metrics_interval_seconds=0))
                await bus.start()
                # register the durable group first so the delivery row is fanned out even before the child polls
                await bus.subscribe(topics.TASK_AVAILABLE, lambda m: asyncio.sleep(3600), group="workers", durable=True, max_inflight=0)
                m = make_message(topics.TASK_AVAILABLE, source="planning", partition_key="task:t1")
                await bus.publish(m)
                await bus.stop()
                return m.id

            message_id = asyncio.run(parent())
            child = ctx.Process(target=_consumer, args=(path, out, "orchestration@w2"))
            child.start()
            child.join(timeout=20)
            self.assertEqual(child.exitcode, 0)
            result = json.loads(Path(out).read_text())
            self.assertEqual(result["id"], message_id)
            self.assertNotEqual(result["pid"], os.getpid())

    def test_expired_lease_of_a_dead_process_is_reaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bus.sqlite")

            async def main():
                now = [1000.0]
                backend = SqliteBackend(path, clock=lambda: now[0], poll_interval_ms=5, lease_seconds=5.0)
                bus = BusClient(backend, source="planning", clock=lambda: now[0], config=Config(metrics_interval_seconds=0))
                await bus.start()
                await bus.subscribe(topics.TASK_AVAILABLE, lambda m: asyncio.sleep(3600), group="workers", durable=True, max_inflight=0)
                m = make_message(topics.TASK_AVAILABLE, source="planning", partition_key="task:t1", clock=lambda: now[0])
                await bus.publish(m)
                # simulate another process that leased it and died
                db = sqlite3.connect(path)
                db.execute("UPDATE deliveries SET state='leased', lease_until=? WHERE message_id=?", (now[0] + 5.0, m.id))
                db.execute("INSERT INTO partition_locks VALUES('workers','task:t1','ghost',?)", (now[0] + 5.0,))
                db.commit(); db.close()
                now[0] += 10.0  # lease expires
                await asyncio.sleep(0.1)  # reaper runs
                db = sqlite3.connect(path)
                state, attempt = db.execute("SELECT state, attempt FROM deliveries WHERE message_id=?", (m.id,)).fetchone()
                locks = db.execute("SELECT COUNT(*) FROM partition_locks").fetchone()[0]
                db.close()
                await bus.stop()
                return state, attempt, locks

            state, attempt, locks = asyncio.run(main())
            self.assertEqual(state, "pending")
            self.assertEqual(attempt, 2)
            self.assertEqual(locks, 0)


if __name__ == "__main__":
    unittest.main()
