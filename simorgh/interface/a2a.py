"""Sim serves its agents over A2A (stage 18 item 10).

A2A -- the protocol IBM's ACP merged into in August 2025 -- is JSON-RPC
2.0 over HTTP with an Agent Card at `/.well-known/agent-card.json`. This
module is the server half: the card, and the `message/send`,
`message/stream` (server-sent events), `tasks/get`, `tasks/cancel` and
`tasks/resubscribe` methods. Push notifications are left out; the card
says so and the methods answer `PushNotificationNotSupportedError`.

Four rules, each a decision rather than a default:

- **Off unless switched on** (`[interface.a2a] enabled = false`). An A2A
  endpoint lets a program somewhere else start an agent in this house.
- **A paired caller only.** The same listener and the same tokens as the
  phone (`devices.py`), and only a paired device holding `chat`: the
  legacy shared token is refused, because it names nobody and the crew's
  requester must be a person. No token, or the wrong one, is a 401 and
  nothing runs.
- **The requester is the caller.** An inbound message becomes a crew
  spawn whose requester is the device's person, on channel `a2a`, so
  Guardian weighs every tool call any member makes as that person's.
  The server never spawns anything itself: it asks Orchestration over
  the Bus (`crew.spawn`) and folds the crew's own `crew.message` and
  `crew.report` back into A2A status and artifact updates.
- **Only what `expose` names.** The card lists the agents in `[interface.a2a]
  expose` (default `["research"]`) with their skills from `agents/*.md`;
  a request for any other agent is refused by name.

The mapping is `contracts/a2a.py`'s (item 8), in A2A v0.3.0's spelling
-- the version the card declares and the `a2a-sdk` 0.3 line speaks:
crew status is the task state (`waiting` is `input-required`, `blocked`
is `rejected`), a `crew.message` is an A2A `Message`, a `Report` is the
task's `report` artifact. Nothing here maps a shape of its own.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from simorgh.contracts import topics
from simorgh.contracts.a2a import task_state, to_a2a_message, to_a2a_task

from .crewview import message_text

#: The A2A protocol version this server speaks.
PROTOCOL_VERSION = "0.3.0"
#: Where the agent bodies are (`agents/*.md`); read for the card's skills.
AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"
#: The JSON-RPC endpoint, next to the card on the same listener.
RPC_PATH = "/a2a"
CARD_PATH = "/.well-known/agent-card.json"
#: An A2A request is a message, not an upload.
MAX_BODY_BYTES = 64 * 1024
#: Tasks remembered for `tasks/get` after they end.
MAX_TASKS = 200
#: `message/send` and `message/stream` per window, across callers: each
#: may start a crew, and a crew spends. The same bound as `/api/chat`.
SPAWN_RATE: tuple[int, float] = (30, 60.0)

# JSON-RPC and A2A error codes (A2A specification section 8).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
PUSH_NOT_SUPPORTED = -32003
UNSUPPORTED_OPERATION = -32004
CONTENT_TYPE_NOT_SUPPORTED = -32005

#: The wire version this server speaks (`contracts/a2a.py` spells both).
WIRE = "0.3"
#: A report's status -> the member's, whose task state the caller sees.
_MEMBER_OF_REPORT: dict[str, str] = {
    "ok": "done", "partial": "done", "failed": "failed", "blocked": "blocked", "cancelled": "cancelled",
}
#: The `crew.message` kinds a member says about its own work; the rest
#: (`answer`, `steer`, `note`) are said to it.
_AGENT_KINDS = frozenset({"progress", "milestone", "question", "report"})
TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rejected"})
#: States a stream ends on: terminal, or waiting for the caller.
FINAL_STATES = TERMINAL_STATES | {"input-required", "auth-required"}


class RpcError(Exception):
    def __init__(self, code: int, message: str, data=None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def to_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


# ------------------------------------------------------------------ the card
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def agent_skill(name: str, agents_dir: Path = AGENTS_DIR) -> dict | None:
    """One exposed agent as an A2A skill, from its `agents/<name>.md`:
    the name, and the first paragraph of the body as what it does. None
    when there is no such agent -- then it is neither listed nor served."""
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", name or ""):
        return None
    path = agents_dir / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    front: dict = {}
    body = text
    if text.startswith("+++"):
        _, _, rest = text.partition("+++")
        head, sep, body = rest.partition("+++")
        if sep:
            try:
                front = tomllib.loads(head)
            except tomllib.TOMLDecodeError:
                front = {}
    body = _COMMENT.sub("", body).strip()
    first = next((" ".join(p.split()) for p in body.split("\n\n") if p.strip()), "")
    description = str(front.get("description") or first or f"Sim's {name} agent")
    if len(description) > 400:
        description = description[:399].rsplit(" ", 1)[0] + "…"
    return {"id": name, "name": name, "description": description,
            "tags": [name, "simorgh"], "inputModes": ["text/plain", "application/json"],
            "outputModes": ["text/plain", "application/json"]}


def agent_card(*, url: str, expose: tuple[str, ...], agents_dir: Path = AGENTS_DIR, version: str = "") -> dict:
    """The Agent Card: who this is, where to call it, how to authenticate,
    and the skills -- only the exposed agents that exist."""
    skills = [s for s in (agent_skill(n, agents_dir) for n in expose) if s is not None]
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": "Sim",
        "description": "A household's own agent. Each skill is one of its agents, run as the paired person who asks.",
        "url": url,
        "preferredTransport": "JSONRPC",
        "version": version or "1",
        "capabilities": {"streaming": True, "pushNotifications": False, "stateTransitionHistory": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer",
                                       "description": "a paired device's token (`pair` on Sim's console)"}},
        "security": [{"bearer": []}],
        "skills": skills,
    }


# ------------------------------------------------------------------ mapping
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def text_message(text: str, *, role: str = "agent", task_id: str = "", context_id: str = "",
                 data: dict | None = None) -> dict:
    parts: list[dict] = [{"kind": "text", "text": text}] if text else []
    if data:
        parts.append({"kind": "data", "data": data})
    message = {"kind": "message", "role": role, "messageId": uuid.uuid4().hex, "parts": parts}
    if task_id:
        message["taskId"] = task_id
    if context_id:
        message["contextId"] = context_id
    return message


def brief_of(message: dict) -> str:
    """An inbound A2A message as the brief a member works from: its text
    parts, then any data parts as compact JSON. A file part is refused --
    a ref into somebody else's storage is not something to fetch on a
    stranger's say-so, and a member cannot read it anyway."""
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise RpcError(INVALID_PARAMS, "message.parts must be a non-empty list")
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            raise RpcError(INVALID_PARAMS, "each part must be an object")
        kind = part.get("kind") or ("text" if "text" in part else "")
        if kind == "text":
            texts.append(str(part.get("text") or ""))
        elif kind == "data":
            texts.append(json.dumps(part.get("data"), separators=(",", ":"), default=str))
        elif kind == "file":
            raise RpcError(CONTENT_TYPE_NOT_SUPPORTED, "file parts are not accepted; send text or data")
        else:
            raise RpcError(INVALID_PARAMS, f"unknown part kind {kind!r}")
    brief = "\n".join(t for t in texts if t.strip()).strip()
    if not brief:
        raise RpcError(INVALID_PARAMS, "the message has no text")
    return brief


def report_artifact(*, handle: str, crew_id: str, agent: str, report: dict) -> dict:
    """A crew `Report` as the task's `report` artifact
    (`contracts.a2a.to_a2a_task`): the summary as text, the rest --
    findings, steps, cost -- as data, each ref as a file part."""
    member = {"handle": handle, "crew_id": crew_id, "agent": agent,
              "status": _MEMBER_OF_REPORT.get(str(report.get("status") or "ok"), "done")}
    return to_a2a_task(member, report, version=WIRE)["artifacts"][0]


def crew_message(payload: dict, *, task_id: str, context_id: str) -> dict:
    """A `crew.message` payload as an A2A `Message`
    (`contracts.a2a.to_a2a_message`), or a plain text message when the
    payload is not one the mapping can read."""
    try:
        return to_a2a_message(payload, version=WIRE)
    except (KeyError, TypeError, ValueError):
        return text_message(message_text(payload.get("body")), task_id=task_id, context_id=context_id)


# ------------------------------------------------------------------ tasks
@dataclass
class InboundTask:
    """One A2A task: a crew member started for a remote caller. Its A2A
    id is the member's handle; its context is the crew."""

    handle: str
    crew_id: str
    agent: str
    caller_id: str
    requester: str
    state: str = "submitted"
    status_message: dict | None = None
    history: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    updated: float = 0.0
    last_question_seq: int | None = None
    listeners: list[asyncio.Queue] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def status(self) -> dict:
        out = {"state": self.state, "timestamp": _iso(self.updated)}
        if self.status_message is not None:
            out["message"] = self.status_message
        return out

    def to_a2a(self, *, history_length: int | None = None) -> dict:
        history = self.history if history_length is None else (self.history[-history_length:] if history_length else [])
        return {"kind": "task", "id": self.handle, "contextId": self.crew_id, "status": self.status(),
                "artifacts": list(self.artifacts), "history": list(history),
                "metadata": {"agent": self.agent}}

    def push(self, event: dict) -> None:
        for queue in list(self.listeners):
            queue.put_nowait(event)
        self.changed.set()


class A2AServer:
    """The A2A methods, over a Bus. `HttpApi.serve_a2a` gives it the
    listener and decides who the caller is; this decides what they get."""

    def __init__(self, bus, *, expose: tuple[str, ...] = ("research",), agents_dir: Path = AGENTS_DIR,
                 clock: Callable[[], float] | None = None, spawn_timeout_s: float = 15.0,
                 send_wait_s: float = 120.0, stream_idle_s: float = 900.0, logger=None) -> None:
        self._bus = bus
        self._expose = tuple(dict.fromkeys(str(a).strip() for a in expose if str(a).strip()))
        self._agents_dir = agents_dir
        self._clock = clock or time.time
        self._spawn_timeout_s = spawn_timeout_s
        self._send_wait_s = send_wait_s
        self._stream_idle_s = stream_idle_s
        self._logger = logger
        self._tasks: dict[str, InboundTask] = {}
        #: Crew events for a handle not registered yet: a fast member can
        #: say something before the spawn's reply reaches this server.
        self._early: list[tuple[str, dict]] = []
        self._subs: list = []

    # -- lifecycle ----------------------------------------------------------------------
    async def start(self) -> None:
        self._subs = [
            await self._bus.subscribe(topics.CREW_MESSAGE, self._on_crew_message),
            await self._bus.subscribe(topics.CREW_REPORT, self._on_crew_report),
            await self._bus.subscribe(topics.CREW_CANCEL, self._on_crew_cancel),
        ]

    async def stop(self) -> None:
        for sub in self._subs:
            try:
                await sub.unsubscribe()
            except Exception:  # noqa: BLE001 -- shutting down; nothing to tell
                pass
        self._subs = []
        for task in self._tasks.values():
            task.push({"_close": True})

    @property
    def exposed(self) -> tuple[str, ...]:
        """The exposed agents that exist (`agents/<name>.md`)."""
        return tuple(n for n in self._expose if agent_skill(n, self._agents_dir) is not None)

    def card(self, url: str) -> dict:
        return agent_card(url=url, expose=self._expose, agents_dir=self._agents_dir)

    # -- the bus side -------------------------------------------------------------------
    def _now(self) -> float:
        return float(self._clock())

    async def _on_crew_message(self, message) -> None:
        self._fold("message", dict(message.payload))

    async def _on_crew_report(self, message) -> None:
        self._fold("report", dict(message.payload))

    async def _on_crew_cancel(self, message) -> None:
        self._fold("cancel", dict(message.payload))

    def _fold(self, kind: str, payload: dict) -> None:
        handle = str(payload.get("from") if kind == "message" else payload.get("handle") or "")
        task = self._tasks.get(handle)
        if task is None:
            if handle:
                self._early.append((kind, payload))
                del self._early[:-256]
            return
        if task.state in TERMINAL_STATES:
            return
        task.updated = self._now()
        if kind == "message":
            what = str(payload.get("kind") or "")
            # Only what the member says about its own work (A2A role
            # `agent`, `contracts/a2a.py`). A `note` is said TO a member:
            # the caller's own follow-up comes back on this topic, and when
            # the crew's root is the member itself (`from` == handle) it
            # would read back as the member speaking.
            if what not in _AGENT_KINDS:
                return
            said = crew_message(payload, task_id=task.handle, context_id=task.crew_id)
            task.history.append(said)
            del task.history[:-50]
            task.state = "input-required" if what == "question" else "working"
            if what == "question" and isinstance(payload.get("seq"), int):
                task.last_question_seq = payload["seq"]
            task.status_message = said
            task.push(self._status_event(task))
            return
        if kind == "report":
            report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
            artifact = report_artifact(handle=task.handle, crew_id=task.crew_id, agent=task.agent, report=report)
            task.artifacts = [artifact]
            task.state = task_state(_MEMBER_OF_REPORT.get(str(report.get("status") or "ok"), "done"), WIRE)
            summary = str(report.get("summary") or "")
            task.status_message = text_message(summary, task_id=task.handle, context_id=task.crew_id) if summary else None
            task.push({"kind": "artifact-update", "taskId": task.handle, "contextId": task.crew_id,
                       "artifact": artifact, "lastChunk": True})
            task.push(self._status_event(task))
            return
        if kind == "cancel":
            task.state = "canceled"
            reason = str(payload.get("reason") or "")
            task.status_message = text_message(reason, task_id=task.handle, context_id=task.crew_id) if reason else None
            task.push(self._status_event(task))

    @staticmethod
    def _status_event(task: InboundTask) -> dict:
        return {"kind": "status-update", "taskId": task.handle, "contextId": task.crew_id,
                "status": task.status(), "final": task.state in FINAL_STATES}

    def _register(self, task: InboundTask) -> None:
        self._tasks[task.handle] = task
        while len(self._tasks) > MAX_TASKS:
            # The oldest finished task goes first; an open one only when
            # every remembered task is open.
            victim = next((h for h, t in self._tasks.items() if t.state in TERMINAL_STATES), next(iter(self._tasks)))
            self._tasks.pop(victim)
        early, self._early = self._early, []
        for kind, payload in early:
            handle = str(payload.get("from") if kind == "message" else payload.get("handle") or "")
            if handle == task.handle:
                self._fold(kind, payload)
            else:
                self._early.append((kind, payload))

    # -- the methods --------------------------------------------------------------------
    def _caller_id(self, caller) -> str:
        return str(getattr(caller, "id", "") or getattr(caller, "name", "") or "")

    def _agent_for(self, params: dict, message: dict) -> str:
        meta = {**(message.get("metadata") or {}), **(params.get("metadata") or {})}
        wanted = str(meta.get("agent") or meta.get("skill") or meta.get("skillId") or "").strip()
        exposed = self.exposed
        if not exposed:
            raise RpcError(UNSUPPORTED_OPERATION, "no agent is exposed here ([interface.a2a] expose)")
        if not wanted:
            return exposed[0]
        if wanted not in exposed:
            raise RpcError(INVALID_PARAMS, f"agent {wanted!r} is not served here; the card lists the ones that are",
                           {"exposed": list(exposed)})
        return wanted

    def _owned(self, task_id: str, caller) -> InboundTask:
        task = self._tasks.get(str(task_id or ""))
        # Another caller's task is not found, rather than forbidden: its
        # existence is not this caller's business.
        if task is None or task.caller_id != self._caller_id(caller):
            raise RpcError(TASK_NOT_FOUND, f"no task {task_id!r}")
        return task

    async def _spawn(self, *, agent: str, brief: str, caller, context_id: str = "") -> InboundTask:
        requester = str(getattr(caller, "person", "") or "")
        payload = {"agent": agent, "brief": brief, "requester": requester, "requester_channel": "a2a",
                   "device": str(getattr(caller, "name", "") or ""), "report": "progress", "background": True}
        if context_id:
            payload["context_id"] = context_id
        try:
            reply = await self._bus.request(self._bus.new(topics.CREW_SPAWN, payload), timeout=self._spawn_timeout_s)
        except TimeoutError as exc:
            raise RpcError(INTERNAL_ERROR, "nothing answered the spawn; is orchestration running?") from exc
        p = dict(getattr(reply, "payload", {}) or {})
        if p.get("ok") is False or not p.get("handle"):
            err = p.get("error") or {}
            raise RpcError(INTERNAL_ERROR, f"the crew was not started: {err.get('code', 'refused')} "
                                           f"-- {err.get('detail', '')}".rstrip(" -"))
        task = InboundTask(handle=str(p["handle"]), crew_id=str(p.get("crew_id") or p["handle"]), agent=agent,
                           caller_id=self._caller_id(caller), requester=requester, updated=self._now())
        task.history.append(text_message(brief, role="user", task_id=task.handle, context_id=task.crew_id))
        return task

    async def _to_member(self, task: InboundTask, brief: str) -> None:
        """A follow-up on a task that is still open: the answer to its
        question, or a note it reads at its next think."""
        kind = "answer" if task.state == "input-required" else "note"
        # From the crew's root, which is who the remote caller stands in
        # for. `seq` 0: Orchestration numbers the crew's messages.
        payload = {"crew_id": task.crew_id, "from": task.crew_id, "to": task.handle, "kind": kind,
                   "body": brief, "refs": [], "seq": 0}
        if kind == "answer" and task.last_question_seq is not None:
            payload["reply_to"] = task.last_question_seq
        await self._bus.publish(self._bus.new(topics.CREW_MESSAGE, payload))
        task.history.append(text_message(brief, role="user", task_id=task.handle, context_id=task.crew_id))
        if kind == "answer":
            task.state, task.status_message, task.updated = "working", None, self._now()
            task.changed.set()

    async def _begin(self, params: dict, caller, *, listener: asyncio.Queue | None = None) -> InboundTask:
        """`message/send` and `message/stream` share this: a new task, or a
        follow-up to one of the caller's own."""
        if not isinstance(params, dict) or not isinstance(params.get("message"), dict):
            raise RpcError(INVALID_PARAMS, "params.message is required")
        message = params["message"]
        if str(message.get("role") or "user") != "user":
            raise RpcError(INVALID_PARAMS, "message.role must be user")
        brief = brief_of(message)
        if message.get("taskId"):
            task = self._owned(message["taskId"], caller)
            if task.state in TERMINAL_STATES:
                raise RpcError(INVALID_PARAMS, f"task {task.handle} is already {task.state}; start a new one")
            if listener is not None:
                task.listeners.append(listener)
            await self._to_member(task, brief)
            return task
        agent = self._agent_for(params, message)
        task = await self._spawn(agent=agent, brief=brief, caller=caller, context_id=str(message.get("contextId") or ""))
        if listener is not None:
            task.listeners.append(listener)
        self._register(task)
        return task

    async def _send(self, params: dict, caller) -> dict:
        task = await self._begin(params, caller)
        blocking = (params.get("configuration") or {}).get("blocking", True) is not False
        if blocking:
            deadline = time.monotonic() + self._send_wait_s
            while task.state not in FINAL_STATES:
                task.changed.clear()
                left = deadline - time.monotonic()
                if left <= 0:
                    break  # the caller polls `tasks/get` from here
                try:
                    await asyncio.wait_for(task.changed.wait(), timeout=left)
                except asyncio.TimeoutError:
                    break
        history_length = (params.get("configuration") or {}).get("historyLength")
        return task.to_a2a(history_length=history_length if isinstance(history_length, int) else None)

    async def _get(self, params: dict, caller) -> dict:
        if not isinstance(params, dict) or not params.get("id"):
            raise RpcError(INVALID_PARAMS, "params.id is required")
        task = self._owned(params["id"], caller)
        length = params.get("historyLength")
        return task.to_a2a(history_length=length if isinstance(length, int) else None)

    async def _cancel(self, params: dict, caller) -> dict:
        if not isinstance(params, dict) or not params.get("id"):
            raise RpcError(INVALID_PARAMS, "params.id is required")
        task = self._owned(params["id"], caller)
        if task.state in TERMINAL_STATES:
            raise RpcError(TASK_NOT_CANCELABLE, f"task {task.handle} is already {task.state}")
        who = str(getattr(caller, "name", "") or "the caller")
        await self._bus.publish(self._bus.new(topics.CREW_CANCEL, {
            "crew_id": task.crew_id, "handle": task.handle, "reason": f"cancelled over A2A by {who}",
            "cascade": True,
        }))
        # Orchestration stops it after the current step; to the caller the
        # task is cancelled now, and nothing it says after this is relayed.
        task.state, task.updated = "canceled", self._now()
        task.status_message = None
        task.push(self._status_event(task))
        return task.to_a2a()

    async def call(self, request: dict, caller) -> dict:
        """One non-streaming JSON-RPC request -> its response object."""
        rid = request.get("id") if isinstance(request, dict) else None
        try:
            method, params = self._check(request)
            if method == "message/send":
                result = await self._send(params, caller)
            elif method == "tasks/get":
                result = await self._get(params, caller)
            elif method == "tasks/cancel":
                result = await self._cancel(params, caller)
            elif method.startswith("tasks/pushNotificationConfig/"):
                raise RpcError(PUSH_NOT_SUPPORTED, "push notifications are not supported")
            elif method in ("message/stream", "tasks/resubscribe"):
                raise RpcError(INVALID_REQUEST, f"{method} answers as a stream")
            else:
                raise RpcError(METHOD_NOT_FOUND, f"no method {method!r}")
        except RpcError as err:
            return {"jsonrpc": "2.0", "id": rid, "error": err.to_dict()}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @staticmethod
    def _check(request) -> tuple[str, dict]:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            raise RpcError(INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        params = request.get("params")
        return request["method"], params if isinstance(params, dict) else {}

    async def stream(self, request: dict, caller, emit: Callable[[dict], "asyncio.Future"]) -> None:
        """`message/stream` and `tasks/resubscribe`: every event as one
        JSON-RPC response, until the task ends or waits for the caller.
        `emit` writes one response; an error before the first event is
        one error response and nothing else."""
        rid = request.get("id") if isinstance(request, dict) else None
        queue: asyncio.Queue = asyncio.Queue()
        task: InboundTask | None = None
        try:
            method, params = self._check(request)
            if method == "message/stream":
                task = await self._begin(params, caller, listener=queue)
            elif method == "tasks/resubscribe":
                if not params.get("id"):
                    raise RpcError(INVALID_PARAMS, "params.id is required")
                task = self._owned(params["id"], caller)
                task.listeners.append(queue)
            else:
                raise RpcError(INVALID_REQUEST, f"{method} does not stream")
        except RpcError as err:
            await emit({"jsonrpc": "2.0", "id": rid, "error": err.to_dict()})
            return
        try:
            await emit({"jsonrpc": "2.0", "id": rid, "result": task.to_a2a()})
            if task.state in FINAL_STATES:
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self._stream_idle_s)
                except asyncio.TimeoutError:
                    return  # the caller resubscribes or polls `tasks/get`
                if event.get("_close"):
                    return
                await emit({"jsonrpc": "2.0", "id": rid, "result": event})
                if event.get("kind") == "status-update" and event.get("final"):
                    return
        finally:
            if queue in task.listeners:
                task.listeners.remove(queue)


__all__ = [
    "A2AServer", "AGENTS_DIR", "CARD_PATH", "InboundTask", "MAX_BODY_BYTES", "PROTOCOL_VERSION", "RPC_PATH",
    "SPAWN_RATE",
    "RpcError", "WIRE", "agent_card", "agent_skill", "brief_of", "crew_message", "report_artifact",
    "text_message",
]
