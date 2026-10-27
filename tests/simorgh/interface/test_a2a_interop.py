"""The A2A interop proof (stage 18 item 11): Sim calls Sim over A2A.

Two Sims in one test process, sharing nothing but a localhost socket:
each has its own bus and its own ledger.

- **The caller** runs the real Guardian and the real Execution. A remote
  call is what Orchestration's `a2a:<name>` member proposes: `a2a_call`,
  on `action.proposed`, as the person who asked. It is tier 3, so
  Guardian asks a person every time (`ui.prompt`), and only an approved
  call reaches Execution and leaves the house.
- **The callee** runs Interface's HTTP listener with a paired device
  (`DeviceBook`), the A2A server on it, the real Orchestration crew
  runtime behind `crew.spawn`, and the real Guardian and Execution under
  the member's own tool calls. Only the model is scripted: a fake
  `cognition.think` that never calls a provider.

What is proved, over the real socket: the card is read (behind the paired
token) and the version agreed both ways; `message/stream` carries the
member's progress as status updates the caller's `a2a:calls` stream
records; `input-required` is answered with a second call naming the task;
`tasks/get` is the polling path; `tasks/cancel` stops the member; the
member's tool calls reach the callee's Guardian as the paired person on
channel `a2a`; and a call the caller's person declines sends nothing.

The caller's transport has two halves. `PlainTransport` below is plain
HTTP JSON-RPC from the standard library, so the proof never depends on
the optional `a2a-sdk`. `TestTheSdkClient` drives the same conversation
through `SdkTransport`, the official SDK client, and is skipped by name
when the package is absent.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import pytest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.execution import a2a as client_a2a
from simorgh.execution.a2a import A2aAgentConfig, CardUnauthorized
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.service import Service as ExecutionService
from simorgh.guardian.config import Config as GuardianConfig
from simorgh.guardian.service import Service as GuardianService
from simorgh.interface import a2a as server_a2a
from simorgh.interface.a2a import A2AServer
from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import HttpApi
from simorgh.ledger.backends.memory import InMemoryBackend as LedgerMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.orchestration.config import Config as OrchestrationConfig
from simorgh.orchestration.service import Service as OrchestrationService

from tests.simorgh.helpers import FakeClock

pytestmark = pytest.mark.contract

AGENTS = Path(__file__).resolve().parents[3] / "agents"
HAS_SDK = importlib.util.find_spec("a2a") is not None and importlib.util.find_spec("httpx") is not None
PERSON = "Saeed"


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


# ---------------------------------------------------------------- one Sim
class _Sim:
    """One Sim's substrate: a bus backend and a ledger of its own. Each
    subsystem gets its own named bus client, as the Kernel hands out."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = FakeClock()
        self.ledger = LedgerClient(LedgerMemoryBackend(), clock=self.clock)
        config = BusConfig(max_deliveries=3, metrics_interval_seconds=0)
        self._config = config
        self._backend = make_backend(config, clock=self.clock)
        self._clients: dict[str, Any] = {}
        self.hmac = uuid.uuid4().hex * 2

    async def start(self) -> None:
        await self.ledger.start()

    def bus(self, name: str):
        if name not in self._clients:
            self._clients[name] = make_client(self._backend, source=name, config=self._config, ledger=self.ledger,
                                              clock=self.clock.now)
        return self._clients[name]

    def ctx(self, name: str, *, secrets: Mapping[str, str] | None = None) -> Context:
        return Context(name=name, instance_id="", run_id="interop", mode="single", bus=self.bus(name),
                       ledger=self.ledger, config={}, secrets=dict(secrets or {}), clock=self.clock,
                       logger=_Logger(), data_dir=self.root / name)


class _Cognition:
    """`cognition.think` for the callee's member, scripted: one step per
    think, the last repeating. A step is a reply dict, or an async
    function of the think message returning one (to hold the member
    mid-task). Never a provider."""

    def __init__(self, bus, script: list) -> None:
        self._bus = bus
        self.script = script
        self.calls: list[Message] = []
        self._sub = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self) -> None:
        if self._sub is not None:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        self.calls.append(message)
        step = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if callable(step):
            step = await step(message)
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": step.get("text", ""), "tool_calls": step.get("tool_calls", []), "provider": "fake",
            "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False})


def _call(i: int, tool: str, **args) -> dict:
    return {"id": f"c{i}", "tool": tool, "args": args}


# ---------------------------------------------------------------- the plain transport
async def _http(url: str, *, method: str = "GET", body: bytes = b"", headers: Mapping[str, str] | None = None):
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


class PlainTransport:
    """A2A over plain HTTP JSON-RPC, standard library only, with
    `SdkTransport`'s shape: what the caller speaks when the `a2a-sdk` is
    not installed. Every request is recorded with its headers."""

    log: list[tuple[str, dict]] = []

    def __init__(self, agent: A2aAgentConfig) -> None:
        self._agent = agent
        self._headers: dict[str, str] = {}

    async def card(self, headers: Mapping[str, str] | None = None) -> dict:
        PlainTransport.log.append(("card", dict(headers or {})))
        status, reader, writer = await _http(client_a2a.card_url(self._agent.url), headers=headers)
        try:
            body = await reader.read()
        finally:
            writer.close()
        if status in (401, 403):
            raise CardUnauthorized(f"the agent card answered {status}")
        if status != 200:
            raise ConnectionError(f"card: HTTP {status}")
        return json.loads(body)

    async def connect(self, headers: Mapping[str, str]) -> None:
        self._headers = dict(headers)

    def _body(self, method: str, params: dict) -> bytes:
        PlainTransport.log.append((method, dict(self._headers)))
        return json.dumps({"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": params}).encode()

    async def _rpc(self, method: str, params: dict) -> dict:
        status, reader, writer = await _http(self._agent.url, method="POST", body=self._body(method, params),
                                             headers=self._headers)
        try:
            body = await reader.read()
        finally:
            writer.close()
        if status != 200:
            raise ConnectionError(f"{method}: HTTP {status}: {body[:200]!r}")
        return client_a2a._unwrap(json.loads(body))  # noqa: SLF001 -- the SDK path's own reader

    async def send(self, message: dict) -> dict:
        return await self._rpc("message/send", {"message": message})

    async def stream(self, message: dict):
        status, reader, writer = await _http(self._agent.url, method="POST",
                                             body=self._body("message/stream", {"message": message}),
                                             headers=self._headers)
        if status != 200:
            writer.close()
            raise ConnectionError(f"message/stream: HTTP {status}")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if line.startswith(b"data:"):
                    yield client_a2a._unwrap(json.loads(line[5:]))  # noqa: SLF001
        finally:
            writer.close()

    async def get_task(self, task_id: str) -> dict:
        return await self._rpc("tasks/get", {"id": task_id})

    async def cancel(self, task_id: str) -> dict:
        return await self._rpc("tasks/cancel", {"id": task_id})

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------- the two Sims
class _Interop(unittest.IsolatedAsyncioTestCase):
    #: The caller's transport factory; None is the default, the SDK.
    transport = PlainTransport

    async def asyncSetUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        PlainTransport.log = []
        self.script: list = [{"text": "done.\n- nothing to add"}]
        await self._start_callee()
        await self._start_caller()

    async def _start_callee(self) -> None:
        sim = self.callee = _Sim(self.root / "callee")
        repo = self.root / "callee-repo"
        (repo / "simorgh_skills").mkdir(parents=True)
        (repo / "docs").mkdir()
        (repo / "docs" / "reviews.md").write_text("Dishwasher A: $689. Dishwasher B: $649.\n", encoding="utf-8")
        await sim.start()
        # The member's own tool calls: the callee's Guardian and Execution.
        self.callee_guardian = GuardianService(config=GuardianConfig(mode="guarded"))
        await self.callee_guardian.start(sim.ctx("guardian", secrets={"__hmac__": sim.hmac}))
        self.addAsyncCleanup(self.callee_guardian.stop)
        self.callee_execution = ExecutionService(config=ExecutionConfig(repo_root=repo))
        await self.callee_execution.start(sim.ctx("execution", secrets={"__hmac__": sim.hmac}))
        self.addAsyncCleanup(self.callee_execution.stop)
        self.proposals: list[dict] = []

        async def _seen(message: Message) -> None:
            self.proposals.append(dict(message.payload))
        # Watching, not consuming: its own group, so Guardian still gets each.
        await sim.bus("observer").subscribe(topics.ACTION_PROPOSED, _seen, group="observer-proposed")
        self.callee_results: list[dict] = []

        async def _ran(message: Message) -> None:
            self.callee_results.append(dict(message.payload))
        await sim.bus("observer").subscribe(topics.ACTION_RESULT, _ran, group="observer-result")
        self.cognition = _Cognition(sim.bus("cognition"), self.script)
        await self.cognition.start()
        self.addAsyncCleanup(self.cognition.stop)
        self.orchestration = OrchestrationService(OrchestrationConfig(
            workers=1, metrics_interval_s=0, skills_enabled=False, worktrees=False, think_timeout_s=30.0))
        await self.orchestration.start(sim.ctx("orchestration"))
        self.addAsyncCleanup(self.orchestration.stop)
        # Interface: the phone's listener, a paired device, the A2A server.
        self.book = DeviceBook(self.root / "devices.json")
        self.book.begin_pairing(name="other-sim", person=PERSON)
        _, self.device_token = self.book.redeem(self.book.pending().code)
        self.server = A2AServer(sim.bus("interface"), expose=("research",), agents_dir=AGENTS,
                                send_wait_s=20.0, stream_idle_s=20.0)
        await self.server.start()
        self.addAsyncCleanup(self.server.stop)
        self.api = HttpApi(sim.bus("interface"), host="127.0.0.1", port=0, token="shared-legacy",
                           devices=self.book)
        self.api.serve_a2a(self.server)
        await self.api.start()
        self.addAsyncCleanup(self.api.stop)
        self.url = f"http://127.0.0.1:{self.api.port}{server_a2a.RPC_PATH}"

    async def _start_caller(self, *, token: str | None = None) -> None:
        sim = self.caller = _Sim(self.root / "caller")
        repo = self.root / "caller-repo"
        (repo / "simorgh_skills").mkdir(parents=True)
        await sim.start()
        secrets = {"__hmac__": sim.hmac, "OTHER_SIM_TOKEN": self.device_token if token is None else token}
        self.guardian = GuardianService(config=GuardianConfig(mode="guarded"))
        await self.guardian.start(sim.ctx("guardian", secrets=secrets))
        self.addAsyncCleanup(self.guardian.stop)
        agent = A2aAgentConfig(name="other_sim", url=self.url, auth_secret="OTHER_SIM_TOKEN",
                               poll_interval_s=0.05, max_wait_s=20.0, timeout_s=10.0)
        self.execution = ExecutionService(config=ExecutionConfig(repo_root=repo, a2a_agents=(agent,)))
        await self.execution.start(sim.ctx("execution", secrets=secrets))
        self.addAsyncCleanup(self.execution.stop)
        tool = self.execution._registry["a2a_call"]  # noqa: SLF001 -- the registered tool, its secrets and all
        if self.transport is not None:
            tool._transport_factory = self.transport  # noqa: SLF001
        # What the caller's person sees and says: every `ui.prompt`.
        self.prompts: list[dict] = []
        self.answer = "yes"
        self.outcomes: dict[str, Message] = {}
        ui = sim.bus("interface")

        async def _prompt(message: Message) -> None:
            self.prompts.append(dict(message.payload))
            await ui.publish(Message.new(topics.UI_PROMPT_ANSWERED, source="interface", payload={
                "prompt_id": message.payload["prompt_id"], "answer": self.answer}))

        async def _outcome(message: Message) -> None:
            self.outcomes[str(message.payload.get("action_id"))] = message

        await ui.subscribe(topics.UI_PROMPT, _prompt)
        await sim.bus("observer").subscribe(topics.ACTION_RESULT, _outcome, group="observer-result")
        await sim.bus("observer").subscribe(topics.ACTION_DENIED, _outcome)

    # -- the caller's side ------------------------------------------------------------
    async def a2a_call(self, **args) -> tuple[Message, dict]:
        """One remote call as Orchestration's `a2a:<name>` member proposes
        it: `a2a_call` as the person who asked, through Guardian. Returns
        the outcome (`action.result` or `action.denied`) and the result's
        metadata (`state`, `task_id`, `question`)."""
        action_id = uuid.uuid4().hex[:12]
        await self.caller.bus("orchestration").publish(Message.new(
            topics.ACTION_PROPOSED, source="orchestration", payload={
                "action_id": action_id, "tool": "a2a_call", "args": {"agent": "other_sim", **args},
                "scope": {"network": True}, "reversibility": "irreversible",
                "rationale": "a2a member: interop proof", "proposed_by": "orchestration",
                "requester": PERSON, "requester_channel": "cli"}))
        deadline = time.monotonic() + 30.0
        while action_id not in self.outcomes:
            self.assertLess(time.monotonic(), deadline, f"no outcome for {args}")
            await asyncio.sleep(0.01)
        outcome = self.outcomes[action_id]
        meta: dict = {}
        ref = str(outcome.payload.get("metadata_ref") or "")
        if ref:
            meta = json.loads((await self.caller.ledger.get_blob(ref)).decode("utf-8"))
        return outcome, meta

    async def calls_stream(self) -> list:
        return await self.caller.ledger.read(client_a2a.A2A_CALLS_STREAM)

    # -- the callee's side ------------------------------------------------------------
    async def crew_events(self) -> list:
        events = []
        for task in self.server._tasks.values():  # noqa: SLF001
            events.extend(await self.callee.ledger.read(f"crew:{task.crew_id}"))
        return events

    async def until(self, predicate, *, timeout: float = 20.0, what: str = "") -> None:
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, f"never happened: {what}")
            await asyncio.sleep(0.01)

    def held(self):
        """A think that does not come back until the test ends: the
        member is mid-task for as long as the test needs it to be."""
        release = asyncio.Event()

        async def _clean() -> None:
            release.set()
        # Registered last, so it runs first: before any service stops.
        self.addAsyncCleanup(_clean)

        async def _step(_message):
            await release.wait()
            return {"text": "released"}
        return _step

    def tool(self):
        return self.execution._registry["a2a_call"]  # noqa: SLF001

    def tasks(self) -> list:
        return list(self.server._tasks.values())  # noqa: SLF001

    async def raw(self, method: str, params: dict, *, version: str | None) -> dict:
        """One JSON-RPC request as any HTTP client sends it."""
        headers = {"Authorization": f"Bearer {self.device_token}"}
        if version is not None:
            headers[server_a2a.VERSION_HEADER] = version
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        status, reader, writer = await _http(self.url, method="POST", body=body, headers=headers)
        try:
            self.assertEqual(status, 200)
            return json.loads(await reader.read())
        finally:
            writer.close()


# ---------------------------------------------------------------- the proofs
class TestSimCallsSim(_Interop):
    async def test_a_streamed_task_runs_end_to_end_with_progress_and_the_report(self):
        self.script[:] = [
            {"tool_calls": [_call(1, "report_progress", text="reading two reviews")]},
            {"tool_calls": [{"id": "c2", "tool": "read_file", "args": {"path": "docs/reviews.md"}}]},
            {"text": "Dishwasher B is cheaper by $40.\n- reviews.md: A $689, B $649"},
        ]
        outcome, meta = await self.a2a_call(message="Which dishwasher is cheaper, A or B?")

        self.assertEqual(outcome.type, topics.ACTION_RESULT, outcome.payload)
        self.assertTrue(outcome.payload["ok"], outcome.payload)
        self.assertIn("cheaper by $40", outcome.payload["stdout_preview"])
        self.assertEqual(meta["state"], "completed")
        # The caller's person was asked, once, before anything left.
        self.assertEqual(len(self.prompts), 1)
        # The wire: the card (behind the paired token), then one stream,
        # every request in the agreed version with the paired token.
        self.assertEqual([m for m, _h in PlainTransport.log], ["card", "card", "message/stream"])
        self.assertEqual(PlainTransport.log[0][1], {}, "the card is asked for without a credential first")
        self.assertEqual(PlainTransport.log[1][1], {"Authorization": f"Bearer {self.device_token}"})
        self.assertEqual(PlainTransport.log[2][1], {"Authorization": f"Bearer {self.device_token}",
                                                    client_a2a.VERSION_HEADER: "0.3"})
        # Progress: the member's status updates reached the caller's ledger.
        progress = [e.payload for e in await self.calls_stream() if e.type == "progress"]
        self.assertIn("reading two reviews", " ".join(p["text"] for p in progress))
        self.assertEqual(progress[-1]["state"], "completed")
        # The callee's side: one crew, for the paired person.
        (task,) = self.tasks()
        self.assertEqual((task.requester, task.state), (PERSON, "completed"))
        spawned = [e.payload for e in await self.crew_events() if e.type == topics.CREW_SPAWNED]
        self.assertEqual(len(spawned), 1)
        # The member's own tool call went to the callee's Guardian as the
        # paired person, on channel a2a, and ran.
        proposal = next(p for p in self.proposals if p.get("tool") == "read_file")
        self.assertEqual((proposal.get("requester"), proposal.get("requester_channel")), (PERSON, "a2a"))
        ran = next(r for r in self.callee_results if r["action_id"] == proposal["action_id"])
        self.assertTrue(ran["ok"], ran)

    async def test_input_required_is_answered_with_a_second_call_naming_the_task(self):
        self.script[:] = [
            {"tool_calls": [_call(1, "report_progress", text="looking up delivery")]},
            {"tool_calls": [_call(2, "ask_parent", question="Which postcode should I price delivery to?",
                                  timeout_s=20)]},
            {"text": "Delivery to M5V is $30.\n- the caller said M5V 2T6"},
        ]
        outcome, meta = await self.a2a_call(message="How much is delivery for dishwasher B?")
        self.assertTrue(outcome.payload["ok"], outcome.payload)
        self.assertEqual(meta["state"], "input-required")
        self.assertIn("Which postcode", meta["question"])
        (task,) = self.tasks()
        self.assertEqual(meta["task_id"], task.handle)

        answered, meta = await self.a2a_call(task_id=task.handle, message="M5V 2T6")
        self.assertTrue(answered.payload["ok"], answered.payload)
        self.assertEqual(meta["state"], "completed")
        self.assertIn("Delivery to M5V is $30", answered.payload["stdout_preview"])
        self.assertEqual(len(self.prompts), 2, "each call is its own decision")
        # The answer reached the member's next think, and no second crew
        # was started for it.
        self.assertIn("M5V 2T6", json.dumps(self.cognition.calls[-1].payload))
        self.assertEqual(len(self.tasks()), 1)
        self.assertEqual([m for m, _h in PlainTransport.log if m != "card"], ["message/stream", "message/stream"])

    async def test_without_streaming_the_task_is_polled_with_tasks_get(self):
        class _NoStream(PlainTransport):
            """The card of an agent that does not stream."""

            async def card(self, headers=None):
                card = await super().card(headers)
                return {**card, "capabilities": {**card["capabilities"], "streaming": False}}

        async def _slow(_message):
            await asyncio.sleep(0.4)
            return {"text": "Dishwasher B, $649.\n- reviews.md"}

        self.tool()._transport_factory = _NoStream  # noqa: SLF001
        self.server._send_wait_s = 0.05  # noqa: SLF001 -- `message/send` answers while the member works
        self.script[:] = [{"tool_calls": [_call(1, "report_progress", text="comparing")]}, _slow]
        outcome, meta = await self.a2a_call(message="Which is cheaper?")
        self.assertTrue(outcome.payload["ok"], outcome.payload)
        self.assertEqual(meta["state"], "completed")
        self.assertIn("Dishwasher B, $649", outcome.payload["stdout_preview"])
        methods = [m for m, _h in PlainTransport.log if m != "card"]
        self.assertEqual(methods[0], "message/send")
        self.assertIn("tasks/get", methods)
        self.assertNotIn("message/stream", methods)
        # Checking on a finished task later is `tasks/get` alone.
        PlainTransport.log = []
        checked, meta = await self.a2a_call(task_id=meta["task_id"])
        self.assertTrue(checked.payload["ok"], checked.payload)
        self.assertEqual(meta["state"], "completed")
        self.assertEqual([m for m, _h in PlainTransport.log if m != "card"], ["tasks/get"])

    async def test_tasks_cancel_stops_the_member_and_ends_the_callers_stream(self):
        self.script[:] = [{"tool_calls": [_call(1, "report_progress", text="started on it")]}, self.held()]
        first = asyncio.ensure_future(self.a2a_call(message="Price every dishwasher in town."))
        await self.until(lambda: any(t.state == "working" for t in self.tasks()), what="the member working")
        (task,) = self.tasks()

        cancelled, meta = await self.a2a_call(task_id=task.handle, cancel=True)
        self.assertTrue(cancelled.payload["ok"], cancelled.payload)
        self.assertEqual(meta["state"], "canceled")
        streamed, first_meta = await asyncio.wait_for(first, 20)
        self.assertFalse(streamed.payload["ok"])
        self.assertEqual(first_meta["state"], "canceled")
        self.assertIn("tasks/cancel", [m for m, _h in PlainTransport.log])
        # The callee's crew recorded the cancel for that member.
        cancels = [e.payload for e in await self.crew_events() if e.type == topics.CREW_CANCEL]
        self.assertTrue(any(c.get("handle") == task.handle for c in cancels), cancels)

    async def test_a_call_the_callers_person_declines_sends_nothing(self):
        self.answer = "no"
        outcome, _meta = await self.a2a_call(message="Which dishwasher is cheaper?")
        self.assertEqual(outcome.type, topics.ACTION_DENIED, outcome.payload)
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(PlainTransport.log, [], "not even the card was fetched")
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.cognition.calls, [])

    async def test_an_unpaired_caller_runs_nothing(self):
        for token in ("not-a-paired-token", "shared-legacy"):
            PlainTransport.log = []
            self.tool()._secrets = {"OTHER_SIM_TOKEN": token}  # noqa: SLF001
            self.tool()._cards.clear()  # noqa: SLF001
            outcome, _meta = await self.a2a_call(message="Which dishwasher is cheaper?")
            self.assertFalse(outcome.payload["ok"], token)
            self.assertEqual(outcome.payload["error_kind"], "unconfigured", outcome.payload)
            self.assertEqual([m for m, _h in PlainTransport.log], ["card", "card"], token)
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.cognition.calls, [])


class TestVersionNegotiation(_Interop):
    """A2A v1.0 "Versioning", both ways: the server names what it speaks
    and refuses a request in anything else; the client agrees a version
    from the card and refuses an agent that speaks none of its own."""

    async def test_the_card_says_its_version_in_both_spellings(self):
        status, reader, writer = await _http(client_a2a.card_url(self.url),
                                             headers={"Authorization": f"Bearer {self.device_token}"})
        card = json.loads(await reader.read())
        writer.close()
        self.assertEqual(status, 200)
        self.assertEqual(card["protocolVersion"], "0.3.0")
        self.assertEqual(card["supportedInterfaces"],
                         [{"url": self.url, "protocolBinding": "JSONRPC", "protocolVersion": "0.3"}])
        self.assertEqual(client_a2a.card_versions(card), ("0.3",))
        self.assertEqual(client_a2a.negotiate_version(card), "0.3")

    async def test_the_server_refuses_a_version_it_does_not_speak_before_anything_runs(self):
        message = {"role": "user", "messageId": "m1", "kind": "message", "parts": [{"kind": "text", "text": "hi"}]}
        refused = await self.raw("message/send", {"message": message}, version="1.0")
        self.assertEqual(refused["error"]["code"], server_a2a.VERSION_NOT_SUPPORTED)
        self.assertEqual(refused["error"]["data"], {"supported": ["0.3"]})
        self.assertEqual(self.tasks(), [])
        # No header is 0.3, and so is a patch version of it.
        for version in (None, "0.3", "0.3.0"):
            answered = await self.raw("tasks/get", {"id": "nope"}, version=version)
            self.assertEqual(answered["error"]["code"], server_a2a.TASK_NOT_FOUND, version)

    async def test_the_client_refuses_an_agent_that_speaks_only_a_version_it_does_not(self):
        class _V1Only(PlainTransport):
            """The card of an agent that speaks A2A v1.0 alone."""

            async def card(self, headers=None):
                card = dict(await super().card(headers))
                card.pop("protocolVersion")
                card["supportedInterfaces"] = [{"url": card["url"], "protocolBinding": "JSONRPC",
                                                "protocolVersion": "1.0"}]
                return card

        self.tool()._transport_factory = _V1Only  # noqa: SLF001
        outcome, _meta = await self.a2a_call(message="Which dishwasher is cheaper?")
        self.assertFalse(outcome.payload["ok"])
        self.assertEqual(outcome.payload["error_kind"], "refused")
        self.assertIn("speaks A2A 1.0", outcome.payload["error"])
        self.assertIn("speaks 0.3", outcome.payload["error"])
        self.assertEqual([m for m, _h in PlainTransport.log], ["card", "card"], "nothing but the card")
        self.assertEqual(self.tasks(), [])


@unittest.skipUnless(HAS_SDK, "a2a-sdk not installed: the SDK-client half of the interop proof is skipped")
class TestTheSdkClient(_Interop):  # pragma: no cover - the optional package
    """The same conversation through `SdkTransport`, the official client."""

    transport = None

    async def test_the_sdk_client_streams_and_answers_input_required(self):
        self.script[:] = [
            {"tool_calls": [_call(1, "report_progress", text="looking up delivery")]},
            {"tool_calls": [_call(2, "ask_parent", question="Which postcode?", timeout_s=20)]},
            {"text": "Delivery to M5V is $30.\n- the caller said M5V"},
        ]
        outcome, meta = await self.a2a_call(message="How much is delivery?")
        self.assertTrue(outcome.payload["ok"], outcome.payload)
        self.assertEqual(meta["state"], "input-required")
        answered, meta = await self.a2a_call(task_id=meta["task_id"], message="M5V")
        self.assertTrue(answered.payload["ok"], answered.payload)
        self.assertEqual(meta["state"], "completed")
        self.assertIn("$30", answered.payload["stdout_preview"])

    async def test_the_sdk_client_cancels(self):
        self.script[:] = [{"tool_calls": [_call(1, "report_progress", text="started")]}, self.held()]
        first = asyncio.ensure_future(self.a2a_call(message="Price everything."))
        await self.until(lambda: any(t.state == "working" for t in self.tasks()), what="the member working")
        (task,) = self.tasks()
        cancelled, meta = await self.a2a_call(task_id=task.handle, cancel=True)
        self.assertTrue(cancelled.payload["ok"], cancelled.payload)
        self.assertEqual(meta["state"], "canceled")
        streamed, _ = await asyncio.wait_for(first, 20)
        self.assertFalse(streamed.payload["ok"])


if __name__ == "__main__":
    unittest.main()


