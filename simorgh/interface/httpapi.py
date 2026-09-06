"""A minimal, stdlib-only HTTP server for Interface's live dashboard.

Pulled forward from roadmap Phase 5's "HTTP/WebSocket API in Interface"
item, scoped down to two concerns: let the creator *see* the running
system (subsystem status, bus/worker/cognition/memory metrics) and now
also *talk* to it from the same page, rather than only through the
REPL's own stdin -- asked for directly after the REPL's own `chat_reply_
timeout_s`/`think_timeout_s` wiring bug (fixed alongside this) made a
real answer look like a hang. Not the general-purpose multi-session API
Phase 5 describes (02-system-architecture.md section 6.1); one chat
box, one turn in flight at a time, no session history -- that's still
future work.

GET and POST only, `Connection: close` on every response -- this is a
local, single-viewer page, not a production HTTP service, so there is
no benefit to the complexity of keep-alive or concurrent-request
pipelining. No third-party dependency (04-build-plan-and-roadmap.md
section 5's "no new third-party dependency in the core"): a hand-rolled
HTTP/1.1 request line + header parse over `asyncio.start_server` is
enough for three routes.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_REASONS = {
    200: "OK", 400: "Bad Request", 404: "Not Found",
    405: "Method Not Allowed", 413: "Payload Too Large", 500: "Internal Server Error",
}

_MAX_BODY_BYTES = 16 * 1024  # a chat message, not a file upload


class HttpApi:
    def __init__(
        self, bus, *, host: str = "127.0.0.1", port: int = 8765,
        clock=None, status_timeout_s: float = 3.0, chat_timeout_s: float = 130.0,
    ) -> None:
        self._bus = bus
        self._host = host
        self._port = port
        self._clock = clock
        self._timeout = status_timeout_s
        self._chat_timeout = chat_timeout_s
        self._server: asyncio.base_events.Server | None = None
        self._page = (_STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
        self._pending_chats: dict[str, asyncio.Future] = {}
        self._turn_sub = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/"

    @property
    def port(self) -> int:
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def start(self) -> None:
        self._turn_sub = await self._bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed)
        self._server = await asyncio.start_server(self._handle, self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._turn_sub is not None:
            await self._turn_sub.unsubscribe()
            self._turn_sub = None

    async def _on_turn_completed(self, message: Message) -> None:
        fut = self._pending_chats.get(message.payload.get("session_id", ""))
        if fut is not None and not fut.done():
            fut.set_result(message.payload)

    # -- connection handling -----------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # The outer ceiling has to cover the slowest legitimate route
        # (chat, up to `chat_timeout_s`) plus real margin -- header
        # parsing itself is negligible in practice, so this isn't
        # trading away slow-loris protection, just not bounding a real
        # in-flight answer to a fixed 10s the way an earlier version of
        # this file did (the exact class of bug `chat_reply_timeout_s`/
        # `think_timeout_s` had elsewhere).
        try:
            await asyncio.wait_for(self._handle_one(reader, writer), timeout=self._chat_timeout + 15.0)
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
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").partition(":")
            if value:
                headers[name.strip().lower()] = value.strip()

        try:
            method, path, _version = request_line.decode("latin-1").strip().split(" ", 2)
        except ValueError:
            await self._try_respond(writer, 400, b"bad request", "text/plain; charset=utf-8")
            return

        path = path.split("?", 1)[0]
        if method == "GET" and path == "/":
            await self._try_respond(writer, 200, self._page.encode("utf-8"), "text/html; charset=utf-8")
        elif method == "GET" and path == "/api/status":
            body = await self._status_json()
            await self._try_respond(writer, 200, body, "application/json")
        elif method == "POST" and path == "/api/chat":
            await self._handle_chat_request(reader, writer, headers)
        elif method not in ("GET", "POST"):
            await self._try_respond(writer, 405, b"method not allowed", "text/plain; charset=utf-8")
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

    async def _handle_chat_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, headers: dict[str, str],
    ) -> None:
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            await self._try_respond(writer, 400, b'{"error":"bad content-length"}', "application/json")
            return
        if length > _MAX_BODY_BYTES:
            await self._try_respond(writer, 413, b'{"error":"message too large"}', "application/json")
            return
        raw = await reader.readexactly(length) if length else b""
        try:
            text = str(json.loads(raw or b"{}").get("text", "")).strip()
        except json.JSONDecodeError:
            await self._try_respond(writer, 400, b'{"error":"invalid json"}', "application/json")
            return
        if not text:
            await self._try_respond(writer, 400, b'{"error":"empty message"}', "application/json")
            return

        payload = await self._chat(text)
        await self._try_respond(writer, 200, json.dumps(payload).encode("utf-8"), "application/json")

    async def _chat(self, text: str) -> dict:
        """One dashboard chat turn: publish `percept.text.received` and
        await the matching `turn.completed` -- the same request/await-a-
        correlated-event shape `Interface._handle_chat` already uses for
        the REPL (milestone 106's fresh-id-per-turn fix applies here
        too: a fresh uuid per call, never a shared key, so two dashboard
        tabs chatting at once can never cross-wire each other's replies)."""
        session_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_chats[session_id] = fut
        try:
            await self._bus.publish(Message.new(
                topics.PERCEPT_TEXT_RECEIVED, source="interface",
                # "dashboard" is not a valid `channel` -- the wire enum
                # is a closed set (`cli|api|chat|command`, `contracts/
                # messages/percept.py`) and publishing an invalid value
                # raises inside `bus.publish()`'s own validation, live-
                # caught as a real 500 the first time this endpoint was
                # actually exercised from a browser. "api" is correct:
                # this is exactly a programmatic client, not the REPL.
                payload={"channel": "api", "text": text, "session_id": session_id},
                clock=self._clock,
            ))
            try:
                turn = await asyncio.wait_for(fut, timeout=self._chat_timeout)
                return {"text": turn.get("text", ""), "floor": bool(turn.get("floor", False))}
            except asyncio.TimeoutError:
                return {"text": "", "floor": True, "error": "no response in time"}
        finally:
            self._pending_chats.pop(session_id, None)

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
