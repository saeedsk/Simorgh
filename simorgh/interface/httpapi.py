"""A minimal, stdlib-only HTTP server for Interface's live dashboard.

Pulled forward from roadmap Phase 5's "HTTP/WebSocket API in Interface"
item, scoped to three concerns: let the creator *see* the running
system (subsystem status, bus/worker/cognition/memory/process metrics,
metrics history, logs), *talk* to it from the same page (asked for
directly after the REPL's own `chat_reply_timeout_s`/`think_timeout_s`
wiring bug made a real answer look like a hang), and browse what's
already durable without a new capability. Not the general-purpose
multi-session API Phase 5 describes (02-system-architecture.md section
6.1); one chat box, one turn in flight at a time, no session history --
that's still future work.

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
that only care about `/`, `/api/status`, or `/api/chat`); the three new
routes degrade to an honest `{"error": ...}` body rather than a 500
when it is absent, same "unreachable kernel is data for the page"
posture `/api/status` already has.

GET and POST only, `Connection: close` on every response -- this is a
local, single-viewer page, not a production HTTP service, so there is
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
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
        self, bus, *, ledger=None, host: str = "127.0.0.1", port: int = 8765,
        clock=None, status_timeout_s: float = 3.0, chat_timeout_s: float = 130.0,
        history_stream: str = "metrics:history", history_default_minutes: float = 10.0,
        history_max_points: int = 500, logs_default_limit: int = 100, logs_max_limit: int = 500,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._host = host
        self._port = port
        self._clock = clock
        self._timeout = status_timeout_s
        self._chat_timeout = chat_timeout_s
        self._history_stream = history_stream
        self._history_default_minutes = history_default_minutes
        self._history_max_points = max(1, history_max_points)
        self._logs_default_limit = logs_default_limit
        self._logs_max_limit = max(1, logs_max_limit)
        self._server: asyncio.base_events.Server | None = None
        self._page = (_STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
        self._pending_chats: dict[str, asyncio.Future] = {}
        self._turn_sub = None

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
        self._turn_sub = await self._bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed)
        # Live activity feed (07-post-cutover-review.md §3.9): the same
        # events the REPL narrates, kept in a small in-memory ring so
        # `/api/activity` answers "what is Sim doing right now / just did"
        # from the bus as it happens -- no Ledger scan across hundreds of
        # `task:*` streams, no polling of counters that can't answer it.
        self._activity_subs = [
            await self._bus.subscribe(t, self._on_activity)
            for t in (topics.TASK_STARTED, topics.TASK_STEP, topics.TASK_COMPLETED, topics.TASK_FAILED,
                      topics.TASK_BLOCKED, topics.ACTION_RESULT, topics.ACTION_DENIED, topics.TURN_COMPLETED,
                      topics.PERCEPT_TEXT_RECEIVED)
        ]
        self._server = await asyncio.start_server(self._handle, self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._turn_sub is not None:
            await self._turn_sub.unsubscribe()
            self._turn_sub = None
        for sub in getattr(self, "_activity_subs", []):
            await sub.unsubscribe()
        self._activity_subs = []

    async def _on_turn_completed(self, message: Message) -> None:
        fut = self._pending_chats.get(message.payload.get("session_id", ""))
        if fut is not None and not fut.done():
            fut.set_result(message.payload)

    _ACTIVITY_MAX = 200

    async def _on_activity(self, message: Message) -> None:
        p = message.payload
        entry = {"ts": self._now(), "type": message.type, "task_id": p.get("task_id") or p.get("session_id", "")}
        if message.type == topics.TASK_STEP:
            entry.update(step_no=p.get("step_no"), phase=p.get("phase"), summary=p.get("summary", ""),
                         tool=p.get("tool"), ok=p.get("ok"))
        elif message.type == topics.TASK_COMPLETED:
            entry.update(summary=(p.get("result_summary") or "")[:160])
        elif message.type in (topics.TASK_FAILED, topics.TASK_BLOCKED):
            entry.update(summary=p.get("reason", ""))
        elif message.type == topics.ACTION_RESULT:
            entry.update(action_id=p.get("action_id"), ok=p.get("ok"), duration_ms=p.get("duration_ms"),
                         summary=(p.get("error") or p.get("stdout_preview") or "")[:160])
        elif message.type == topics.ACTION_DENIED:
            entry.update(action_id=p.get("action_id"), ok=False, summary="denied: " + "; ".join(p.get("reasons", [])))
        elif message.type == topics.TURN_COMPLETED:
            entry.update(summary=(p.get("text") or "")[:160], floor=p.get("floor", False))
        elif message.type == topics.PERCEPT_TEXT_RECEIVED:
            entry.update(summary=(p.get("text") or "")[:160], channel=p.get("channel"))
        activity = getattr(self, "_activity", None)
        if activity is None:
            self._activity = activity = []
        activity.append(entry)
        if len(activity) > self._ACTIVITY_MAX:
            del activity[: len(activity) - self._ACTIVITY_MAX]

    async def _activity_json(self, query: dict) -> bytes:
        limit = min(int(self._q1(query, "limit", "50") or 50), self._ACTIVITY_MAX)
        items = list(getattr(self, "_activity", []))[-limit:]
        items.reverse()  # newest first
        pending = sorted(self._pending_chats)
        return json.dumps({"now": self._now(), "pending_turns": pending, "events": items}).encode("utf-8")

    # -- connection handling -----------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # The outer ceiling has to cover the slowest legitimate route
        # (chat, up to `chat_timeout_s`) plus real margin -- header
        # parsing itself is negligible in practice, so this isn't
        # trading away slow-loris protection, just not bounding a real
        # in-flight answer to a fixed 10s (the exact class of bug
        # `chat_reply_timeout_s`/`think_timeout_s` had elsewhere).
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

        split = urlsplit(path)
        route, query = split.path, parse_qs(split.query)
        if method == "GET" and route == "/":
            await self._try_respond(writer, 200, self._page.encode("utf-8"), "text/html; charset=utf-8")
        elif method == "GET" and route == "/api/status":
            body = await self._status_json()
            await self._try_respond(writer, 200, body, "application/json")
        elif method == "GET" and route == "/api/history":
            body = await self._history_json(query)
            await self._try_respond(writer, 200, body, "application/json")
        elif method == "GET" and route == "/api/logs":
            body = await self._logs_json(query)
            await self._try_respond(writer, 200, body, "application/json")
        elif method == "GET" and route == "/api/streams":
            body = await self._streams_json()
            await self._try_respond(writer, 200, body, "application/json")
        elif method == "GET" and route == "/api/activity":
            body = await self._activity_json(query)
            await self._try_respond(writer, 200, body, "application/json")
        elif method == "POST" and route == "/api/chat":
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
            body = json.loads(raw or b"{}")
            text = str(body.get("text", "")).strip()
            client_session_id = body.get("session_id")
            client_session_id = str(client_session_id).strip() if client_session_id else None
        except json.JSONDecodeError:
            await self._try_respond(writer, 400, b'{"error":"invalid json"}', "application/json")
            return
        if not text:
            await self._try_respond(writer, 400, b'{"error":"empty message"}', "application/json")
            return

        payload = await self._chat(text, session_id=client_session_id)
        status = 409 if payload.get("error") == "turn already in flight" else 200
        await self._try_respond(writer, status, json.dumps(payload).encode("utf-8"), "application/json")

    async def _chat(self, text: str, *, session_id: str | None = None) -> dict:
        """One dashboard chat turn: publish `percept.text.received` and
        await the matching `turn.completed` -- the same request/await-a-
        correlated-event shape `Interface._handle_chat` already uses for
        the REPL.

        `session_id` is optional and, when a caller supplies one, is
        reused as-is rather than replaced -- 02-system-architecture.md
        section 6.1's own multi-session direction: Memory's episodic
        write (milestone 105) groups turns by exactly this field, so a
        client that wants a real, continuous conversation (not a fresh
        stranger every message) sends the same id every time. The
        dashboard page does this automatically (one id generated per
        page load). When no caller supplies one, a fresh uuid is
        generated, preserving milestone 106's original fix (never a
        *shared, hardcoded* key).

        A second, real risk that fix didn't have to consider: an
        externally-supplied session_id could legitimately collide if a
        client fires two requests for the same conversation before the
        first resolves. Milestone 106's bug was a fixed key being
        silently overwritten mid-flight, corrupting which reply answered
        which prompt; the fix there was "never share a key." Now that a
        caller can ask to share one on purpose, silently overwriting is
        exactly as wrong as it was then -- so this refuses the second
        request outright (a clear `"turn already in flight"` error,
        HTTP 409) instead of ever letting two futures alias the same
        dict entry. The dashboard's own UI already serializes one tab's
        sends (the input is disabled while a reply is pending), so this
        only ever fires for a genuinely concurrent caller, not normal use.
        `channel: "api"` -- the wire enum (`percept.text.received`'s
        `channel`) is closed (`cli|api|chat|command`); a live-caught bug
        used `"dashboard"` here originally and every publish 500'd on
        real contract validation (milestone 116)."""
        session_id = session_id or str(uuid.uuid4())
        if session_id in self._pending_chats:
            return {"text": "", "floor": True, "error": "turn already in flight"}
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_chats[session_id] = fut
        try:
            await self._bus.publish(Message.new(
                topics.PERCEPT_TEXT_RECEIVED, source="interface",
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
