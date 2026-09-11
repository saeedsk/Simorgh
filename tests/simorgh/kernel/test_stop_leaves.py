"""A signal ends the process (kernel/cli.py, 2026-09-11).

Reproduced live: with one tool thread busy (a pytest, a whisper-cli),
SIGTERM put Sim into "stopping" and the process stayed for minutes,
because asyncio's teardown joins worker threads; the second signal's
`sys.exit` raised into that same teardown and changed nothing. Now the
first signal asks for a stop and starts a clock, the second leaves at
once, and an orderly shutdown leaves without waiting on threads. The
exit itself is patched here -- the real one is `os._exit`."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from simorgh.kernel import cli
from simorgh.kernel.supervisor import Supervisor
from simorgh.contracts.protocols import Health


class _Bus:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, message) -> None:
        self.published.append(message)


class TestStopper(unittest.IsolatedAsyncioTestCase):
    async def test_first_signal_asks_for_a_stop_and_arms_the_clock(self) -> None:
        bus = _Bus()
        exits = []
        with mock.patch.object(cli, "_HARD_EXIT", exits.append), mock.patch.object(cli, "_terminate_children"):
            stopper = cli.Stopper(bus, hard_exit_s=60.0)
            stopper.on_signal()
            await asyncio.sleep(0)
        self.assertEqual(len(bus.published), 1)
        self.assertEqual(bus.published[0].payload["reason"], "signal")
        self.assertEqual(exits, [])
        stopper.cancel()

    async def test_second_signal_leaves_at_once(self) -> None:
        bus = _Bus()
        exits = []
        with mock.patch.object(cli, "_HARD_EXIT", exits.append), mock.patch.object(cli, "_terminate_children"):
            stopper = cli.Stopper(bus, hard_exit_s=60.0)
            stopper.on_signal()
            stopper.on_signal()
            await asyncio.sleep(0)
        self.assertEqual(exits, [130])
        stopper.cancel()

    async def test_the_clock_running_out_leaves(self) -> None:
        bus = _Bus()
        exits = []
        with mock.patch.object(cli, "_HARD_EXIT", exits.append), mock.patch.object(cli, "_terminate_children"):
            stopper = cli.Stopper(bus, hard_exit_s=0.05)
            stopper.on_signal()
            await asyncio.sleep(0.2)
        self.assertEqual(exits, [1])

    async def test_a_cancelled_clock_does_not_fire(self) -> None:
        bus = _Bus()
        exits = []
        with mock.patch.object(cli, "_HARD_EXIT", exits.append), mock.patch.object(cli, "_terminate_children"):
            stopper = cli.Stopper(bus, hard_exit_s=0.05)
            stopper.on_signal()
            stopper.cancel()
            await asyncio.sleep(0.2)
        self.assertEqual(exits, [])


class TestExitNow(unittest.TestCase):
    def test_exit_now_flushes_terminates_children_and_exits(self) -> None:
        calls = []
        with mock.patch.object(cli, "_HARD_EXIT", calls.append), \
             mock.patch.object(cli, "_terminate_children", lambda: calls.append("children")), \
             mock.patch("sys.stdin", None):
            cli._exit_now(3, why="because")
        self.assertEqual(calls, ["children", 3])


class _Slow:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    async def start(self, ctx) -> None:
        pass

    async def stop(self) -> None:
        await asyncio.sleep(self._seconds)

    async def health(self) -> Health:
        return Health.ok()


class TestStopAllBudget(unittest.IsolatedAsyncioTestCase):
    async def test_the_grace_is_shared_across_layers_not_per_layer(self) -> None:
        sup = Supervisor(clock=mock.MagicMock(), logger=mock.MagicMock(), backoff_s=(0.1,),
                         max_restarts_per_window=1)
        for i in range(3):
            sup.services[f"s{i}"] = mock.MagicMock(service=_Slow(10.0), status="ok")
        loop = asyncio.get_running_loop()
        started = loop.time()
        await sup.stop_all([("s0",), ("s1",), ("s2",)], grace_s=1.0)
        self.assertLess(loop.time() - started, 3.5)  # 1s budget + two 0.5s floors, not 30s
        self.assertTrue(all(sup.services[f"s{i}"].status == "stopped" for i in range(3)))


if __name__ == "__main__":
    unittest.main()
