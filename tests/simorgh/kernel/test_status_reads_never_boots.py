"""`simorgh status` reads, never boots (B17, stage 1 item 9).

(a) nothing running: the last recorded state comes from the ledger files,
    and the ledger is byte-for-byte the same afterwards;
(b) an instance answering `/api/status`: live data, ledger never opened;
(c) the old path -- booting a second `Kernel` -- is gone.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from simorgh.contracts.envelope import Event
from simorgh.kernel import statusread
from simorgh.kernel.cli import main


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _event(stream: str, type_: str, ts: float, payload: dict) -> Event:
    return Event(stream=stream, type=type_, ts=ts, trace_id="t", causation_id=None, payload=payload)


async def _write_ledger(backend) -> None:
    await backend.start()
    try:
        seq = 0
        for i, (state, prev) in enumerate([("booting", "none"), ("running", "booting"), ("stopped", "running")]):
            seq = await backend.append(_event("system", "system.state", 1_700_000_000.0 + i, {
                "state": state, "previous": prev, "reason": "test", "requested_by": "kernel",
                "scope": None, "autonomous_paused": state == "stopped"}), expected_seq=None)
        await backend.append(_event("system", "system.other", 1_700_000_010.0, {"x": 1}), expected_seq=None)
        await backend.append(_event("metrics:history", "system.metrics_history", 1_700_000_005.0,
                                    {"metrics": {"cognition": {"calls": 3}}}), expected_seq=None)
        await backend.append(_event("config:effective", "effective", 1_700_000_000.0, {"hash": "h"}),
                             expected_seq=None)
        del seq
    finally:
        await backend.stop()


def _tree(root: Path) -> dict:
    """Every file under `root` with its size and line count."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            out[str(path.relative_to(root))] = (len(data), data.count(b"\n"))
    return out


class _Base(unittest.TestCase):
    backend = "jsonl"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.port = _free_port()
        self.config_path = Path(self._tmp.name) / "simorgh.toml"
        self.config_path.write_text(
            f'[runtime]\ndata_dir = "{self.data_dir}"\n'
            f'[ledger]\nbackend = "{self.backend}"\n'
            f'[interface]\nhttp_host = "127.0.0.1"\nhttp_port = {self.port}\n'
        )
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("SIM_API_TOKEN", None)
        os.environ.pop("SIMORGH_LEDGER_BACKEND", None)

    def _run_status(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(self.config_path), "status", "--timeout", "0.5"])
        return code, out.getvalue(), err.getvalue()

    def _make_ledger(self) -> Path:
        root = self.data_dir / "ledger"
        if self.backend == "jsonl":
            from simorgh.ledger.backends.jsonl import JsonlBackend

            backend = JsonlBackend(root, fsync=False)
        else:
            from simorgh.ledger.backends.sqlite import SqliteBackend

            backend = SqliteBackend(root / "ledger.sqlite3")
        asyncio.run(_write_ledger(backend))
        return root


class TestNothingRunningReadsTheLedger(_Base):
    def test_prints_the_recorded_state_and_the_ledger_is_unchanged(self):
        root = self._make_ledger()
        before = _tree(root)
        code, out, err = self._run_status()
        self.assertEqual(code, 0, err)
        snapshot = json.loads(out)
        self.assertEqual(snapshot["source"], "ledger")
        self.assertEqual(snapshot["state"], "stopped")  # the last system.state, not the later system.other
        self.assertEqual(snapshot["previous"], "running")
        self.assertTrue(snapshot["autonomous_paused"])
        self.assertEqual(snapshot["metrics"], {"cognition": {"calls": 3}})
        self.assertIn("from the ledger, as of", err)
        self.assertEqual(_tree(root), before)

    def test_a_running_state_nobody_answers_for_is_flagged(self):
        from simorgh.ledger.backends.jsonl import JsonlBackend

        async def write():
            b = JsonlBackend(self.data_dir / "ledger", fsync=False)
            await b.start()
            await b.append(_event("system", "system.state", 1.0, {"state": "running"}), expected_seq=None)
            await b.stop()

        asyncio.run(write())
        code, out, _err = self._run_status()
        self.assertEqual(code, 0)
        snapshot = json.loads(out)
        self.assertEqual(snapshot["state"], "running")
        self.assertIn("may have ended without recording its stop", snapshot["note"])

    def test_an_empty_data_dir_says_nothing_is_recorded_and_creates_nothing(self):
        code, out, err = self._run_status()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["state"], "unknown")
        self.assertIn("nothing recorded", err)
        self.assertFalse(self.data_dir.exists())

    def test_a_torn_last_line_is_skipped_not_repaired(self):
        root = self._make_ledger()
        path = root / "streams" / "system.jsonl"
        with open(path, "ab") as fh:
            fh.write(b'{"type": "system.state", "payload": {"sta')
        before = path.read_bytes()
        code, out, _ = self._run_status()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["state"], "stopped")
        self.assertEqual(path.read_bytes(), before)

    def test_the_old_boot_path_is_gone(self):
        self._make_ledger()
        boom = AssertionError("status must not construct a Kernel")
        with mock.patch("simorgh.kernel.cli.Kernel", side_effect=boom), \
                mock.patch("simorgh.kernel.service.Kernel", side_effect=boom):
            code, out, err = self._run_status()
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["source"], "ledger")


class TestSqliteLedger(_Base):
    backend = "sqlite"

    def test_reads_the_sqlite_ledger_read_only(self):
        root = self._make_ledger()
        before = _tree(root)
        code, out, err = self._run_status()
        self.assertEqual(code, 0, err)
        snapshot = json.loads(out)
        self.assertEqual((snapshot["source"], snapshot["state"]), ("ledger", "stopped"))
        self.assertEqual(snapshot["metrics"], {"cognition": {"calls": 3}})
        self.assertEqual(_tree(root), before)


class _StatusHandler(BaseHTTPRequestHandler):
    seen_auth: list = []

    def do_GET(self):  # noqa: N802
        type(self).seen_auth.append(self.headers.get("Authorization"))
        if self.path != "/api/status":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"run_id": "r1", "mode": "single", "state": "running", "autonomous_paused": False,
                           "uptime_seconds": 12.5, "subsystems": [{"name": "bus", "status": "healthy"}],
                           "metrics": {}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


class TestALiveInstanceAnswers(_Base):
    def setUp(self):
        super().setUp()
        _StatusHandler.seen_auth = []
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), _StatusHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_prints_live_data_and_never_opens_the_ledger(self):
        os.environ["SIM_API_TOKEN"] = "sekret"
        never = AssertionError("the ledger must not be read when the instance answered")
        with mock.patch.object(statusread, "last_event", side_effect=never), \
                mock.patch.object(statusread, "from_ledger", side_effect=never), \
                mock.patch("simorgh.kernel.cli.Kernel", side_effect=never):
            code, out, err = self._run_status()
        self.assertEqual(code, 0, err)
        snapshot = json.loads(out)
        self.assertEqual(snapshot["source"], "live")
        self.assertEqual(snapshot["run_id"], "r1")
        self.assertEqual(snapshot["subsystems"][0]["name"], "bus")
        self.assertIn("status: live", err)
        self.assertEqual(_StatusHandler.seen_auth, ["Bearer sekret"])
        self.assertFalse(self.data_dir.exists())


class TestStatusUrl(unittest.TestCase):
    def test_a_wildcard_bind_is_asked_on_loopback(self):
        from simorgh.kernel.config import LoadedConfig

        cfg = LoadedConfig({"interface": {"http_host": "0.0.0.0", "http_port": 9999}}, None)
        self.assertEqual(statusread.status_url(cfg), "http://127.0.0.1:9999/api/status")

    def test_the_default_is_the_interface_default(self):
        from simorgh.interface.config import Config as InterfaceConfig
        from simorgh.kernel.config import LoadedConfig

        d = InterfaceConfig()
        self.assertEqual(statusread.status_url(LoadedConfig({}, None)),
                         f"http://{d.http_host}:{d.http_port}/api/status")


if __name__ == "__main__":
    unittest.main()
