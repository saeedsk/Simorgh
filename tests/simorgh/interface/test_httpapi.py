"""HttpApi: the live-status dashboard's server (simorgh/interface/httpapi.py).
Real sockets, real HTTP/1.1 requests via `http.client` -- this module
hand-rolls request parsing, so the thing actually worth testing is what
a real client sees on the wire, not a mocked reader/writer."""

from __future__ import annotations

import asyncio
import http.client
import json
import unittest

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

    async def _post(self, api: HttpApi, path: str, body: dict | bytes) -> tuple[int, bytes]:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
            conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
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
