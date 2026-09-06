"""A minimal, stdlib-only HTTP server for Interface's live dashboard.

Pulled forward from roadmap Phase 5's "HTTP/WebSocket API in Interface"
item, scoped down to exactly one read-only concern: let the creator
*see* the running system -- which subsystems are loaded, their state,
bus queue depth and throughput, and what each Orchestration worker is
doing right now -- while actually interacting with it, rather than only
inferring it from what got printed to the REPL. Not the general-purpose
API surface Phase 5 describes; that's still future work.

Extended for the observe tier (02-system-architecture.md section 6.2,
captured right after the creator saw the first version run live):
`/api/history` (metrics over time, read from the Kernel's own
`metrics:history` Ledger stream -- see `simorgh/kernel/metrics.py`'s
`MetricsHistoryWriter`), `/api/logs` (a tail of any Ledger stream --
"structured logs are Ledger events," section 7), and `/api/streams`
(which streams currently exist, for a stream picker). All three are
read-only queries against the same `Ledger` protocol every subsystem
already gets from its own `Context` -- no new capability, just a new
surface over data that was already durable and already queryable.
`ledger` is optional (`None` in the handful of existing tests/callers
that only care about `/` and `/api/status`); the three new routes
degrade to an honest `{"error": ...}` body rather than a 500 when it is
absent, same "unreachable kernel is data for the page" posture
`/api/status` already has.

GET-only, `Connection: close` on every response -- this is a local,
single-viewer status page, not a production HTTP service, so there is
no benefit to the complexity of keep-alive or concurrent-request
pipelining. No third-party dependency (04-build-plan-and-roadmap.md
section 5's "no new third-party dependency in the core"): a hand-rolled
HTTP/1.1 request line + header parse over `asyncio.start_server` is
enough for a handful of routes.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_REASONS = {
    200: "OK", 400: "Bad Request", 404: "Not Found",
    405: "Method Not Allowed", 500: "Internal Server Error",
}


class HttpApi:
    def __init__(
        self, bus, *, ledger=None, host: str = "127.0.0.1", port: int = 8765,
        clock=None, status_timeout_s: float = 3.0,
        history_stream: str = "metrics:history", history_default_minutes: float = 10.0,
        history_max_points: int = 500, logs_default_limit: int = 100, logs_max_limit: int = 500,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._host = host
        self._port = port
        self._clock = clock
        self._timeout = status_timeout_s
        self._history_stream = history_stream
        self._history_default_minutes = history_default_minutes
        self._history_max_points = max(1, history_max_points)
        self._logs_default_limit = logs_default_limit
        self._logs_max_limit = max(1, logs_max_limit)
        self._server: asyncio.base_events.Server | None = None
        self._page = (_STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.time()

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/"

    @property
    def port(self) -> int:
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # -- connection handling -----------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(self._handle_one(reader, writer), timeout=10.0)
        except (asyncio.TimeoutError, ConnectionError):
            pass
        except Exception as exc:  # noqa: BLE001 -- one bad request must never take the server down
            await self._try_respond(writer, 500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _handle_one(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = await reader.readline()
        if not request_line:
            return
        while True:  # drain and discard headers -- nothing here reads a body or needs one
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        try:
            method, path, _version = request_line.decode("latin-1").strip().split(" ", 2)
        except ValueError:
            await self._try_respond(writer, 400, b"bad request", "text/plain; charset=utf-8")
            return
        if method != "GET":
            await self._try_respond(writer, 405, b"method not allowed", "text/plain; charset=utf-8")
            return

        split = urlsplit(path)
        route, query = split.path, parse_qs(split.query)
        if route == "/":
            await self._try_respond(writer, 200, self._page.encode("utf-8"), "text/html; charset=utf-8")
        elif route == "/api/status":
            body = await self._status_json()
            await self._try_respond(writer, 200, body, "application/json")
        elif route == "/api/history":
            body = await self._history_json(query)
            await self._try_respond(writer, 200, body, "application/json")
        elif route == "/api/logs":
            body = await self._logs_json(query)
            await self._try_respond(writer, 200, body, "application/json")
        elif route == "/api/streams":
            body = await self._streams_json()
            await self._try_respond(writer, 200, body, "application/json")
        else:
            await self._try_respond(writer, 404, b"not found", "text/plain; charset=utf-8")

    async def _status_json(self) -> bytes:
        req = Message.new(topics.SYSTEM_STATUS_REQUEST, source="interface", payload={}, clock=self._clock)
        try:
            reply = await self._bus.request_or_error(req, timeout=self._timeout)
            payload = reply.payload
        except Exception as exc:  # noqa: BLE001 -- an unreachable kernel is data for the page, not a crash
            payload = {"state": "unknown", "error": {"code": "status_unavailable", "detail": str(exc)}}
        return json.dumps(payload, default=str).encode("utf-8")

    @staticmethod
    def _q1(query: dict, key: str, default: str | None) -> str | None:
        values = query.get(key)
        return values[0] if values else default

    async def _read_tail(self, stream: str, cap: int) -> list:
        """The last `cap` events of `stream`, oldest first. `head()` is
        `LedgerClient`-specific (not part of the narrower
        `contracts.protocols.Ledger` every subsystem is typed against),
        but Interface's `ctx.ledger` is always a real `LedgerClient` in
        practice -- same duck-typing `kernel/scheduler.py`'s own
        `materialize()` call already relies on. Falls back to reading
        from the start and slicing when a caller's `ledger` (a test
        fake, most likely) doesn't have it."""
        head = getattr(self._ledger, "head", None)
        if head is not None:
            total = await head(stream)
            start = max(1, total - cap + 1)
            return await self._ledger.read(stream, from_seq=start, limit=cap)
        events = await self._ledger.read(stream, from_seq=0, limit=None)
        return events[-cap:]

    async def _history_json(self, query: dict) -> bytes:
        subsystem = self._q1(query, "subsystem", None)
        if not subsystem:
            return json.dumps({"error": {"code": "missing_subsystem",
                                          "detail": "subsystem query param is required"}}).encode("utf-8")
        try:
            minutes = float(self._q1(query, "minutes", None) or self._history_default_minutes)
        except ValueError:
            minutes = self._history_default_minutes
        minutes = max(0.5, min(minutes, 24 * 60.0))
        if self._ledger is None:
            return json.dumps({"subsystem": subsystem, "minutes": minutes, "points": [],
                                "error": {"code": "ledger_unavailable"}}).encode("utf-8")
        try:
            events = await self._read_tail(self._history_stream, self._history_max_points)
        except Exception as exc:  # noqa: BLE001 -- a bad read is data for the page, not a crash
            return json.dumps({"subsystem": subsystem, "minutes": minutes, "points": [],
                                "error": {"code": "history_unavailable", "detail": str(exc)}}).encode("utf-8")
        cutoff = self._now() - minutes * 60.0
        points = []
        for event in events:
            if event.ts is not None and event.ts < cutoff:
                continue
            entry = (event.payload.get("metrics") or {}).get(subsystem)
            if entry is None:
                continue
            points.append({"ts": event.ts, "counters": entry.get("counters", {}), "gauges": entry.get("gauges", {})})
        return json.dumps({"subsystem": subsystem, "minutes": minutes, "points": points},
                          default=str).encode("utf-8")

    async def _logs_json(self, query: dict) -> bytes:
        stream = self._q1(query, "stream", "system")
        try:
            limit = int(self._q1(query, "limit", None) or self._logs_default_limit)
        except ValueError:
            limit = self._logs_default_limit
        limit = max(1, min(limit, self._logs_max_limit))
        if self._ledger is None:
            return json.dumps({"stream": stream, "events": [],
                                "error": {"code": "ledger_unavailable"}}).encode("utf-8")
        try:
            events = await self._read_tail(stream, limit)
        except Exception as exc:  # noqa: BLE001 -- a bad read is data for the page, not a crash
            return json.dumps({"stream": stream, "events": [],
                                "error": {"code": "logs_unavailable", "detail": str(exc)}}).encode("utf-8")
        body = {"stream": stream, "events": [
            {"seq": e.seq, "ts": e.ts, "type": e.type, "trace_id": e.trace_id,
             "causation_id": e.causation_id, "payload": e.payload}
            for e in events
        ]}
        return json.dumps(body, default=str).encode("utf-8")

    async def _streams_json(self) -> bytes:
        if self._ledger is None:
            return json.dumps({"streams": [], "error": {"code": "ledger_unavailable"}}).encode("utf-8")
        try:
            names = await self._ledger.streams("")
        except Exception as exc:  # noqa: BLE001 -- a bad read is data for the page, not a crash
            return json.dumps({"streams": [], "error": {"code": "streams_unavailable",
                                                          "detail": str(exc)}}).encode("utf-8")
        return json.dumps({"streams": names}).encode("utf-8")

    async def _try_respond(self, writer: asyncio.StreamWriter, status: int, body: bytes, content_type: str) -> None:
        headers = (
            f"HTTP/1.1 {status} {_REASONS.get(status, '')}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "Cache-Control: no-store\r\n"
            "\r\n"
        ).encode("latin-1")
        writer.write(headers + body)
        await writer.drain()


__all__ = ["HttpApi"]
