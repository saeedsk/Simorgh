"""HttpApi: the live-status dashboard's server (simorgh/interface/httpapi.py).
Real sockets, real HTTP/1.1 requests via `http.client` -- this module
hand-rolls request parsing, so the thing actually worth testing is what
a real client sees on the wire, not a mocked reader/writer."""

from __future__ import annotations

import asyncio
import http.client
import json
import unittest
from pathlib import Path

from simorgh.contracts.envelope import Event
from simorgh.interface.httpapi import HttpApi


class _FakeReply:
    def __init__(self, payload: dict) -> None:
        self.payload = payload


class _Sub:
    def __init__(self, subs: list, entry) -> None:
        self._subs = subs
        self._entry = entry

    async def unsubscribe(self) -> None:
        if self._entry in self._subs:
            self._subs.remove(self._entry)


class _FakeBus:
    """`request_or_error`/`subscribe`/`publish` are the only methods
    HttpApi calls. `respond_to_chat`, when set, turns a published
    `percept.text.received` into a `turn.completed` delivered back to
    every subscriber -- standing in for Orchestration answering a real
    chat turn, the same shape `simorgh.orchestration.worker.Worker.
    run_percept_chat` produces."""

    def __init__(self, payload: dict | None = None, *, raises: Exception | None = None) -> None:
        self._payload = payload or {}
        self._raises = raises
        self.calls: list = []
        self.published: list = []
        self._subs: list = []
        self.respond_to_chat: dict | None = None  # e.g. {"text": "hi", "floor": False}

    async def request_or_error(self, message, *, timeout=None):
        self.calls.append((message, timeout))
        if self._raises is not None:
            raise self._raises
        return _FakeReply(self._payload)

    async def subscribe(self, type_, handler, **kwargs):
        entry = (type_, handler)
        self._subs.append(entry)
        return _Sub(self._subs, entry)

    async def publish(self, message) -> None:
        self.published.append(message)
        if message.type == "percept.text.received" and self.respond_to_chat is not None:
            turn_payload = {"session_id": message.payload["session_id"], **self.respond_to_chat}
            turn = _FakeMessage("turn.completed", turn_payload)
            for type_, handler in list(self._subs):
                if type_ == "turn.completed":
                    await handler(turn)


class _FakeMessage:
    def __init__(self, type_: str, payload: dict) -> None:
        self.type = type_
        self.payload = payload


def _event(stream: str, seq: int, *, ts: float = 0.0, type_: str = "x.y", payload: dict | None = None) -> Event:
    return Event(stream=stream, type=type_, ts=ts, trace_id=f"t{seq}", causation_id=None,
                payload=payload or {}, seq=seq)


class _FakeLedger:
    """`head`/`read`/`streams` are the only methods `HttpApi` calls --
    matching the real `LedgerClient`'s duck-typed surface (`head` is
    outside the narrow `contracts.protocols.Ledger` protocol, same as
    `simorgh/kernel/scheduler.py`'s own `materialize()` reliance on it)."""

    def __init__(self, events: dict[str, list[Event]] | None = None, *, raises: Exception | None = None) -> None:
        self._events = events or {}
        self._raises = raises

    async def head(self, stream: str) -> int:
        if self._raises is not None:
            raise self._raises
        evs = self._events.get(stream, [])
        return evs[-1].seq if evs else 0

    async def read(self, stream: str, *, from_seq: int = 0, limit: int | None = None) -> list[Event]:
        if self._raises is not None:
            raise self._raises
        out = [e for e in self._events.get(stream, []) if e.seq >= from_seq]
        return out[:limit] if limit is not None else out

    async def streams(self, prefix: str = "") -> list[str]:
        if self._raises is not None:
            raise self._raises
        return sorted(s for s, evs in self._events.items() if evs and s.startswith(prefix))


class HttpApiTestCase(unittest.IsolatedAsyncioTestCase):
    async def _start(self, bus, *, ledger=None, **kwargs) -> HttpApi:
        api = HttpApi(bus, ledger=ledger, host="127.0.0.1", port=0, **kwargs)  # port 0 -> OS picks a free one
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def _get(self, api: HttpApi, path: str) -> http.client.HTTPResponse:
        import asyncio

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)

    async def test_root_serves_the_dashboard_html(self):
        api = await self._start(_FakeBus({}))
        resp = await self._get(api, "/")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.getheader("Content-Type"))
        self.assertIn(b"Simorgh", resp.body)
        self.assertIn(b"/api/status", resp.body)  # the page actually polls this route

    async def test_api_status_proxies_the_real_status_reply_as_json(self):
        payload = {"state": "running", "mode": "single", "run_id": "abc123",
                   "uptime_seconds": 12.5, "subsystems": [{"name": "bus", "status": "ok"}]}
        bus = _FakeBus(payload)
        api = await self._start(bus)
        resp = await self._get(api, "/api/status")
        self.assertEqual(resp.status, 200)
        self.assertIn("application/json", resp.getheader("Content-Type"))
        self.assertEqual(json.loads(resp.body), payload)
        self.assertEqual(len(bus.calls), 1)

    async def test_api_status_degrades_honestly_when_the_bus_request_fails(self):
        """An unreachable kernel is data for the page to render (the
        "lost contact" banner), never a crash -- graceful degradation
        applies to this dashboard's own backend call same as anywhere
        else in the system."""
        api = await self._start(_FakeBus(raises=TimeoutError("no reply")))
        resp = await self._get(api, "/api/status")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["state"], "unknown")
        self.assertIn("error", body)

    async def test_unknown_path_is_404(self):
        api = await self._start(_FakeBus({}))
        resp = await self._get(api, "/nope")
        self.assertEqual(resp.status, 404)

    async def test_post_to_a_get_only_path_is_404_not_405(self):
        # POST is a valid method in general now (/api/chat accepts it) --
        # a path that just doesn't route for this method is "not found"
        # for that combination, not a blanket "method not allowed".
        api = await self._start(_FakeBus({}))

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("POST", "/api/status", body=b"{}")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp

        resp = await asyncio.to_thread(_do)
        self.assertEqual(resp.status, 404)

    async def test_a_genuinely_unsupported_method_is_405(self):
        api = await self._start(_FakeBus({}))

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("DELETE", "/api/status")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp

        resp = await asyncio.to_thread(_do)
        self.assertEqual(resp.status, 405)

    async def test_a_bare_connection_with_no_bytes_does_not_crash_the_server(self):
        import asyncio

        api = await self._start(_FakeBus({}))
        reader, writer = await asyncio.open_connection("127.0.0.1", api.port)
        writer.close()
        await writer.wait_closed()
        # The server must still answer the next real request.
        resp = await self._get(api, "/")
        self.assertEqual(resp.status, 200)

    async def test_two_requests_in_a_row_both_get_full_responses(self):
        api = await self._start(_FakeBus({"state": "running"}))
        first = await self._get(api, "/api/status")
        second = await self._get(api, "/api/status")
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)

    async def _post(self, api: HttpApi, path: str, body: dict | bytes, *, headers: dict | None = None
                     ) -> tuple[int, bytes]:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        req_headers.update(headers or {})

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request("POST", path, body=payload, headers=req_headers)
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            return resp.status, data

        return await asyncio.to_thread(_do)

    async def test_chat_publishes_a_percept_and_returns_the_matching_turn(self):
        bus = _FakeBus({})
        bus.respond_to_chat = {"text": "hello back", "floor": False}
        api = await self._start(bus)

        status, data = await self._post(api, "/api/chat", {"text": "hi there"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"text": "hello back", "floor": False})

        self.assertEqual(len(bus.published), 1)
        percept = bus.published[0]
        self.assertEqual(percept.payload["text"], "hi there")
        self.assertEqual(percept.payload["channel"], "api")

    async def test_chat_rejects_a_cross_origin_request(self):
        """A malicious page open in another tab can fire a same-origin-
        free "simple request" (no CORS preflight) at this local,
        unauthenticated dashboard -- e.g. Content-Type: text/plain with
        a JSON body, which this server parses identically to a real
        dashboard click. Confirmed live against a real running server:
        such a request was accepted and produced a real chat turn before
        this guard existed. A present, mismatching `Origin` header is
        the CSRF tell -- browsers always attach it cross-site, including
        under `no-cors`."""
        bus = _FakeBus({})
        bus.respond_to_chat = {"text": "should never run", "floor": False}
        api = await self._start(bus)

        status, data = await self._post(api, "/api/chat", {"text": "attacker text"},
                                         headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(bus.published, [])

    async def test_chat_accepts_a_same_origin_request(self):
        bus = _FakeBus({})
        bus.respond_to_chat = {"text": "hello back", "floor": False}
        api = await self._start(bus)

        status, data = await self._post(api, "/api/chat", {"text": "hi there"},
                                         headers={"Origin": f"http://127.0.0.1:{api.port}"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"text": "hello back", "floor": False})

    async def test_chat_reports_a_floor_reply_honestly_not_as_a_success(self):
        bus = _FakeBus({})
        bus.respond_to_chat = {"text": "", "floor": True}
        api = await self._start(bus)
        status, data = await self._post(api, "/api/chat", {"text": "hi"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"text": "", "floor": True})

    async def test_chat_times_out_honestly_when_no_turn_completed_arrives(self):
        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0, chat_timeout_s=0.05)
        await api.start()
        self.addAsyncCleanup(api.stop)
        status, data = await self._post(api, "/api/chat", {"text": "hi"})
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertEqual(body["floor"], True)
        self.assertIn("error", body)

    async def test_empty_message_is_a_client_error_not_a_publish(self):
        bus = _FakeBus({})
        api = await self._start(bus)
        status, _data = await self._post(api, "/api/chat", {"text": "   "})
        self.assertEqual(status, 400)
        self.assertEqual(bus.published, [])

    async def test_invalid_json_body_is_a_client_error(self):
        api = await self._start(_FakeBus({}))
        status, _data = await self._post(api, "/api/chat", b"not json")
        self.assertEqual(status, 400)

    async def test_oversized_body_is_rejected(self):
        api = await self._start(_FakeBus({}))
        huge = json.dumps({"text": "x" * 20_000}).encode("utf-8")
        status, _data = await self._post(api, "/api/chat", huge)
        self.assertEqual(status, 413)

    async def test_two_concurrent_chats_never_cross_wire_their_replies(self):
        """Same class of bug as milestone 106's REPL fix, verified here
        too: a fresh session id per call, keyed correctly, so two
        dashboard tabs chatting at once each get their own answer."""
        bus = _FakeBus({})
        api = await self._start(bus)

        async def _respond_once(text: str, reply: str) -> None:
            # Wait for this call's own percept to land, then answer it
            # specifically -- proves routing is by session_id, not by
            # publish order.
            while not any(p.payload["text"] == text for p in bus.published):
                await asyncio.sleep(0)
            percept = next(p for p in bus.published if p.payload["text"] == text)
            turn = _FakeMessage("turn.completed", {"session_id": percept.payload["session_id"], "text": reply, "floor": False})
            for type_, handler in list(bus._subs):  # noqa: SLF001
                if type_ == "turn.completed":
                    await handler(turn)

        async def _run(text: str, reply: str):
            responder = asyncio.ensure_future(_respond_once(text, reply))
            status, data = await self._post(api, "/api/chat", {"text": text})
            await responder
            return status, json.loads(data)

        (status1, body1), (status2, body2) = await asyncio.gather(
            _run("first message", "reply to first"),
            _run("second message", "reply to second"),
        )
        self.assertEqual(status1, 200)
        self.assertEqual(status2, 200)
        self.assertEqual(body1["text"], "reply to first")
        self.assertEqual(body2["text"], "reply to second")

    async def test_a_client_supplied_session_id_is_reused_not_replaced(self):
        """02-system-architecture.md section 6.1: a client that wants a
        real conversation (not a fresh stranger every message) sends
        the same session_id every time -- it must reach Memory's own
        episodic-grouping field unchanged, the exact thing the dashboard
        page itself now does (one id per tab, generated client-side)."""
        bus = _FakeBus({})
        bus.respond_to_chat = {"text": "ok", "floor": False}
        api = await self._start(bus)
        status, _data = await self._post(api, "/api/chat", {"text": "hi", "session_id": "conv-42"})
        self.assertEqual(status, 200)
        self.assertEqual(bus.published[0].payload["session_id"], "conv-42")

    async def test_two_sequential_messages_with_the_same_session_id_both_succeed(self):
        bus = _FakeBus({})
        bus.respond_to_chat = {"text": "ok", "floor": False}
        api = await self._start(bus)
        first = await self._post(api, "/api/chat", {"text": "hi", "session_id": "conv-1"})
        second = await self._post(api, "/api/chat", {"text": "again", "session_id": "conv-1"})
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertEqual([p.payload["session_id"] for p in bus.published], ["conv-1", "conv-1"])

    async def test_a_second_request_for_a_session_id_already_in_flight_is_refused_not_cross_wired(self):
        """The real risk milestone 106's fix didn't have to consider: an
        externally-supplied session_id can legitimately collide if a
        caller fires two requests before the first resolves. Silently
        overwriting the pending future (106's original bug) would be
        exactly as wrong now as it was then -- this must refuse the
        second one outright instead."""
        bus = _FakeBus({})  # no respond_to_chat -- the first call is left in-flight, on purpose
        api = HttpApi(bus, host="127.0.0.1", port=0, chat_timeout_s=5.0)
        await api.start()
        self.addAsyncCleanup(api.stop)

        first = asyncio.ensure_future(self._post(api, "/api/chat", {"text": "hi", "session_id": "conv-x"}))
        while not bus.published:
            await asyncio.sleep(0)  # let the first request actually register as pending

        status2, raw2 = await self._post(api, "/api/chat", {"text": "again", "session_id": "conv-x"})
        self.assertEqual(status2, 409)
        self.assertEqual(json.loads(raw2)["error"], "turn already in flight")

        # Resolve the first so it doesn't dangle into the timeout.
        turn = _FakeMessage("turn.completed", {"session_id": "conv-x", "text": "ok", "floor": False})
        for type_, handler in list(bus._subs):  # noqa: SLF001
            if type_ == "turn.completed":
                await handler(turn)
        status1, raw1 = await first
        self.assertEqual(status1, 200)
        self.assertEqual(json.loads(raw1)["text"], "ok")


class HistoryEndpointTestCase(unittest.IsolatedAsyncioTestCase):
    """`GET /api/history?subsystem=<name>&minutes=<n>` -- metrics over
    time (02-system-architecture.md section 6.2), read from the Kernel's
    own `metrics:history` stream, not mined from `trace:<trace_id>`
    (`system.metrics` is sampled to 0.0 there by default)."""

    async def _start(self, *, ledger=None, **kwargs) -> HttpApi:
        api = HttpApi(_FakeBus({}), ledger=ledger, host="127.0.0.1", port=0, **kwargs)
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def _get(self, api: HttpApi, path: str):
        import asyncio

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)

    async def test_missing_subsystem_is_a_friendly_error_not_a_crash(self):
        api = await self._start(ledger=_FakeLedger())
        resp = await self._get(api, "/api/history?minutes=5")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["error"]["code"], "missing_subsystem")

    async def test_no_ledger_wired_degrades_honestly(self):
        api = await self._start(ledger=None)
        resp = await self._get(api, "/api/history?subsystem=bus")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["subsystem"], "bus")
        self.assertEqual(body["points"], [])
        self.assertEqual(body["error"]["code"], "ledger_unavailable")

    async def test_returns_only_the_requested_subsystems_series_within_the_window(self):
        stream = "metrics:history"
        events = [
            # Older than the 5-minute (300s) window measured from "now" (1000.0) below -- must be excluded.
            _event(stream, 1, ts=100.0, type_="system.metrics_history",
                  payload={"metrics": {"bus": {"counters": {"published": 1}, "gauges": {"queue_depth.x": 0}},
                                       "memory": {"counters": {}, "gauges": {"records": {"episodic": 1}}}}}),
            _event(stream, 2, ts=850.0, type_="system.metrics_history",
                  payload={"metrics": {"bus": {"counters": {"published": 2}, "gauges": {"queue_depth.x": 1}}}}),
            _event(stream, 3, ts=950.0, type_="system.metrics_history",
                  payload={"metrics": {"bus": {"counters": {"published": 3}, "gauges": {"queue_depth.x": 2}}}}),
        ]
        api = await self._start(ledger=_FakeLedger({stream: events}))
        api._clock = lambda: 1000.0  # noqa: SLF001 -- cutoff = 1000 - 300 = 700, so event 1 (ts=100) falls out
        resp = await self._get(api, "/api/history?subsystem=bus&minutes=5")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["subsystem"], "bus")
        self.assertEqual([p["ts"] for p in body["points"]], [850.0, 950.0])
        self.assertEqual(body["points"][0]["gauges"], {"queue_depth.x": 1})
        # `memory`'s series must never leak into a `bus` request.
        self.assertTrue(all("gauges" in p and "records" not in p["gauges"] for p in body["points"]))

    async def test_ledger_read_failure_degrades_honestly(self):
        api = await self._start(ledger=_FakeLedger(raises=TimeoutError("no ledger")))
        resp = await self._get(api, "/api/history?subsystem=bus")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["error"]["code"], "history_unavailable")


class LogsEndpointTestCase(unittest.IsolatedAsyncioTestCase):
    """`GET /api/logs?stream=<name>&limit=<n>` -- structured logs are
    already Ledger events (02-system-architecture.md section 7); this is
    a read-only tail over any stream, not new capture."""

    async def _start(self, *, ledger=None, **kwargs) -> HttpApi:
        api = HttpApi(_FakeBus({}), ledger=ledger, host="127.0.0.1", port=0, **kwargs)
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def _get(self, api: HttpApi, path: str):
        import asyncio

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)

    async def test_defaults_to_the_system_stream(self):
        events = [_event("system", i, ts=float(i), type_="system.state", payload={"state": "running"})
                 for i in range(1, 4)]
        api = await self._start(ledger=_FakeLedger({"system": events}))
        resp = await self._get(api, "/api/logs")
        body = json.loads(resp.body)
        self.assertEqual(body["stream"], "system")
        self.assertEqual(len(body["events"]), 3)

    async def test_limit_returns_only_the_most_recent_events(self):
        events = [_event("system", i, ts=float(i), type_="system.state") for i in range(1, 11)]
        api = await self._start(ledger=_FakeLedger({"system": events}))
        resp = await self._get(api, "/api/logs?stream=system&limit=3")
        body = json.loads(resp.body)
        self.assertEqual([e["seq"] for e in body["events"]], [8, 9, 10])

    async def test_event_shape_carries_seq_ts_type_trace_and_payload(self):
        events = [_event("system", 1, ts=42.0, type_="system.state", payload={"state": "running"})]
        api = await self._start(ledger=_FakeLedger({"system": events}))
        resp = await self._get(api, "/api/logs?stream=system")
        row = json.loads(resp.body)["events"][0]
        self.assertEqual(row["seq"], 1)
        self.assertEqual(row["ts"], 42.0)
        self.assertEqual(row["type"], "system.state")
        self.assertEqual(row["trace_id"], "t1")
        self.assertEqual(row["payload"], {"state": "running"})

    async def test_no_ledger_wired_degrades_honestly(self):
        api = await self._start(ledger=None)
        resp = await self._get(api, "/api/logs")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["events"], [])
        self.assertEqual(body["error"]["code"], "ledger_unavailable")

    async def test_ledger_read_failure_degrades_honestly(self):
        api = await self._start(ledger=_FakeLedger(raises=RuntimeError("boom")))
        resp = await self._get(api, "/api/logs")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["error"]["code"], "logs_unavailable")

    async def test_an_unknown_stream_is_an_empty_list_not_an_error(self):
        api = await self._start(ledger=_FakeLedger({}))
        resp = await self._get(api, "/api/logs?stream=nope")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["events"], [])
        self.assertNotIn("error", body)


class StreamsEndpointTestCase(unittest.IsolatedAsyncioTestCase):
    """`GET /api/streams` -- lists live Ledger streams, e.g. for a stream
    picker in the log viewer."""

    async def _start(self, *, ledger=None) -> HttpApi:
        api = HttpApi(_FakeBus({}), ledger=ledger, host="127.0.0.1", port=0)
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def _get(self, api: HttpApi, path: str):
        import asyncio

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)

    async def test_lists_streams_that_have_events(self):
        ledger = _FakeLedger({
            "system": [_event("system", 1)],
            "metrics:history": [_event("metrics:history", 1)],
        })
        api = await self._start(ledger=ledger)
        resp = await self._get(api, "/api/streams")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(sorted(body["streams"]), ["metrics:history", "system"])

    async def test_no_ledger_wired_degrades_honestly(self):
        api = await self._start(ledger=None)
        resp = await self._get(api, "/api/streams")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["streams"], [])
        self.assertEqual(body["error"]["code"], "ledger_unavailable")


if __name__ == "__main__":
    unittest.main()


class AuthTestCase(unittest.IsolatedAsyncioTestCase):
    """`SIM_API_TOKEN` gating (platform-connectors-design.md section 4).

    The dashboard shipped local and unauthenticated, which is the right
    posture on 127.0.0.1 and the wrong one the moment the bind moves or
    a tunnel is put in front of it -- `/api/chat` starts a real,
    tool-using turn. With a token set, every route but the page itself
    and the liveness check requires `Authorization: Bearer`."""

    TOKEN = "s3cret-token-value"

    async def _start(self, **kwargs) -> HttpApi:
        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0, **kwargs)
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def _request(self, api: HttpApi, method: str, path: str, *, token: str | None = None,
                       raw_auth: str | None = None, body: bytes | None = None) -> tuple[int, bytes]:
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if raw_auth is not None:
            headers["Authorization"] = raw_auth
        if body is not None:
            headers["Content-Type"] = "application/json"

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            return resp.status, data

        return await asyncio.to_thread(_do)

    async def test_with_no_token_configured_nothing_changes(self):
        api = await self._start()
        self.assertFalse(api.requires_token)
        for path in ("/", "/api/status", "/api/streams"):
            status, _ = await self._request(api, "GET", path)
            self.assertEqual(status, 200, path)

    async def test_a_gated_route_refuses_without_a_token(self):
        api = await self._start(token=self.TOKEN)
        self.assertTrue(api.requires_token)
        status, body = await self._request(api, "GET", "/api/streams")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")

    async def test_the_refusal_names_the_secret_to_set(self):
        api = await self._start(token=self.TOKEN)
        _, body = await self._request(api, "GET", "/api/activity")
        self.assertIn("SIM_API_TOKEN", json.loads(body)["error"]["detail"])

    async def test_the_right_token_passes(self):
        api = await self._start(token=self.TOKEN)
        status, _ = await self._request(api, "GET", "/api/streams", token=self.TOKEN)
        self.assertEqual(status, 200)

    async def test_a_wrong_token_is_refused(self):
        api = await self._start(token=self.TOKEN)
        status, _ = await self._request(api, "GET", "/api/streams", token="not-the-token")
        self.assertEqual(status, 401)

    async def test_a_prefix_of_the_token_is_refused(self):
        """A `startswith` comparison would let this through, and would
        also leak the token one character at a time."""
        api = await self._start(token=self.TOKEN)
        status, _ = await self._request(api, "GET", "/api/streams", token=self.TOKEN[:-1])
        self.assertEqual(status, 401)

    async def test_a_non_bearer_scheme_is_refused(self):
        api = await self._start(token=self.TOKEN)
        status, _ = await self._request(api, "GET", "/api/streams", raw_auth="Basic " + self.TOKEN)
        self.assertEqual(status, 401)

    async def test_the_page_and_the_status_route_stay_open(self):
        """The page is what carries the token to the browser; gating it
        would leave the dashboard unreachable. `/api/status` is the
        liveness check, and shows only what the boot banner prints."""
        api = await self._start(token=self.TOKEN)
        for path in ("/", "/api/status"):
            status, _ = await self._request(api, "GET", path)
            self.assertEqual(status, 200, path)

    async def test_chat_is_gated(self):
        api = await self._start(token=self.TOKEN)
        status, _ = await self._request(api, "POST", "/api/chat", body=b'{"text":"hi"}')
        self.assertEqual(status, 401)

    async def test_the_401_carries_a_www_authenticate_header(self):
        api = await self._start(token=self.TOKEN)

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request("GET", "/api/streams")
            resp = conn.getresponse()
            resp.read()
            header = resp.getheader("WWW-Authenticate")
            conn.close()
            return header

        self.assertIn("Bearer", await asyncio.to_thread(_do))


class RouteTableTestCase(unittest.IsolatedAsyncioTestCase):
    """`register_route` (platform section 4): `home`, `voice` and the
    domain subsystems add inbound routes without editing httpapi.py."""

    async def _start(self, **kwargs) -> HttpApi:
        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0, **kwargs)
        return api

    async def _get(self, api: HttpApi, path: str, *, token: str | None = None) -> tuple[int, bytes]:
        headers = {"Authorization": "Bearer " + token} if token else {}

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            return resp.status, data

        return await asyncio.to_thread(_do)

    async def test_a_registered_route_answers(self):
        api = await self._start()
        seen = []

        async def _handler(query, body, headers):
            seen.append((query, body))
            return 200, b'{"ok":true}', "application/json"

        api.register_route("GET", "/api/home/state", _handler)
        await api.start()
        self.addAsyncCleanup(api.stop)
        status, body = await self._get(api, "/api/home/state?room=kitchen")
        self.assertEqual((status, json.loads(body)), (200, {"ok": True}))
        self.assertEqual(seen[0][0], {"room": ["kitchen"]})

    async def test_a_registered_route_is_gated_by_default(self):
        api = await self._start(token="tok")

        async def _handler(query, body, headers):
            return 200, b"{}", "application/json"

        api.register_route("GET", "/api/home/state", _handler)
        await api.start()
        self.addAsyncCleanup(api.stop)
        self.assertEqual((await self._get(api, "/api/home/state"))[0], 401)
        self.assertEqual((await self._get(api, "/api/home/state", token="tok"))[0], 200)

    async def test_a_duplicate_route_is_refused_rather_than_silently_shadowing(self):
        api = await self._start()

        async def _handler(query, body, headers):
            return 200, b"{}", "application/json"

        with self.assertRaises(ValueError):
            api.register_route("GET", "/api/status", _handler)

    async def test_a_handler_that_raises_does_not_take_the_server_down(self):
        api = await self._start()

        async def _boom(query, body, headers):
            raise RuntimeError("handler exploded")

        api.register_route("GET", "/api/boom", _boom)
        await api.start()
        self.addAsyncCleanup(api.stop)
        status, _ = await self._get(api, "/api/boom")
        self.assertEqual(status, 500)
        # still serving
        self.assertEqual((await self._get(api, "/api/status"))[0], 200)


class BodyLimitTestCase(unittest.IsolatedAsyncioTestCase):
    """The server-wide POST body cap (`api_max_body_bytes`) and the much
    smaller one `/api/chat` keeps for itself."""

    async def _post(self, api: HttpApi, path: str, payload: bytes) -> int:
        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status

        return await asyncio.to_thread(_do)

    async def test_chat_keeps_its_own_small_cap_even_when_the_server_cap_is_wide(self):
        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0, max_body_bytes=1_000_000)
        await api.start()
        self.addAsyncCleanup(api.stop)
        big = json.dumps({"text": "x" * 32_000}).encode()
        self.assertEqual(await self._post(api, "/api/chat", big), 413)

    async def test_a_registered_route_gets_the_server_wide_cap(self):
        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0, max_body_bytes=2048)
        received = []

        async def _handler(query, body, headers):
            received.append(body)
            return 200, b"{}", "application/json"

        api.register_route("POST", "/api/hook", _handler)
        await api.start()
        self.addAsyncCleanup(api.stop)
        self.assertEqual(await self._post(api, "/api/hook", b"x" * 1000), 200)
        self.assertEqual(received[0], b"x" * 1000)
        self.assertEqual(await self._post(api, "/api/hook", b"x" * 4000), 413)


class RateLimitTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_route_over_its_rate_gets_429(self):
        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0)

        async def _handler(query, body, headers):
            return 200, b"{}", "application/json"

        api.register_route("GET", "/api/cheap", _handler, rate=(3, 60.0))
        await api.start()
        self.addAsyncCleanup(api.stop)

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request("GET", "/api/cheap")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status

        statuses = [await asyncio.to_thread(_do) for _ in range(5)]
        self.assertEqual(statuses, [200, 200, 200, 429, 429])

    async def test_an_unlimited_route_is_never_throttled(self):
        api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0)
        await api.start()
        self.addAsyncCleanup(api.stop)

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request("GET", "/api/status")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status

        self.assertEqual([await asyncio.to_thread(_do) for _ in range(6)], [200] * 6)


class TheOpenRouteDoesNotBypassTheTokenTestCase(AuthTestCase):
    """`/api/status` stays unauthenticated so a viewer can see the
    system is alive. Its comment claimed it revealed "only what the boot
    banner already prints"; on a token-gated server it returned process
    memory, the host's load averages, every bus counter and queue depth,
    and the worker table including the running task's id -- the same
    observe-tier numbers `/api/history` answers with a 401 (observer,
    2026-09-10).
    """

    FULL = {"state": "running", "version": "1", "uptime_s": 12.0,
            "metrics": {"rss_mb": 210, "load": [4.1, 3.0, 2.2]},
            "workers": [{"worker_id": "w1", "task_id": "t-secret"}]}

    async def _api(self, token: str) -> HttpApi:
        api = HttpApi(_FakeBus(dict(self.FULL)),
                      host="127.0.0.1", port=0, token=token)
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def test_without_the_token_the_metrics_are_withheld(self):
        api = await self._api(self.TOKEN)
        status, body = await self._request(api, "GET", "/api/status")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload.get("state"), "running")
        self.assertNotIn("metrics", payload)
        self.assertNotIn("workers", payload)
        self.assertNotIn("t-secret", body.decode())

    async def test_with_the_token_nothing_is_withheld(self):
        api = await self._api(self.TOKEN)
        _status, body = await self._request(api, "GET", "/api/status", token=self.TOKEN)
        self.assertIn("metrics", json.loads(body))

    async def test_liveness_is_still_open(self):
        """The point of the route survives: a viewer with no token can
        still see that the system is up."""
        api = await self._api(self.TOKEN)
        _status, body = await self._request(api, "GET", "/api/status")
        payload = json.loads(body)
        self.assertEqual(payload["state"], "running")
        self.assertIn("uptime_s", payload)

    async def test_with_no_token_configured_nothing_changes(self):
        """There is no gate to get around on a local dashboard."""
        api = HttpApi(_FakeBus(dict(self.FULL)),
                      host="127.0.0.1", port=0)
        await api.start()
        self.addAsyncCleanup(api.stop)
        _status, body = await self._request(api, "GET", "/api/status")
        self.assertIn("metrics", json.loads(body))


class TvPageTestCase(unittest.IsolatedAsyncioTestCase):
    """Sim on the TV: the page is open (a shell), the state behind the
    token -- which the TV passes in the URL, since a cast URL cannot
    carry a header -- and `tv.state` on the bus is what the page frames."""

    async def _api(self, token=""):
        bus = _FakeBus()
        api = HttpApi(bus, ledger=None, host="127.0.0.1", port=0, token=token)
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api, bus

    def _get(self, api, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    async def test_the_page_is_open_and_the_state_needs_the_token_in_header_or_url(self):
        api, bus = await self._api(token="tv-secret")
        status, body = await asyncio.to_thread(self._get, api, "/tv")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Sim</title>", body)
        status, _ = await asyncio.to_thread(self._get, api, "/api/tv/state")
        self.assertEqual(status, 401)
        status, body = await asyncio.to_thread(self._get, api, "/api/tv/state?token=tv-secret")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "none")
        status, _ = await asyncio.to_thread(self._get, api, "/api/tv/state?token=wrong")
        self.assertEqual(status, 401)
        status, _ = await asyncio.to_thread(self._get, api, "/api/tv/state", {"Authorization": "Bearer tv-secret"})
        self.assertEqual(status, 200)

    async def test_the_state_follows_tv_state_on_the_bus(self):
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message
        api, bus = await self._api()
        handler = next(entry[1] for entry in bus._subs if entry[0] == topics.TV_STATE)  # noqa: SLF001
        await handler(Message.new(topics.TV_STATE, source="execution",
                                  payload={"mode": "frame", "url": "https://x/clip.mp4", "title": "Clip"}))
        status, body = await asyncio.to_thread(self._get, api, "/api/tv/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual((state["mode"], state["url"], state["title"]), ("frame", "https://x/clip.mp4", "Clip"))


class TvSpeechTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_piece_of_speech_is_listed_in_the_state_and_served_from_the_ledger(self):
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message

        class _Ledger:
            async def get_blob(self, ref):
                if ref != "blob:7":
                    raise KeyError(ref)
                return b"RIFF....WAVEfake"
        bus = _FakeBus()
        api = HttpApi(bus, ledger=_Ledger(), host="127.0.0.1", port=0)
        await api.start()
        self.addAsyncCleanup(api.stop)
        handler = next(entry[1] for entry in bus._subs if entry[0] == topics.TV_SPEECH)  # noqa: SLF001
        await handler(Message.new(topics.TV_SPEECH, source="voice",
                                  payload={"ref": "blob:7", "seconds": 1.5, "seq": 1, "request_id": "r1"}))

        def _get(path):
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            ctype = resp.getheader("Content-Type")
            conn.close()
            return resp.status, body, ctype
        status, body, _ = await asyncio.to_thread(_get, "/api/tv/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual(state["speech"][0]["seq"], 1)
        self.assertEqual(state["speech"][0]["url"], "/api/tv/speech?ref=blob:7")
        status, body, ctype = await asyncio.to_thread(_get, "/api/tv/speech?ref=blob:7")
        self.assertEqual((status, body, ctype), (200, b"RIFF....WAVEfake", "audio/wav"))
        status, _b, _c = await asyncio.to_thread(_get, "/api/tv/speech?ref=blob:999")
        self.assertEqual(status, 404, "only refs the page was told about are served")


class HooksAndHlsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_webhook_lands_on_the_bus_and_hls_is_served_from_the_workspace(self):
        import os
        import tempfile
        from simorgh.contracts import topics
        bus = _FakeBus()
        api = HttpApi(bus, ledger=None, host="127.0.0.1", port=0, token="tv-secret")
        with tempfile.TemporaryDirectory() as tmp:
            api._hls_root = Path(tmp).resolve()  # noqa: SLF001
            (Path(tmp) / "7").mkdir()
            (Path(tmp) / "7" / "index.m3u8").write_text("#EXTM3U\n")
            await api.start()
            self.addAsyncCleanup(api.stop)

            def _req(method, path, body=None):
                conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
                conn.request(method, path, body=body, headers={"Content-Type": "application/xml"} if body else {})
                resp = conn.getresponse()
                data = resp.read()
                conn.close()
                return resp.status, data
            status, _ = await asyncio.to_thread(_req, "POST", "/api/hooks/reolink", b"<xml>channel1</xml>")
            self.assertEqual(status, 401, "a hook needs the token too")
            status, body = await asyncio.to_thread(_req, "POST", "/api/hooks/reolink?token=tv-secret", b"<xml>channel1</xml>")
            self.assertEqual((status, body), (200, b"ok"))
            hooks = [m for m in bus.published if m.type == topics.UI_HOOK_RECEIVED]
            self.assertEqual(hooks[-1].payload["name"], "reolink")
            self.assertIn("channel1", hooks[-1].payload["body"])
            status, body = await asyncio.to_thread(_req, "GET", "/tv/hls/7/index.m3u8")
            self.assertEqual((status, body), (200, b"#EXTM3U\n"), "a live stream is open on the LAN")
            status, _ = await asyncio.to_thread(_req, "GET", "/tv/hls/../secrets.toml")
            self.assertEqual(status, 404)


class DashAndWallpapersTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_dash_is_open_wallpapers_list_and_serve_and_no_traversal(self):
        import tempfile
        bus=_FakeBus()
        api=HttpApi(bus,ledger=None,host="127.0.0.1",port=0,token="secret")
        with tempfile.TemporaryDirectory() as tmp:
            api._wallpaper_root=Path(tmp).resolve()  # noqa: SLF001
            (Path(tmp)/"beach.jpg").write_bytes(b"\xff\xd8jpeg")
            (Path(tmp)/".DS_Store").write_bytes(b"x")
            await api.start(); self.addAsyncCleanup(api.stop)
            def g(path,hdr=None):
                c=http.client.HTTPConnection("127.0.0.1",api.port,timeout=5)
                c.request("GET",path,headers=hdr or {}); r=c.getresponse(); b=r.read(); ct=r.getheader("Content-Type"); c.close()
                return r.status,b,ct
            st,b,_=await asyncio.to_thread(g,"/dash")
            self.assertEqual(st,200); self.assertIn(b"Simorgh",b)  # open, no token
            st,b,_=await asyncio.to_thread(g,"/api/wallpapers")
            self.assertEqual(st,200); self.assertEqual(json.loads(b)["wallpapers"],["beach.jpg"])  # dotfile skipped
            st,b,ct=await asyncio.to_thread(g,"/wallpapers/beach.jpg")
            self.assertEqual((st,b),(200,b"\xff\xd8jpeg")); self.assertEqual(ct,"image/jpeg")
            st,_,_=await asyncio.to_thread(g,"/wallpapers/../secrets.toml")
            self.assertEqual(st,404)
            st,_,_=await asyncio.to_thread(g,"/wallpapers/missing.jpg")
            self.assertEqual(st,404)


class DashDataStateAndRemoteTestCase(unittest.IsolatedAsyncioTestCase):
    """The collector's snapshot, the steering state, the phone remote and
    the camera stills (2026-09-12): the page and the TV's Cast receiver
    fetch these with no header, so the reads are open; the one write is
    behind the token like every other side effect."""

    class _Feeds:
        def __init__(self) -> None:
            self.started = self.stopped = False

        async def start(self):
            self.started = True

        async def stop(self):
            self.stopped = True

        def snapshot(self):
            return {"now": 1.0, "feeds": {"quotes": {"error": ""}}, "markets": {"stocks": [{"symbol": "NVDA", "last": 218.29}]},
                    "news": {}, "cameras": []}

    def _g(self, api, path, hdr=None):
        c = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
        c.request("GET", path, headers=hdr or {}); r = c.getresponse(); b = r.read(); ct = r.getheader("Content-Type"); c.close()
        return r.status, b, ct

    def _p(self, api, path, body, hdr=None):
        c = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        headers.update(hdr or {})
        c.request("POST", path, body=json.dumps(body).encode(), headers=headers); r = c.getresponse(); b = r.read(); c.close()
        return r.status, b

    async def test_the_snapshot_is_served_open_and_the_collector_is_started_and_stopped_with_the_api(self):
        feeds = self._Feeds()
        api = HttpApi(_FakeBus(), host="127.0.0.1", port=0, token="secret", feeds=feeds)
        await api.start()
        self.assertTrue(feeds.started)
        st, b, _ = await asyncio.to_thread(self._g, api, "/api/dash/data")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(b)["markets"]["stocks"][0]["symbol"], "NVDA")
        await api.stop()
        self.assertTrue(feeds.stopped)

    async def test_without_a_collector_the_snapshot_says_so_instead_of_inventing(self):
        api = HttpApi(_FakeBus(), host="127.0.0.1", port=0)
        await api.start(); self.addAsyncCleanup(api.stop)
        st, b, _ = await asyncio.to_thread(self._g, api, "/api/dash/data")
        self.assertEqual(st, 200)
        body = json.loads(b)
        self.assertTrue(body["off"]); self.assertIsNone(body["markets"])

    async def test_the_state_is_read_open_written_with_the_token_and_follows_the_bus(self):
        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message
        bus = _FakeBus()
        api = HttpApi(bus, host="127.0.0.1", port=0, token="secret")
        await api.start(); self.addAsyncCleanup(api.stop)
        st, b, _ = await asyncio.to_thread(self._g, api, "/api/dash/state")
        self.assertEqual(st, 200); self.assertEqual(json.loads(b)["view"], "")
        # the write needs the token -- header or query (the phone page carries it in its URL)
        st, _ = await asyncio.to_thread(self._p, api, "/api/dash/state", {"view": "markets"})
        self.assertEqual(st, 401)
        st, b = await asyncio.to_thread(self._p, api, "/api/dash/state?token=secret", {"view": "stocks", "timeframe": "1w", "rotate_s": 30})
        self.assertEqual(st, 200)
        state = json.loads(b)
        self.assertEqual((state["view"], state["timeframe"], state["rotate_s"]), ("markets", "1W", 30), "aliases and case are normalised")
        self.assertGreater(state["since"], 0)
        self.assertEqual(bus.published[-1].type, topics.DASH_STATE, "the remote's change is announced like the tool's")
        # a nonsense view or timeframe changes nothing
        st, b = await asyncio.to_thread(self._p, api, "/api/dash/state", {"view": "nope", "timeframe": "5Y"}, {"Authorization": "Bearer secret"})
        self.assertEqual(json.loads(b)["view"], "markets"); self.assertEqual(json.loads(b)["timeframe"], "1W")
        # and the dash_view tool's message on the bus lands in the same state
        handler = next(entry[1] for entry in bus._subs if entry[0] == topics.DASH_STATE)  # noqa: SLF001
        await handler(Message.new(topics.DASH_STATE, source="execution", payload={"view": "cameras", "symbol": "amd"}))
        st, b, _ = await asyncio.to_thread(self._g, api, "/api/dash/state")
        self.assertEqual((json.loads(b)["view"], json.loads(b)["symbol"]), ("cameras", "AMD"))

    async def test_a_same_origin_post_from_the_lan_address_is_not_mistaken_for_csrf(self):
        api = HttpApi(_FakeBus(), host="0.0.0.0", port=0)
        await api.start(); self.addAsyncCleanup(api.stop)
        host = f"192.168.50.7:{api.port}"
        st, _ = await asyncio.to_thread(self._p, api, "/api/dash/state", {"view": "news"},
                                        {"Origin": f"http://{host}", "Host": host})
        self.assertEqual(st, 200)
        st, _ = await asyncio.to_thread(self._p, api, "/api/dash/state", {"view": "news"},
                                        {"Origin": "http://evil.example", "Host": host})
        self.assertEqual(st, 403)

    async def test_the_logo_is_served_open_for_the_pages_and_the_tab_icon(self):
        api = HttpApi(_FakeBus(), host="127.0.0.1", port=0, token="secret")
        await api.start(); self.addAsyncCleanup(api.stop)
        for path in ("/logo.png", "/favicon.ico"):
            st, b, ct = await asyncio.to_thread(self._g, api, path)
            self.assertEqual((st, ct), (200, "image/png"), path)
            self.assertTrue(b.startswith(b"\x89PNG"), path)
        st, b, _ = await asyncio.to_thread(self._g, api, "/dash")
        self.assertIn(b'src="/logo.png"', b)

    async def test_the_startup_banner_is_served_for_the_terminal_box(self):
        api = HttpApi(_FakeBus(), host="127.0.0.1", port=0, token="secret")
        await api.start(); self.addAsyncCleanup(api.stop)
        st, b, _ = await asyncio.to_thread(self._g, api, "/api/dash/banner")
        self.assertEqual(st, 200)
        text = json.loads(b)["text"]
        self.assertIn("SIMORGH", text); self.assertIn("help", text); self.assertIn("\x1b[38;2;", text, "the splash's colours")
        st, b, _ = await asyncio.to_thread(self._g, api, "/api/dash/banner?unicode=off")
        self.assertNotIn("▀", json.loads(b)["text"])

    async def test_the_page_can_ask_for_live_cameras_and_ring_signalling_through_the_tool_path(self):
        from simorgh.interface import dispatch as dispatch_mod
        calls = []

        async def _fake_run_tool(*, bus, ledger, tool, raw, session_id, timeout):
            calls.append((tool, json.loads(raw), session_id))
            if tool == "ring_live":
                return dispatch_mod.Outcome(json.dumps({"sdp": "v=0 answer", "session": "4242", "camera": "Front Door"}))
            return dispatch_mod.Outcome("live in the dashboard's camera strip: Office, Pool")
        original = dispatch_mod._run_tool
        dispatch_mod._run_tool = _fake_run_tool
        try:
            api = HttpApi(_FakeBus(), host="127.0.0.1", port=0, token="secret")
            await api.start(); self.addAsyncCleanup(api.stop)
            st, b = await asyncio.to_thread(self._p, api, "/api/dash/cameras/live", {})
            self.assertEqual(st, 401, "a side effect: the token is needed")
            st, b = await asyncio.to_thread(self._p, api, "/api/dash/cameras/live?token=secret", {})
            self.assertEqual(st, 200); self.assertIn("Office", json.loads(b)["text"]); self.assertTrue(json.loads(b)["ok"])
            st, b = await asyncio.to_thread(self._p, api, "/api/dash/ring/live?token=secret", {"camera": "Front Door", "sdp": "v=0..."})
            self.assertEqual(st, 200); self.assertEqual(json.loads(b)["session"], "4242")
            st, b = await asyncio.to_thread(self._p, api, "/api/dash/ring/live?token=secret", {"sdp": "v=0"})
            self.assertEqual(st, 400)
        finally:
            dispatch_mod._run_tool = original
        self.assertEqual(calls[0], ("cam_stream", {"camera": "all", "mode": "dash"}, "dash"))
        self.assertEqual(calls[1][0], "ring_live"); self.assertEqual(calls[1][1]["camera"], "Front Door")

    async def test_the_remote_page_is_open_and_posts_to_the_state_route(self):
        api = HttpApi(_FakeBus(), host="127.0.0.1", port=0, token="secret")
        await api.start(); self.addAsyncCleanup(api.stop)
        st, b, ct = await asyncio.to_thread(self._g, api, "/remote")
        self.assertEqual(st, 200); self.assertIn("text/html", ct); self.assertIn(b"/api/dash/state", b)

    async def test_the_newest_camera_still_is_served_by_camera_name(self):
        import tempfile
        api = HttpApi(_FakeBus(), host="127.0.0.1", port=0, token="secret")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            api._snapshot_root = root  # noqa: SLF001
            (root / "Front_Door-20260912-090000.jpg").write_bytes(b"old")
            (root / "Front_Door-20260912-100000.jpg").write_bytes(b"new")
            import os
            os.utime(root / "Front_Door-20260912-100000.jpg", (2_000_000_000, 2_000_000_000))
            (root / "ring").mkdir(); (root / "ring" / "Porch-20260912-110000.jpg").write_bytes(b"ring")
            await api.start(); self.addAsyncCleanup(api.stop)
            st, b, ct = await asyncio.to_thread(self._g, api, "/cameras/snap/Front_Door")
            self.assertEqual((st, b, ct), (200, b"new", "image/jpeg"))
            st, b, _ = await asyncio.to_thread(self._g, api, "/cameras/snap/ring/Porch")
            self.assertEqual((st, b), (200, b"ring"))
            st, _, _ = await asyncio.to_thread(self._g, api, "/cameras/snap/Garage")
            self.assertEqual(st, 404)
            st, _, _ = await asyncio.to_thread(self._g, api, "/cameras/snap/../secrets")
            self.assertEqual(st, 404)
