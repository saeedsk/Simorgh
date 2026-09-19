"""The blob sweep reads every stream file; it runs on a worker thread,
not on the event loop (2026-09-18 evaluation, B1)."""

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from simorgh.ledger.backends.jsonl import JsonlBackend


class TheSweepRunsOffTheLoop(unittest.IsolatedAsyncioTestCase):
    async def test_the_loop_keeps_turning_while_the_sweep_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = JsonlBackend(Path(tmp), fsync=False)
            loop_thread = threading.current_thread()
            seen = {}
            original = backend._sweep_unreferenced_blobs_sync  # noqa: SLF001

            def slow(grace):
                seen["thread"] = threading.current_thread()
                import time
                time.sleep(0.3)
                return original(grace)

            ticks = 0

            async def heartbeat():
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.02)
                    ticks += 1

            beat = asyncio.create_task(heartbeat())
            with mock.patch.object(backend, "_sweep_unreferenced_blobs_sync", side_effect=slow):
                removed = await backend.sweep_unreferenced_blobs()
            beat.cancel()
            self.assertEqual(removed, 0)
            self.assertIsNot(seen["thread"], loop_thread)
            self.assertGreater(ticks, 5, "the event loop kept running during the sweep")
