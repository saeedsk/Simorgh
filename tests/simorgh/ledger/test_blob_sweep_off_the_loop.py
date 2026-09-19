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


class TheStreamListingRunsOffTheLoop(unittest.IsolatedAsyncioTestCase):
    """`run_compaction` lists every stream (`streams("")`): a `scandir` plus
    a `stat` per file. That walk runs on a worker thread too."""

    async def test_streams_walks_the_directory_on_a_worker_thread(self):
        import os

        from simorgh.contracts.envelope import Event

        with tempfile.TemporaryDirectory() as tmp:
            backend = JsonlBackend(Path(tmp), fsync=False)
            await backend.start()
            await backend.append(Event(stream="task:a", type="t", ts=1.0, trace_id="",
                                       causation_id=None, payload={}), expected_seq=None)
            loop_thread = threading.current_thread()
            seen = []
            real_scandir = os.scandir

            def recording(path):
                seen.append(threading.current_thread())
                return real_scandir(path)

            with mock.patch("simorgh.ledger.backends.jsonl.os.scandir", side_effect=recording):
                names = await backend.streams("")
            self.assertEqual(names, ["task:a"])
            self.assertTrue(seen)
            self.assertTrue(all(t is not loop_thread for t in seen))
