"""`a2a_call` against an in-process fake A2A server (stage 18 item 9).

The server is a real asyncio HTTP listener on 127.0.0.1 that serves an
Agent Card and answers JSON-RPC (`message/send`, `message/stream` as
server-sent events, `tasks/get`, `tasks/cancel`). The `a2a-sdk` package
is not installed here, so most cases drive the tool through `RawTransport`
below, a stdlib JSON-RPC client with the same four calls the SDK
transport has; `TestTheSdkTransport` runs `SdkTransport` itself over
stand-in `a2a` / `httpx` modules that speak to the same server, and a
last case uses the real SDK when it is installed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution import a2a
from simorgh.execution.a2a import A2aAgentConfig, A2aCallTool, ProposeA2aAgentTool, SdkTransport
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.ledger.factory import make_ledger
from tests.simorgh.execution.test_service import _ExecutionServiceTestCase
from tests.simorgh.helpers import FakeClock


class _Logger:
    def __init__(self) -> None:
        self.events: list[str] = []

    def debug(self, event, **f): self.events.append(event)
    def info(self, event, **f): self.events.append(event)
    def warning(self, event, **f): self.events.append(event)
    def error(self, event, **f): self.events.append(event)


def _task(task_id, state, *, text="", artifact="", context_id="ctx-1"):
    task = {"kind": "task", "id": task_id, "contextId": context_id, "status": {"state": state}}
    if text:
        task["status"]["message"] = {"kind": "message", "role": "agent", "messageId": "m",
                                     "parts": [{"kind": "text", "text": text}]}
    if artifact:
        task["artifacts"] = [{"artifactId": "a1", "parts": [{"kind": "text", "text": artifact}]}]
    return task


def _status(task_id, state, text="", final=False):
    event = {"kind": "status-update", "taskId": task_id, "contextId": "ctx-1", "final": final,
             "status": {"state": state}}
    if text:
        event["status"]["message"] = {"kind": "message", "role": "agent", "messageId": "m",
                                      "parts": [{"kind": "text", "text": text}]}
    return event


class FakeA2aServer:
    """Scripted A2A agent. `on_send(params)`, `on_stream(params)` (a list of
    events), `on_get(task_id)` and `on_cancel(task_id)` decide the answers;
    every request is kept in `requests` as `(method, headers, params)`."""

    def __init__(self, *, streaming=False, security=None, schemes=None) -> None:
        self.streaming = streaming
        self.security = security
        self.schemes = schemes
        self.requests: list[tuple[str, dict, dict]] = []
        self.on_send = lambda params: _task("t-1", "completed", artifact="answer")
        self.on_stream = lambda params: [_task("t-1", "completed", artifact="answer")]
        self.on_get = lambda task_id: _task(task_id, "completed", artifact="answer")
        self.on_cancel = lambda task_id: _task(task_id, "canceled")
        self._server = None
        self.url = ""

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/a2a"

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()

    def card(self) -> dict:
        card = {"name": "fake", "description": "a fake agent", "url": self.url, "version": "1",
                "protocolVersion": "0.3.0", "capabilities": {"streaming": self.streaming},
                "defaultInputModes": ["text"], "defaultOutputModes": ["text"], "skills": []}
        if self.security is not None:
            card["security"] = self.security
            card["securitySchemes"] = self.schemes or {}
        return card

    async def _handle(self, reader, writer) -> None:
        try:
            request_line = (await reader.readline()).decode()
            method, path, _ = request_line.split(" ", 2)
            headers = {}
            while True:
                line = (await reader.readline()).decode().strip()
                if not line:
                    break
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()
            body = await reader.readexactly(int(headers.get("content-length", "0") or 0))
            if method == "GET" and path == a2a.CARD_PATH:
                self.requests.append(("card", headers, {}))
                await self._reply(writer, 200, self.card())
                return
            rpc = json.loads(body)
            params = rpc.get("params") or {}
            self.requests.append((rpc["method"], headers, params))
            if rpc["method"] == "message/stream":
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
                for event in self.on_stream(params):
                    if event == "BREAK":
                        break
                    frame = {"jsonrpc": "2.0", "id": rpc["id"], "result": event}
                    writer.write(f"data: {json.dumps(frame)}\n\n".encode())
                    await writer.drain()
                return
            handler = {"message/send": lambda: self.on_send(params),
                       "tasks/get": lambda: self.on_get(params["id"]),
                       "tasks/cancel": lambda: self.on_cancel(params["id"])}.get(rpc["method"])
            if handler is None:
                await self._reply(writer, 200, {"jsonrpc": "2.0", "id": rpc["id"],
                                                "error": {"code": -32601, "message": "no such method"}})
                return
            await self._reply(writer, 200, {"jsonrpc": "2.0", "id": rpc["id"], "result": handler()})
        finally:
            try:
                await writer.drain()
            except ConnectionError:
                pass
            writer.close()

    @staticmethod
    async def _reply(writer, status, obj) -> None:
        body = json.dumps(obj).encode()
        writer.write(f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\n"
                     f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)


async def _http(url: str, *, method="GET", body: bytes = b"", headers=None):
    """One HTTP/1.1 exchange; returns (status, reader) with headers read."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
    lines = [f"{method} {parsed.path or '/'} HTTP/1.1", f"Host: {parsed.netloc}", "Connection: close",
             f"Content-Length: {len(body)}", "Content-Type: application/json"]
    lines += [f"{key}: {value}" for key, value in (headers or {}).items()]
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
    await writer.drain()
    status = int((await reader.readline()).split()[1])
    while (await reader.readline()).strip():
        pass
    return status, reader, writer


class RawTransport:
    """A stdlib JSON-RPC client with `SdkTransport`'s shape (tests only)."""

    def __init__(self, agent: A2aAgentConfig) -> None:
        self._agent = agent
        self._headers: dict = {}

    async def card(self) -> dict:
        _status_code, reader, writer = await _http(a2a.card_url(self._agent.url))
        try:
            return json.loads(await reader.read())
        finally:
            writer.close()

    async def connect(self, headers) -> None:
        self._headers = dict(headers)

    async def _rpc(self, method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": method, "params": params}).encode()
        _status_code, reader, writer = await _http(self._agent.url, method="POST", body=body, headers=self._headers)
        try:
            return a2a._unwrap(json.loads(await reader.read()))  # noqa: SLF001
        finally:
            writer.close()

    async def send(self, message):
        return await self._rpc("message/send", {"message": message})

    async def stream(self, message):
        body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": "message/stream",
                           "params": {"message": message}}).encode()
        _status_code, reader, writer = await _http(self._agent.url, method="POST", body=body, headers=self._headers)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if line.startswith(b"data:"):
                    yield a2a._unwrap(json.loads(line[5:]))  # noqa: SLF001
        finally:
            writer.close()
        if getattr(self, "break_after_stream", False):
            raise ConnectionResetError("stream dropped")

    async def get_task(self, task_id):
        return await self._rpc("tasks/get", {"id": task_id})

    async def cancel(self, task_id):
        return await self._rpc("tasks/cancel", {"id": task_id})

    async def close(self) -> None:
        pass


class _Case(unittest.IsolatedAsyncioTestCase):
    streaming = False

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.server = FakeA2aServer(streaming=self.streaming)
        await self.server.start()
        self.addAsyncCleanup(self.server.stop)
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.logger = _Logger()
        self.slept: list[float] = []
        self.progress: list[dict] = []

    def tool(self, *, secrets=None, progress=True, **agent_kw) -> A2aCallTool:
        agent = A2aAgentConfig(name="desk", url=self.server.url, poll_interval_s=1.0, max_wait_s=5.0, **agent_kw)

        async def _sleep(seconds):
            self.slept.append(seconds)

        async def _progress(ctx, event):
            self.progress.append(event)

        return A2aCallTool((agent,), secrets=secrets, transport_factory=RawTransport, sleep=_sleep,
                           progress=_progress if progress else None)

    def ctx(self) -> ToolContext:
        return ToolContext(action_id="act-1", task_id="task-1", scope={}, constraints={},
                           data_dir=Path(self._tmp.name), clock=self.clock, logger=self.logger, ledger=self.ledger)

    def methods(self) -> list[str]:
        return [method for method, _headers, _params in self.server.requests]


class TestStreaming(_Case):
    streaming = True

    async def test_status_updates_become_progress_and_the_artifact_is_the_answer(self):
        self.server.on_stream = lambda params: [
            _task("t-9", "submitted"),
            _status("t-9", "working", "searching three shops"),
            {"kind": "artifact-update", "taskId": "t-9", "contextId": "ctx-1",
             "artifact": {"artifactId": "a1", "parts": [{"kind": "text", "text": "Dishwasher A is $649"}]}},
            _status("t-9", "completed", final=True),
        ]
        result = await self.tool().run({"agent": "desk", "message": "price of dishwasher A"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "Dishwasher A is $649")
        self.assertEqual(self.methods(), ["card", "message/stream"])
        self.assertEqual([p["state"] for p in self.progress], ["working", "completed"])
        self.assertEqual(self.progress[0]["text"], "searching three shops")
        self.assertEqual(result.metadata["task_id"], "t-9")
        self.assertEqual(result.side_effects, ("a2a:desk:send",))

    async def test_without_a_callback_progress_goes_to_the_calls_stream(self):
        self.server.on_stream = lambda params: [_status("t-9", "working", "thinking"),
                                                _status("t-9", "completed", "done", final=True)]
        result = await self.tool(progress=False).run({"agent": "desk", "message": "hi"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        events = await self.ledger.read(a2a.A2A_CALLS_STREAM)
        types_ = [event.type for event in events]
        self.assertEqual(types_, ["sent", "progress", "progress", "completed"])
        sent = events[0].payload
        self.assertEqual((sent["agent"], sent["data"], sent["chars"]), ("desk", ["public"], 2))
        self.assertNotIn("hi", json.dumps(sent), "the message itself is not copied into the ledger")

    async def test_a_stream_that_breaks_after_the_task_exists_is_followed_by_polling(self):
        self.server.on_stream = lambda params: [_status("t-5", "working", "on it"), "BREAK"]
        self.server.on_get = lambda task_id: _task(task_id, "completed", artifact="late answer")
        tool = self.tool()
        original = tool._transport_factory  # noqa: SLF001

        def _breaking(agent):
            transport = original(agent)
            transport.break_after_stream = True
            return transport

        tool._transport_factory = _breaking  # noqa: SLF001
        result = await tool.run({"agent": "desk", "message": "hi"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "late answer")
        self.assertEqual(self.methods(), ["card", "message/stream", "tasks/get"])


class TestSendAndPoll(_Case):
    async def test_a_card_that_does_not_stream_gets_send_then_bounded_polling(self):
        answers = iter([_task("t-2", "working", text="reading"), _task("t-2", "completed", artifact="42")])
        self.server.on_send = lambda params: _task("t-2", "submitted")
        self.server.on_get = lambda task_id: next(answers)
        result = await self.tool().run({"agent": "desk", "message": "what is six times seven"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "42")
        self.assertEqual(self.methods(), ["card", "message/send", "tasks/get", "tasks/get"])
        self.assertEqual(self.slept, [1.0, 1.0])
        self.assertEqual([p["state"] for p in self.progress], ["working", "completed"])

    async def test_a_task_that_never_finishes_stops_at_max_wait_and_says_how_to_check(self):
        self.server.on_send = lambda params: _task("t-3", "working")
        self.server.on_get = lambda task_id: _task(task_id, "working")
        result = await self.tool().run({"agent": "desk", "message": "slow"}, ctx=self.ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "transient")
        self.assertIn("task_id=t-3", result.error)
        self.assertEqual(self.methods().count("tasks/get"), 5, "max_wait_s 5 / poll_interval_s 1")
        self.assertEqual(sum(self.slept), 5.0)

    async def test_a_task_id_alone_checks_on_it_without_sending_anything(self):
        self.server.on_get = lambda task_id: _task(task_id, "completed", artifact="ready")
        result = await self.tool().run({"agent": "desk", "task_id": "t-3"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.methods(), ["card", "tasks/get"])
        self.assertEqual(self.slept, [], "the first check is immediate")

    async def test_a_direct_message_reply_is_the_answer(self):
        self.server.on_send = lambda params: {"kind": "message", "role": "agent", "messageId": "r",
                                              "parts": [{"kind": "text", "text": "hello back"}]}
        result = await self.tool().run({"agent": "desk", "message": "hello"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "hello back")

    async def test_a_failed_task_is_a_failure_with_the_agents_words(self):
        self.server.on_send = lambda params: _task("t-4", "failed", text="no such product")
        result = await self.tool().run({"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "failed")
        self.assertIn("no such product", result.error)


class TestInputRequired(_Case):
    async def test_the_agents_question_comes_back_and_the_answer_continues_the_same_task(self):
        def _send(params):
            message = params["message"]
            if not message.get("taskId"):
                return _task("t-7", "input-required", text="Which city?")
            city = message["parts"][0]["text"]
            return _task("t-7", "completed", artifact=f"Delivery to {city}: Tuesday")

        self.server.on_send = _send
        tool = self.tool()
        first = await tool.run({"agent": "desk", "message": "when can it be delivered"}, ctx=self.ctx())
        self.assertTrue(first.ok, first.error)
        self.assertEqual(first.metadata["state"], "input-required")
        self.assertEqual(first.metadata["question"], "Which city?")
        self.assertIn("task_id=t-7", first.output)
        second = await tool.run({"agent": "desk", "task_id": first.metadata["task_id"],
                                 "context_id": first.metadata["context_id"], "message": "San Jose"},
                                ctx=self.ctx())
        self.assertTrue(second.ok, second.error)
        self.assertEqual(second.output, "Delivery to San Jose: Tuesday")
        sent = [params["message"] for method, _h, params in self.server.requests if method == "message/send"]
        self.assertEqual((sent[1]["taskId"], sent[1]["contextId"]), ("t-7", "ctx-1"))
        self.assertEqual(self.methods().count("card"), 1, "the card is cached between calls")


class TestCancel(_Case):
    async def test_cancel_sends_tasks_cancel(self):
        result = await self.tool().run({"agent": "desk", "task_id": "t-8", "cancel": True}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.methods(), ["card", "tasks/cancel"])
        self.assertEqual(self.server.requests[-1][2], {"id": "t-8"})
        self.assertEqual(result.metadata["state"], "canceled")

    async def test_cancel_without_a_task_id_is_refused_before_any_request(self):
        result = await self.tool().run({"agent": "desk", "cancel": True}, ctx=self.ctx())
        self.assertEqual(result.error_kind, "refused")
        self.assertEqual(self.server.requests, [])


class TestRefusals(_Case):
    async def test_an_unknown_agent_is_refused_by_name(self):
        result = await self.tool().run({"agent": "nobody", "message": "x"}, ctx=self.ctx())
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("configured: desk", result.error)
        self.assertEqual(self.server.requests, [])

    async def test_data_the_agent_may_not_receive_is_refused_and_nothing_is_sent(self):
        result = await self.tool().run({"agent": "desk", "message": "my calendar", "data": ["calendar"]},
                                       ctx=self.ctx())
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("may not receive calendar", result.error)
        self.assertEqual(self.server.requests, [])
        allowed = await self.tool(allowed_data=("public", "calendar")).run(
            {"agent": "desk", "message": "my calendar", "data": "public, calendar"}, ctx=self.ctx())
        self.assertTrue(allowed.ok, allowed.error)

    async def test_a_card_that_asks_for_oauth2_is_refused_by_scheme_name(self):
        self.server.security = [{"corp_sso": []}]
        self.server.schemes = {"corp_sso": {"type": "oauth2", "flows": {}}}
        result = await self.tool(auth_secret="DESK_TOKEN", secrets={"DESK_TOKEN": "s3cret"}).run(
            {"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("'corp_sso' (oauth2)", result.error)
        self.assertEqual(self.methods(), ["card"], "only the card was read; no message left")

    async def test_mutual_tls_and_a_query_key_are_refused_too(self):
        self.server.security = [{"mtls": []}, {"qkey": []}]
        self.server.schemes = {"mtls": {"type": "mutualTLS"},
                               "qkey": {"type": "apiKey", "in": "query", "name": "key"}}
        result = await self.tool(auth_secret="DESK_TOKEN", secrets={"DESK_TOKEN": "s"}).run(
            {"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("'mtls' (mutualTLS)", result.error)
        self.assertIn("'qkey' (apiKey in query)", result.error)

    async def test_a_bearer_card_gets_the_configured_secret(self):
        self.server.security = [{"bearer": []}]
        self.server.schemes = {"bearer": {"type": "http", "scheme": "bearer"}}
        result = await self.tool(auth_secret="DESK_TOKEN", secrets={"DESK_TOKEN": "s3cret"}).run(
            {"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        headers = self.server.requests[-1][1]
        self.assertEqual(headers["authorization"], "Bearer s3cret")
        self.assertNotIn("authorization", self.server.requests[0][1], "the card is read without the secret")

    async def test_a_header_api_key_card_gets_the_secret_in_that_header(self):
        self.server.security = [{"key": []}]
        self.server.schemes = {"key": {"type": "apiKey", "in": "header", "name": "X-Agent-Key"}}
        result = await self.tool(auth_secret="DESK_TOKEN", secrets={"DESK_TOKEN": "k"}).run(
            {"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.server.requests[-1][1]["x-agent-key"], "k")

    async def test_a_bearer_card_with_no_secret_set_is_unconfigured(self):
        self.server.security = [{"bearer": []}]
        self.server.schemes = {"bearer": {"type": "http", "scheme": "bearer"}}
        result = await self.tool(auth_secret="DESK_TOKEN", secrets={}).run(
            {"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertEqual(result.error_kind, "unconfigured")
        self.assertIn("DESK_TOKEN", result.error)
        self.assertEqual(self.methods(), ["card"])

    async def test_a_card_without_json_rpc_is_refused_by_transport_name(self):
        card = self.server.card

        def _grpc_only():
            return {**card(), "preferredTransport": "GRPC"}

        self.server.card = _grpc_only
        result = await self.tool().run({"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("'GRPC'", result.error)

    async def test_a_remote_json_rpc_error_is_reported(self):
        transport = RawTransport(A2aAgentConfig(name="desk", url=self.server.url))
        await transport.connect({})
        with self.assertRaises(a2a.A2aError):
            await transport._rpc("no/such", {})  # noqa: SLF001


class TestWithoutTheSdk(_Case):
    async def test_the_default_transport_reports_the_missing_package_and_sends_nothing(self):
        agent = A2aAgentConfig(name="desk", url=self.server.url)
        tool = A2aCallTool((agent,))
        with unittest.mock.patch.dict(sys.modules, {"a2a": None, "a2a.client": None, "a2a.types": None}):
            result = await tool.run({"agent": "desk", "message": "x"}, ctx=self.ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "unconfigured")
        self.assertIn(a2a.SDK_MISSING, result.error)
        self.assertEqual(self.server.requests, [])


def _fake_sdk_modules(server_url_holder: list) -> dict:
    """Stand-ins for `a2a.client`, `a2a.types` and `httpx` with the names and
    call shapes `SdkTransport` uses, speaking to the fake server through
    `RawTransport`."""

    class _Model:
        def __init__(self, **fields):
            self.fields = fields

        @classmethod
        def model_validate(cls, data):
            return cls(**data)

        def model_dump(self, **kw):
            return {k: (v.model_dump() if isinstance(v, _Model) else v) for k, v in self.fields.items()}

    types_mod = types.ModuleType("a2a.types")
    for name in ("MessageSendParams", "SendMessageRequest", "SendStreamingMessageRequest", "GetTaskRequest",
                 "CancelTaskRequest", "TaskQueryParams", "TaskIdParams"):
        setattr(types_mod, name, type(name, (_Model,), {}))

    seen: dict = {"headers": None, "client_url": None}

    class AsyncClient:
        def __init__(self, timeout=None, headers=None):
            self.headers = dict(headers or {})
            seen["headers"] = self.headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def aclose(self):
            pass

    def _raw(http):
        transport = RawTransport(A2aAgentConfig(name="x", url=server_url_holder[0]))
        transport._headers = http.headers  # noqa: SLF001
        return transport

    class A2ACardResolver:
        def __init__(self, httpx_client, base_url):
            self._http = httpx_client
            seen["base_url"] = base_url

        async def get_agent_card(self):
            return _Model(**(await _raw(self._http).card()))

    def _resp(result):
        return _Model(jsonrpc="2.0", id="1", result=result)

    class A2AClient:
        def __init__(self, httpx_client, url=None, agent_card=None):
            self._http = httpx_client
            seen["client_url"] = url

        async def send_message(self, request):
            return _resp(await _raw(self._http).send(request.fields["params"].fields["message"]))

        async def send_message_streaming(self, request):
            async for event in _raw(self._http).stream(request.fields["params"].fields["message"]):
                yield _resp(event)

        async def get_task(self, request):
            return _resp(await _raw(self._http).get_task(request.fields["params"].fields["id"]))

        async def cancel_task(self, request):
            return _resp(await _raw(self._http).cancel(request.fields["params"].fields["id"]))

    client_mod = types.ModuleType("a2a.client")
    client_mod.A2ACardResolver = A2ACardResolver
    client_mod.A2AClient = A2AClient
    root = types.ModuleType("a2a")
    root.client, root.types = client_mod, types_mod
    httpx_mod = types.ModuleType("httpx")
    httpx_mod.AsyncClient = AsyncClient
    return {"modules": {"a2a": root, "a2a.client": client_mod, "a2a.types": types_mod, "httpx": httpx_mod},
            "seen": seen}


class TestTheSdkTransport(_Case):
    streaming = True

    async def test_the_sdk_path_streams_and_polls_through_the_same_wire(self):
        fake = _fake_sdk_modules([self.server.url])
        self.server.security = [{"bearer": []}]
        self.server.schemes = {"bearer": {"type": "http", "scheme": "bearer"}}
        self.server.on_stream = lambda params: [_status("t-1", "working", "busy"), "BREAK"]
        self.server.on_get = lambda task_id: _task(task_id, "completed", artifact="via the sdk")
        agent = A2aAgentConfig(name="desk", url=self.server.url, auth_secret="DESK_TOKEN", poll_interval_s=1.0)

        async def _sleep(_s):
            return None

        tool = A2aCallTool((agent,), secrets={"DESK_TOKEN": "tok"}, sleep=_sleep)
        with unittest.mock.patch.dict(sys.modules, fake["modules"]):
            result = await tool.run({"agent": "desk", "message": "hi"}, ctx=self.ctx())
            cancelled = await tool.run({"agent": "desk", "task_id": "t-1", "cancel": True}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "via the sdk")
        self.assertTrue(cancelled.ok, cancelled.error)
        self.assertEqual(self.methods(), ["card", "message/stream", "tasks/get", "tasks/cancel"])
        self.assertEqual(fake["seen"]["headers"], {"Authorization": "Bearer tok"})
        self.assertEqual(fake["seen"]["client_url"], self.server.url, "the configured URL, never the card's")
        self.assertEqual(fake["seen"]["base_url"], self.server.url.rsplit("/a2a", 1)[0])

    @unittest.skipUnless(__import__("importlib").util.find_spec("a2a") is not None, "a2a-sdk not installed")
    async def test_the_real_sdk_against_the_fake_server(self):  # pragma: no cover - optional package
        self.server.on_stream = lambda params: [_status("t-1", "working", "busy"),
                                                _task("t-1", "completed", artifact="real sdk")]
        agent = A2aAgentConfig(name="desk", url=self.server.url)
        result = await A2aCallTool((agent,)).run({"agent": "desk", "message": "hi"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIsInstance(SdkTransport(agent), SdkTransport)


class TestConfigAndProposal(_Case):
    async def test_agents_load_from_a_table_per_name_and_register_a2a_call(self):
        config = ExecutionConfig.from_mapping({"a2a_agents": {
            "desk": {"url": "https://agents.example/a2a", "auth_secret": "DESK_TOKEN",
                     "allowed_data": ["public", "Calendar"]}}})
        (agent,) = config.a2a_agents
        self.assertEqual((agent.name, agent.auth_secret, agent.allowed_data),
                         ("desk", "DESK_TOKEN", ("public", "calendar")))
        names = [tool.name for tool in a2a.a2a_tools(config)]
        self.assertEqual(names, ["propose_a2a_agent", "a2a_call"])
        self.assertEqual([tool.name for tool in a2a.a2a_tools(ExecutionConfig.from_mapping({}))],
                         ["propose_a2a_agent"], "no agent configured: nothing to call")
        call = a2a.a2a_tools(config)[1]
        self.assertEqual(call.reversibility, "irreversible")
        self.assertGreater(call.timeout_s, agent.max_wait_s)

    async def test_a_proposal_is_recorded_and_never_configures_anything(self):
        tool = ProposeA2aAgentTool()
        result = await tool.run({"proposal": "name: research_desk\nurl: https://agents.example/a2a\n"
                                             "allowed_data: public\nauth_secret: DESK_TOKEN\n"
                                             "reason: compares prices across shops"}, ctx=self.ctx())
        self.assertTrue(result.ok, result.error)
        (event,) = await self.ledger.read(a2a.A2A_PROPOSALS_STREAM)
        self.assertEqual(event.payload["name"], "research_desk")
        self.assertEqual(event.payload["status"], "pending")
        self.assertEqual(event.payload["allowed_data"], ["public"])
        self.assertEqual(tool.reversibility, "reversible")

    async def test_a_bad_proposal_is_refused(self):
        tool = ProposeA2aAgentTool()
        for text, needle in (
            ("name: Desk\nurl: https://x\nreason: r", "name"),
            ("name: desk\nurl: ftp://x\nreason: r", "url"),
            ("name: desk\nurl: https://x\nauth_secret: sk-live-123\nreason: r", "auth_secret"),
            ("name: desk\nurl: https://x", "reason"),
        ):
            result = await tool.run({"proposal": text}, ctx=self.ctx())
            self.assertEqual(result.error_kind, "refused", text)
            self.assertIn(needle, result.error)
        ok = await tool.run({"proposal": json.dumps({"name": "desk", "url": "http://10.0.0.5:8080/a2a",
                                                     "allowed_data": ["public", "calendar"],
                                                     "reason": "the other Sim"})}, ctx=self.ctx())
        self.assertTrue(ok.ok, ok.error)


class TestGuardianGatesTheCall(_ExecutionServiceTestCase):
    """`a2a_call` runs only through `_on_approved`: a denial means no
    request of any kind reaches the remote agent."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.server = FakeA2aServer()
        await self.server.start()
        self.addAsyncCleanup(self.server.stop)

    async def _ready(self, *, approve: bool):
        config = ExecutionConfig(repo_root=self.root, a2a_agents=(A2aAgentConfig(name="desk", url=self.server.url),))
        await self._start(config=config)
        self.assertIn("a2a_call", self.service._registry)  # noqa: SLF001
        self.service._registry["a2a_call"] = A2aCallTool(  # noqa: SLF001
            config.a2a_agents, transport_factory=RawTransport)
        guardian = await self._guardian(approve=approve)
        return guardian

    async def test_a_denied_call_makes_no_http_request(self):
        guardian = await self._ready(approve=False)
        result = await self.service._self_actions.run(  # noqa: SLF001
            "a2a_call", {"agent": "desk", "message": "hi"}, rationale="test", timeout=5.0)
        self.assertFalse(result.ok)
        self.assertTrue(result.metadata.get("denied"))
        self.assertEqual(guardian.proposals[0]["reversibility"], "irreversible")
        self.assertEqual(self.server.requests, [])

    async def test_an_approved_call_reaches_the_agent(self):
        await self._ready(approve=True)
        result = await self.service._self_actions.run(  # noqa: SLF001
            "a2a_call", {"agent": "desk", "message": "hi"}, rationale="test", timeout=10.0)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, "answer")
        self.assertEqual([m for m, _h, _p in self.server.requests], ["card", "message/send"])


if __name__ == "__main__":
    unittest.main()
