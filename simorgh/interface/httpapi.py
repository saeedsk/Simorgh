"""A minimal, stdlib-only HTTP server for Interface's live dashboard.

Pulled forward from roadmap Phase 5's "HTTP/WebSocket API in Interface"
item, scoped down to exactly one read-only concern: let the creator
*see* the running system -- which subsystems are loaded, their state,
bus queue depth and throughput, and what each Orchestration worker is
doing right now -- while actually interacting with it, rather than only
inferring it from what got printed to the REPL. Not the general-purpose
API surface Phase 5 describes; that's still future work.

GET-only, `Connection: close` on every response -- this is a local,
single-viewer status page, not a production HTTP service, so there is
no benefit to the complexity of keep-alive or concurrent-request
pipelining. No third-party dependency (04-build-plan-and-roadmap.md
section 5's "no new third-party dependency in the core"): a hand-rolled
HTTP/1.1 request line + header parse over `asyncio.start_server` is
enough for two routes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_REASONS = {
    200: "OK", 400: "Bad Request", 404: "Not Found",
    405: "Method Not Allowed", 500: "Internal Server Error",
}


class HttpApi:
    def __init__(
        self, bus, *, host: str = "127.0.0.1", port: int = 8765,
        clock=None, status_timeout_s: float = 3.0,
    ) -> None:
        self._bus = bus
        self._host = host
        self._port = port
        self._clock = clock
        self._timeout = status_timeout_s
        self._server: asyncio.base_events.Server | None = None
        self._page = (_STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")

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

        path = path.split("?", 1)[0]
        if path == "/":
            await self._try_respond(writer, 200, self._page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            body = await self._status_json()
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
