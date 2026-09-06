"""Real Kernel, real HTTP, real sockets: the dashboard's observe tier
(02-system-architecture.md section 6.2) -- metrics history, the logs
viewer, and OS-level process resource usage -- proven against a genuine
`Kernel(..., interactive=True)` boot, not a fake bus/ledger.

Two things a real boot needs handling a fresh `HttpApi`/`Kernel` unit
test doesn't:

- `registry.build_factories` always constructs Interface's `Config`
  with its class defaults (`simorgh/kernel/supervisor.py`'s
  `factories[name]()` takes no `ctx`, so `simorgh.toml [interface]`
  settings never reach it -- a pre-existing gap, not this test's to
  fix), which means the dashboard always binds the fixed port 8765
  through this path. `simorgh.interface.service.Config` is patched for
  the duration of `boot()` to hand back `http_port=0` instead, so this
  test never fights a real port already in use.
- `interactive=True` also starts a real REPL thread blocking on this
  process's own `input()`. `builtins.input` is patched to raise
  `EOFError` immediately so that thread exits the moment it starts
  (`Service._repl_main`'s own `except EOFError: break`) -- the HTTP
  server's own start does not depend on the REPL thread either way.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import tempfile
import unittest
from unittest import mock

from simorgh.interface.config import Config as InterfaceConfig
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


async def _get(port: int, path: str) -> tuple[int, dict]:
    def _do():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    status, body = await asyncio.to_thread(_do)
    return status, json.loads(body)


async def _get_html(port: int, path: str) -> tuple[int, str, str]:
    def _do():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, resp.getheader("Content-Type"), body

    status, content_type, body = await asyncio.to_thread(_do)
    return status, content_type, body.decode("utf-8")


async def _wait_until(predicate, *, timeout_s: float = 5.0, interval_s: float = 0.1):
    """Polls `predicate()` (an async callable returning the value once it
    satisfies, or None) until it stops returning None or `timeout_s`
    elapses -- real wall-clock waiting, needed here because the periodic
    publishers under test run on the real clock this boot uses, and the
    HTTP round trip itself crosses a real socket/thread boundary FakeClock
    tricks cannot shortcut."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while True:
        result = await predicate()
        if result is not None:
            return result
        if loop.time() >= deadline:
            return result
        await asyncio.sleep(interval_s)


class TestDashboardObserveTier(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # A short `metrics_every_s` so the process-metrics publisher and
        # the metrics-history writer (both `simorgh/kernel/metrics.py`,
        # both scheduled off this same runtime knob) fire quickly on the
        # real clock this test uses, instead of the 10s production default.
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name, "metrics_every_s": 0.3}}, None)

        patched_config = mock.patch(
            "simorgh.interface.service.Config", side_effect=lambda: InterfaceConfig(http_port=0),
        )
        patched_input = mock.patch("builtins.input", side_effect=EOFError)
        with patched_config, patched_input:
            self.kernel = Kernel(config, secrets=EnvSecretStore({}), interactive=True)
            await self.kernel.boot()

        iface = self.kernel._supervisor.services["interface"].service  # noqa: SLF001
        self.assertIsNotNone(iface._http)  # noqa: SLF001 -- the dashboard must actually have bound a real port
        self.port = iface._http.port  # noqa: SLF001

    async def asyncTearDown(self):
        await self.kernel.shutdown()
        self._tmp.cleanup()

    async def test_dashboard_root_serves_the_real_page_over_a_real_socket(self):
        status, content_type, body = await _get_html(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("Simorgh", body)

    async def test_api_status_reflects_the_real_running_kernel(self):
        status, body = await _get(self.port, "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["run_id"], self.kernel.run_id)
        self.assertEqual(body["state"], "running")

    async def test_process_gauges_eventually_appear_on_the_same_system_metrics_channel(self):
        async def _check():
            status, body = await _get(self.port, "/api/status")
            process = (body.get("metrics") or {}).get("process")
            return body if process and process.get("gauges") else None

        body = await _wait_until(_check)
        self.assertIsNotNone(body, "process gauges never appeared in /api/status within the timeout")
        gauges = body["metrics"]["process"]["gauges"]
        self.assertIn("threads", gauges)
        self.assertIn("cpu_count", gauges)

    async def test_logs_endpoint_returns_the_boot_time_system_state_event_immediately(self):
        # `system.state` events are appended synchronously during
        # `Kernel.boot()` itself (`_append_state`), so this needs no
        # waiting at all -- unlike the metrics/history endpoints below.
        status, body = await _get(self.port, "/api/logs?stream=system&limit=50")
        self.assertEqual(status, 200)
        self.assertEqual(body["stream"], "system")
        self.assertGreaterEqual(len(body["events"]), 1)
        self.assertTrue(any(e["payload"].get("state") == "running" for e in body["events"]))

    async def test_streams_endpoint_eventually_lists_the_metrics_history_stream(self):
        async def _check():
            status, body = await _get(self.port, "/api/streams")
            return body if "metrics:history" in body.get("streams", []) else None

        body = await _wait_until(_check)
        self.assertIsNotNone(body, "metrics:history never appeared in /api/streams within the timeout")
        self.assertIn("system", body["streams"])

    async def test_history_endpoint_eventually_returns_process_points(self):
        async def _check():
            status, body = await _get(self.port, "/api/history?subsystem=process&minutes=10")
            return body if body.get("points") else None

        body = await _wait_until(_check)
        self.assertIsNotNone(body, "no process history points appeared within the timeout")
        self.assertEqual(body["subsystem"], "process")
        point = body["points"][-1]
        self.assertIn("threads", point["gauges"])

    async def test_history_endpoint_requires_a_subsystem(self):
        status, body = await _get(self.port, "/api/history")
        self.assertEqual(status, 200)
        self.assertEqual(body["error"]["code"], "missing_subsystem")

    async def test_unknown_route_is_still_404_through_the_real_kernel(self):
        status, body = await asyncio.to_thread(lambda: _raw_get(self.port, "/nope"))
        self.assertEqual(status, 404)


def _raw_get(port: int, path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


if __name__ == "__main__":
    unittest.main()
