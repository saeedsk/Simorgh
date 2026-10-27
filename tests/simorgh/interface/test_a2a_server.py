"""Sim serves its agents over A2A (stage 18 item 10).

Driven end to end over a real socket with a raw JSON-RPC client -- the
`a2a-sdk` is not a dependency -- against a fake Orchestration on the bus:
it answers `crew.spawn` with a handle and then says what a running member
says (`crew.message` progress, maybe a question) and files its
`crew.report`. What is pinned: the card lists only the exposed agents;
`message/send` returns the finished task with its report as an artifact;
`message/stream` streams progress as status updates; a question is
`input-required` and the caller's answer reaches the member; `tasks/get`
and `tasks/cancel` map to the crew; the requester is the paired device's
person; and no token, the shared token, or an unexposed agent runs nothing.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import tempfile
import unittest
from pathlib import Path

import pytest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.interface.a2a import A2AServer, agent_card, agent_skill
from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import HttpApi

pytestmark = pytest.mark.contract

AGENTS = Path(__file__).resolve().parents[3] / "agents"


class _Sub:
    def __init__(self, subs, entry):
        self._subs, self._entry = subs, entry

    async def unsubscribe(self):
        if self._entry in self._subs:
            self._subs.remove(self._entry)


class _Orchestration:
    """The bus, with a fake crew runtime behind `crew.spawn`."""

    def __init__(self, *, script: str = "report") -> None:
        self.script = script
        self.requests: list[Message] = []
        self.published: list[Message] = []
        self._subs: list = []
        self.answered = asyncio.Event()
        self.n = 0

    def new(self, type_, payload, **_kw):
        return Message.new(type_, source="interface", payload=payload)

    async def subscribe(self, type_, handler, **_kw):
        entry = (type_, handler)
        self._subs.append(entry)
        return _Sub(self._subs, entry)

    async def publish(self, message):
        self.published.append(message)
        for type_, handler in list(self._subs):
            if type_ == message.type:
                await handler(message)
        if message.type == topics.CREW_MESSAGE and message.payload.get("kind") == "answer":
            self.answered.set()

    async def _say(self, type_, payload, delay=0.05):
        await asyncio.sleep(delay)
        await self.publish(Message.new(type_, source="orchestration", payload=payload))

    async def request(self, message, *, timeout=None):
        self.requests.append(message)
        assert message.type == topics.CREW_SPAWN
        self.n += 1
        crew, handle = f"crew{self.n:04d}", f"member{self.n:04d}"
        asyncio.ensure_future(self._run(crew, handle))
        return Message.new(topics.CREW_SPAWN_REPLY, source="orchestration",
                           payload={"crew_id": crew, "handle": handle})

    async def _run(self, crew, handle):
        await self._say(topics.CREW_SPAWNED, {"crew_id": crew, "handle": handle, "parent": crew,
                                               "agent": "research", "brief_ref": "x", "report_policy": "progress",
                                               "budget": {}})
        await self._say(topics.CREW_MESSAGE, {"crew_id": crew, "from": handle, "to": crew, "kind": "progress",
                                               "body": "read two reviews", "seq": 1})
        if self.script == "question":
            await self._say(topics.CREW_MESSAGE, {"crew_id": crew, "from": handle, "to": crew, "kind": "question",
                                                   "body": "which postcode?", "seq": 2})
            await asyncio.wait_for(self.answered.wait(), timeout=5)
        if self.script == "hang":
            return
        await self._say(topics.CREW_REPORT, {"crew_id": crew, "handle": handle, "report": {
            "status": "ok", "summary": "B is cheaper by $40", "findings": [{"claim": "B $649", "evidence_ref": "blob:1"}],
            "steps": 3, "cost_usd": 0.01}})


class _Base(unittest.IsolatedAsyncioTestCase):
    async def _start(self, *, script: str = "report", expose=("research",), token: str = "shared"):
        self.bus = _Orchestration(script=script)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.book = DeviceBook(Path(tmp.name) / "devices.json")
        self.book.begin_pairing(name="laptop-agent", person="Saeed")
        _, self.device_token = self.book.redeem(self.book.pending().code)
        self.api = HttpApi(self.bus, host="127.0.0.1", port=0, token=token, devices=self.book)
        self.a2a = A2AServer(self.bus, expose=expose, agents_dir=AGENTS, send_wait_s=5.0, stream_idle_s=5.0)
        await self.a2a.start()
        self.api.serve_a2a(self.a2a)
        await self.api.start()
        self.addAsyncCleanup(self.api.stop)
        self.addAsyncCleanup(self.a2a.stop)

    async def _http(self, method: str, path: str, body=None, *, token: str | None = None):
        token = self.device_token if token is None else token

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=10)
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)

    async def _rpc(self, method: str, params: dict, **kw) -> dict:
        resp = await self._http("POST", "/a2a", {"jsonrpc": "2.0", "id": 7, "method": method, "params": params}, **kw)
        self.assertEqual(resp.status, 200, resp.body)
        return json.loads(resp.body)

    @staticmethod
    def _message(text: str, **extra) -> dict:
        return {"message": {"role": "user", "messageId": "m1", "parts": [{"kind": "text", "text": text}], **extra}}


class TheCard(_Base):
    async def test_the_card_lists_only_the_exposed_agents_with_their_skills(self):
        await self._start(expose=("research",))
        resp = await self._http("GET", "/.well-known/agent-card.json")
        self.assertEqual(resp.status, 200, resp.body)
        card = json.loads(resp.body)
        self.assertEqual([s["id"] for s in card["skills"]], ["research"])
        self.assertIn("evidence", card["skills"][0]["description"], "the skill is described from agents/research.md")
        self.assertTrue(card["url"].endswith("/a2a"))
        self.assertTrue(card["capabilities"]["streaming"])
        self.assertFalse(card["capabilities"]["pushNotifications"])
        self.assertEqual(card["security"], [{"bearer": []}])

    def test_an_agent_without_a_file_is_not_listed(self):
        card = agent_card(url="http://x/a2a", expose=("research", "no_such_agent", "../etc"), agents_dir=AGENTS)
        self.assertEqual([s["id"] for s in card["skills"]], ["research"])
        self.assertIsNone(agent_skill("no_such_agent", AGENTS))


class TheGate(_Base):
    async def test_no_token_is_a_401_and_nothing_runs(self):
        await self._start()
        resp = await self._http("POST", "/a2a", {"jsonrpc": "2.0", "id": 1, "method": "message/send",
                                                 "params": self._message("hi")}, token="")
        self.assertEqual(resp.status, 401)
        self.assertEqual((await self._http("GET", "/.well-known/agent-card.json", token="")).status, 401)
        self.assertEqual(self.bus.requests, [])

    async def test_the_shared_token_names_nobody_and_is_refused(self):
        await self._start(token="shared")
        resp = await self._http("POST", "/a2a", {"jsonrpc": "2.0", "id": 1, "method": "message/send",
                                                 "params": self._message("hi")}, token="shared")
        self.assertEqual(resp.status, 401)
        self.assertIn(b"paired", resp.body)
        self.assertEqual(self.bus.requests, [])

    async def test_on_this_machine_with_no_token_set_a_device_is_still_required(self):
        await self._start(token="")
        resp = await self._http("POST", "/a2a", {"jsonrpc": "2.0", "id": 1, "method": "message/send",
                                                 "params": self._message("hi")}, token="")
        self.assertEqual(resp.status, 401)

    async def test_an_agent_not_exposed_is_refused_by_name(self):
        await self._start(expose=("research",))
        reply = await self._rpc("message/send", {**self._message("fix the bug"), "metadata": {"agent": "patch"}})
        self.assertEqual(reply["error"]["code"], -32602)
        self.assertIn("'patch' is not served", reply["error"]["message"])
        self.assertEqual(self.bus.requests, [])


class TheMethods(_Base):
    async def test_message_send_runs_research_and_returns_the_report_as_an_artifact(self):
        await self._start()
        reply = await self._rpc("message/send", self._message("which dishwasher is cheaper?"))
        task = reply["result"]
        self.assertEqual(task["kind"], "task")
        self.assertEqual(task["status"]["state"], "completed", task)
        self.assertEqual(task["id"], "member0001")
        self.assertEqual(task["contextId"], "crew0001")
        artifact = task["artifacts"][0]
        self.assertEqual(artifact["parts"][0], {"kind": "text", "text": "B is cheaper by $40"})
        self.assertEqual(artifact["parts"][1]["data"]["findings"][0]["claim"], "B $649")
        spawn = self.bus.requests[0].payload
        self.assertEqual((spawn["agent"], spawn["brief"]), ("research", "which dishwasher is cheaper?"))
        self.assertEqual(spawn["requester"], "Saeed", "the requester is the paired caller's person")
        self.assertEqual(spawn["requester_channel"], "a2a")
        self.assertEqual(spawn["device"], "laptop-agent")
        got = await self._rpc("tasks/get", {"id": "member0001"})
        self.assertEqual(got["result"]["status"]["state"], "completed")

    async def test_message_stream_sends_progress_as_status_updates(self):
        await self._start()

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=10)
            conn.request("POST", "/a2a", body=json.dumps({"jsonrpc": "2.0", "id": 3, "method": "message/stream",
                                                          "params": self._message("compare A and B")}),
                         headers={"Authorization": f"Bearer {self.device_token}", "Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.getheader("Content-Type") == "text/event-stream"
            raw = resp.read().decode("utf-8")
            conn.close()
            return [json.loads(chunk[len("data: "):]) for chunk in raw.split("\n\n") if chunk.startswith("data: ")]

        events = [e["result"] for e in await asyncio.to_thread(_do)]
        self.assertEqual(events[0]["kind"], "task")
        progress = [e for e in events if e.get("kind") == "status-update" and e["status"]["state"] == "working"]
        self.assertGreaterEqual(len(progress), 1, events)
        self.assertEqual(progress[0]["status"]["message"]["parts"][0]["text"], "read two reviews")
        self.assertTrue(any(e.get("kind") == "artifact-update" for e in events), events)
        self.assertEqual(events[-1]["kind"], "status-update")
        self.assertTrue(events[-1]["final"])
        self.assertEqual(events[-1]["status"]["state"], "completed")

    async def test_a_question_is_input_required_and_the_answer_reaches_the_member(self):
        await self._start(script="question")
        first = (await self._rpc("message/send", self._message("delivery dates?")))["result"]
        self.assertEqual(first["status"]["state"], "input-required", first)
        self.assertEqual(first["status"]["message"]["parts"][0]["text"], "which postcode?")
        done = (await self._rpc("message/send", self._message("95112", taskId=first["id"])))["result"]
        self.assertEqual(done["status"]["state"], "completed", done)
        answer = [m for m in self.bus.published if m.type == topics.CREW_MESSAGE and m.payload["kind"] == "answer"][0]
        self.assertEqual(answer.payload["to"], first["id"])
        self.assertEqual(answer.payload["body"], "95112")
        self.assertEqual(answer.payload["reply_to"], 2)
        self.assertEqual(len(self.bus.requests), 1, "an answer is not a second crew")

    async def test_tasks_cancel_asks_the_crew_and_the_task_reads_canceled(self):
        await self._start(script="hang")
        task = (await self._rpc("message/send", {**self._message("go"), "configuration": {"blocking": False}}))["result"]
        self.assertIn(task["status"]["state"], ("submitted", "working"))
        cancelled = (await self._rpc("tasks/cancel", {"id": task["id"]}))["result"]
        self.assertEqual(cancelled["status"]["state"], "canceled")
        cancel = [m for m in self.bus.published if m.type == topics.CREW_CANCEL][0]
        self.assertEqual((cancel.payload["crew_id"], cancel.payload["handle"], cancel.payload["cascade"]),
                         (task["contextId"], task["id"], True))
        again = await self._rpc("tasks/cancel", {"id": task["id"]})
        self.assertEqual(again["error"]["code"], -32002)

    async def test_another_callers_task_is_not_found(self):
        await self._start()
        task = (await self._rpc("message/send", self._message("x")))["result"]
        self.book.begin_pairing(name="someone-else", person="Guest")
        _, other = self.book.redeem(self.book.pending().code)
        reply = await self._rpc("tasks/get", {"id": task["id"]}, token=other)
        self.assertEqual(reply["error"]["code"], -32001)

    async def test_a_file_part_and_an_unknown_method_are_refused(self):
        await self._start()
        reply = await self._rpc("message/send", {"message": {"role": "user", "parts": [
            {"kind": "file", "file": {"uri": "https://example.invalid/x.pdf"}}]}})
        self.assertEqual(reply["error"]["code"], -32005)
        self.assertEqual((await self._rpc("tasks/pushNotificationConfig/set", {}))["error"]["code"], -32003)
        self.assertEqual((await self._rpc("agent/dance", {}))["error"]["code"], -32601)
        self.assertEqual(self.bus.requests, [])


class OffByDefault(unittest.IsolatedAsyncioTestCase):
    async def test_without_serve_a2a_neither_path_exists(self):
        api = HttpApi(_Orchestration(), host="127.0.0.1", port=0, token="")
        await api.start()
        self.addAsyncCleanup(api.stop)

        def _do(method, path):
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request(method, path, body="{}" if method == "POST" else None)
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp.status

        self.assertEqual(await asyncio.to_thread(_do, "GET", "/.well-known/agent-card.json"), 404)
        self.assertEqual(await asyncio.to_thread(_do, "POST", "/a2a"), 404)

    def test_the_setting_is_off_and_exposes_research(self):
        from simorgh.interface.config import Config

        self.assertFalse(Config().a2a_enabled)
        self.assertEqual(Config().a2a_expose, ("research",))
        config = Config.from_mapping({"a2a": {"enabled": True, "expose": ["research", "browser"]}})
        self.assertTrue(config.a2a_enabled)
        self.assertEqual(config.a2a_expose, ("research", "browser"))
