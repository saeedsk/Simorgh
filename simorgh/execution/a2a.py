"""A2A client: Sim calls a remote agent (stage 18 item 9, Execution half).

A remote agent is reached through one tool, `a2a_call`, so every call is
proposed to Guardian like any other tool call. It is `irreversible`: the
message carries household data out of the house and cannot be unsent.

Which agents exist is a person's decision, never Sim's. They are listed
in config, one table per agent:

    [crew.a2a_agents.research_desk]        # the Kernel copies this table
    url = "https://agents.example/a2a"     # into Execution's `a2a_agents`;
    auth_secret = "RESEARCH_DESK_TOKEN"    # `[execution.a2a_agents.<name>]`
    allowed_data = ["public", "calendar"]  # is read the same way

`url` is the agent's JSON-RPC endpoint; its Agent Card is read from the
same origin's `/.well-known/agent-card.json`. `auth_secret` is a key
NAME in `secrets.toml`, read at call time. `allowed_data` is the data
classes this agent may receive; a call names the classes its message
carries (`data`, default `public`) and is refused before anything is
sent when one is not allowed. Sim may propose an agent with
`propose_a2a_agent`, which only records the proposal on `a2a:proposals`
for a person to approve, the way `propose_mcp_server` works.

The protocol is spoken by the official `a2a-sdk` package (imported under
`try/except ImportError`, as the device SDKs are). Without it the call
reports `unconfigured` with "needs `pip install a2a-sdk`" and sends
nothing. Everything above the transport works on the A2A wire shapes as
plain dicts (a Task, a Message, a status or artifact update), so a test
can drive the tool with a transport of its own against a fake server.

One call:
- fetch the Agent Card (cached per agent for `CARD_TTL_S`); a card behind
  a bearer (another Sim's is: only a paired device may read it) is asked
  for again once with the configured secret -- only when the 401/403's
  `WWW-Authenticate` challenge names `Bearer`, or the agent's table says
  `auth_scheme = "bearer"`; any other card answers `unconfigured` naming
  the scheme it asked for, and the secret is never sent to it;
- agree the A2A version: the card's JSON-RPC interfaces name what it
  speaks, this client speaks `CLIENT_VERSIONS` and says which in the
  `A2A-Version` header of every request; a card offering none of them
  is refused by name, before anything is sent;
- refuse, by scheme name, a security requirement Sim cannot meet
  (anything but HTTP bearer or a header API key);
- `message/stream` when the card says it streams, each status update
  handed to the progress callback (the default writes it to `a2a:calls`);
- otherwise, or when a stream breaks after the task exists, `message/send`
  then `tasks/get` every `poll_interval_s`, at most `max_wait_s`;
- `input-required` comes back as an ok result carrying the remote
  agent's question and the task id, to answer with a second call that
  names `task_id`; `cancel: true` with a `task_id` sends `tasks/cancel`.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlparse

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import ToolContext, ToolResult, ToolUnconfigured

A2A_PROPOSALS_STREAM = "a2a:proposals"
A2A_CALLS_STREAM = "a2a:calls"
SDK_MISSING = "needs `pip install a2a-sdk`"
CARD_PATH = "/.well-known/agent-card.json"
CARD_TTL_S = 300.0
#: The A2A versions this client speaks, newest first: the v0.3 wire the
#: `a2a-sdk` 0.3 line speaks and `_Progress` folds (`kind` discriminators,
#: `input-required`). v1.0's shapes (`TASK_STATE_*`, `statusUpdate`
#: wrappers, `SendMessage`) are not spoken yet.
CLIENT_VERSIONS = ("0.3",)
#: The request header that names the version (A2A v1.0 "Versioning"). A
#: server that sees none assumes 0.3, so a 0.3 server that ignores it
#: still understands the request.
VERSION_HEADER = "A2A-Version"

TERMINAL_STATES = frozenset({"completed", "canceled", "failed", "rejected"})
INTERRUPTED_STATES = frozenset({"input-required", "auth-required"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SECRET_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DATA_RE = re.compile(r"^(\*|[a-z][a-z0-9_-]*)$")


@dataclass(frozen=True)
class A2aAgentConfig:
    name: str
    url: str
    # A key name in secrets.toml, never the value. Empty: no credential.
    auth_secret: str = ""
    # The scheme the agent's card itself sits behind, when its 401 does not
    # say (no `WWW-Authenticate`). Only `bearer` sends the secret for it.
    auth_scheme: str = ""
    # Data classes this agent may receive. `*` allows any.
    allowed_data: tuple[str, ...] = ("public",)
    timeout_s: float = 30.0
    poll_interval_s: float = 2.0
    max_wait_s: float = 120.0

    @classmethod
    def from_mapping(cls, name: str, data: Mapping[str, Any]) -> "A2aAgentConfig":
        allowed = data.get("allowed_data", ("public",))
        if isinstance(allowed, str):
            allowed = [allowed]
        return cls(
            name=str(name), url=str(data["url"]), auth_secret=str(data.get("auth_secret", "") or ""),
            auth_scheme=str(data.get("auth_scheme", "") or "").strip().lower(),
            allowed_data=tuple(str(item).strip().lower() for item in allowed if str(item).strip()),
            timeout_s=float(data.get("timeout_s", 30.0)),
            poll_interval_s=float(data.get("poll_interval_s", 2.0)),
            max_wait_s=float(data.get("max_wait_s", 120.0)),
        )


def a2a_agents_from_mapping(value: Any) -> tuple[A2aAgentConfig, ...]:
    """`{name: {url, ...}}` (the shape a `[... .a2a_agents.<name>]` table
    loads as) or a list of tables that each carry `name`."""
    if not value:
        return ()
    if isinstance(value, Mapping):
        items = [(name, row) for name, row in value.items()]
    else:
        items = [(row.name, row) if isinstance(row, A2aAgentConfig) else (row["name"], row) for row in value]
    agents = []
    for name, row in items:
        agents.append(row if isinstance(row, A2aAgentConfig) else A2aAgentConfig.from_mapping(name, row))
    return tuple(agents)


class A2aError(Exception):
    """A refusal or a remote failure, with the `ToolResult.error_kind` it
    becomes. Never raised past `A2aCallTool.run`."""

    def __init__(self, message: str, *, error_kind: str = "failed") -> None:
        super().__init__(message)
        self.error_kind = error_kind


class CardUnauthorized(A2aError):
    """The Agent Card answered 401 or 403: it is behind the agent's own
    credential. A transport raises it from `card()` with the response's
    `WWW-Authenticate` header as `challenge` ("" when it sent none); the
    tool asks once more with the configured secret only when that names
    `Bearer` or the agent's table declares `auth_scheme = "bearer"`."""

    def __init__(self, message: str = "the agent card needs a credential", *, challenge: str = "") -> None:
        super().__init__(message, error_kind="unconfigured")
        self.challenge = str(challenge or "").strip()

    @property
    def scheme(self) -> str:
        """The challenge's auth scheme, lower case (`bearer`, `basic`, ...)."""
        return challenge_scheme(self.challenge)


def challenge_scheme(header: str) -> str:
    """A `WWW-Authenticate` value's first auth scheme, lower case: `Bearer
    realm="x"` is `bearer`; nothing is ""."""
    head = str(header or "").strip().split(",", 1)[0].split()
    return head[0].lower() if head else ""


# -- the Agent Card ---------------------------------------------------------

def auth_headers(card: Mapping[str, Any], *, secret_name: str, secret: str) -> dict[str, str]:
    """The request headers that meet the card's security requirement.

    `security` is a list of alternatives, each a set of scheme names that
    must all be met. Sim can meet HTTP bearer and an API key in a header,
    both from the one configured secret. A card whose every alternative
    needs something else (OAuth2, OpenID Connect, mutual TLS, basic auth,
    a key in a query or cookie) is refused naming that scheme."""
    schemes = card.get("securitySchemes") or {}
    requirements = card.get("security") or []
    if not requirements:
        return {}
    unmet: list[str] = []
    for alternative in requirements:
        headers: dict[str, str] = {}
        ok = True
        for scheme_name in (alternative or {}):
            scheme = schemes.get(scheme_name) or {}
            kind = str(scheme.get("type", "")).strip()
            if kind == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
                headers["Authorization"] = f"Bearer {secret}"
            elif kind == "apiKey" and str(scheme.get("in", "")).lower() == "header" and scheme.get("name"):
                headers[str(scheme["name"])] = secret
            else:
                detail = kind or "unknown"
                if kind == "http":
                    detail = f"http {scheme.get('scheme', '')}".strip()
                elif kind == "apiKey":
                    detail = f"apiKey in {scheme.get('in', '?')}"
                unmet.append(f"{scheme_name!r} ({detail})")
                ok = False
                break
        if ok:
            if headers and not secret:
                raise A2aError(
                    f"the agent's card asks for a credential and no secret is set: put "
                    f"{secret_name or '<a key name>'} in secrets.toml and name it as this agent's auth_secret",
                    error_kind="unconfigured")
            return headers
    raise A2aError("the agent's card asks for a security scheme Sim cannot meet: " + ", ".join(unmet),
                   error_kind="refused")


def check_card(card: Mapping[str, Any]) -> None:
    """A card that offers no JSON-RPC interface is refused by name: the
    client speaks JSON-RPC only."""
    preferred = str(card.get("preferredTransport") or "JSONRPC").upper()
    if preferred == "JSONRPC":
        return
    others = {str((row or {}).get("transport", "")).upper() for row in card.get("additionalInterfaces") or ()}
    if "JSONRPC" not in others:
        raise A2aError(f"the agent offers transport {preferred!r} only; Sim speaks JSON-RPC", error_kind="refused")


def _major_minor(version: Any) -> str:
    """`0.3.0` -> `0.3`; A2A versions negotiate on major.minor."""
    parts = str(version or "").strip().split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]) else ""


def card_versions(card: Mapping[str, Any]) -> tuple[str, ...]:
    """The A2A versions a card offers over JSON-RPC, as major.minor.

    A v1.0 card lists `supportedInterfaces[]{protocolBinding,
    protocolVersion}`; a v0.3 card has one top-level `protocolVersion`
    for its `url`. A card that names no version at all is 0.3, the
    version the spec assumes when none is said."""
    offered: list[str] = []
    for row in card.get("supportedInterfaces") or ():
        if not isinstance(row, Mapping):
            continue
        binding = str(row.get("protocolBinding") or row.get("transport") or "").upper()
        version = _major_minor(row.get("protocolVersion"))
        if binding == "JSONRPC" and version:
            offered.append(version)
    top = _major_minor(card.get("protocolVersion"))
    if top:
        offered.append(top)
    if not offered and not card.get("supportedInterfaces"):
        offered.append("0.3")
    return tuple(dict.fromkeys(offered))


def negotiate_version(card: Mapping[str, Any]) -> str:
    """The newest version both sides speak, or a refusal naming both
    lists: a request in a version the agent does not speak would be
    misread, and the household's data would already have left."""
    offered = card_versions(card)
    for version in CLIENT_VERSIONS:
        if version in offered:
            return version
    raise A2aError(f"the agent speaks A2A {', '.join(offered) or 'no version over JSON-RPC'}; Sim's client "
                   f"speaks {', '.join(CLIENT_VERSIONS)}", error_kind="refused")


def card_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{CARD_PATH}"


# -- the wire shapes --------------------------------------------------------

def text_of(parts: Any) -> str:
    out: list[str] = []
    for part in parts or ():
        if not isinstance(part, Mapping):
            continue
        kind = part.get("kind") or part.get("type")
        if kind == "text":
            out.append(str(part.get("text", "")))
        elif kind == "data":
            out.append(json.dumps(part.get("data"), ensure_ascii=False, sort_keys=True))
        elif kind == "file":
            file = part.get("file") or {}
            out.append(f"[file {file.get('name') or file.get('uri') or ''}]".strip())
    return "\n".join(item for item in out if item)


def user_message(text: str, *, task_id: str = "", context_id: str = "") -> dict:
    message = {"kind": "message", "role": "user", "messageId": uuid.uuid4().hex,
               "parts": [{"kind": "text", "text": text}]}
    if task_id:
        message["taskId"] = task_id
    if context_id:
        message["contextId"] = context_id
    return message


class _Progress:
    """What one call has learnt so far, folded from Tasks, Messages and
    status/artifact updates in the order they arrive."""

    def __init__(self) -> None:
        self.task_id = ""
        self.context_id = ""
        self.state = ""
        self.status_text = ""
        self.artifacts: dict[str, str] = {}
        self.reply = ""  # a direct Message answer, no task
        # The stream used up `max_wait_s`: no polling after it.
        self.out_of_time = False

    def fold(self, obj: Mapping[str, Any]) -> None:
        kind = obj.get("kind")
        if kind == "message":
            # A Message as the result is the agent's whole answer.
            self.reply = text_of(obj.get("parts"))
            self._ids({"taskId": obj.get("taskId"), "contextId": obj.get("contextId")})
            self.state = "completed"
            return
        if kind == "artifact-update":
            self._ids(obj)
            artifact = obj.get("artifact") or {}
            key = str(artifact.get("artifactId") or len(self.artifacts))
            text = text_of(artifact.get("parts"))
            self.artifacts[key] = (self.artifacts.get(key, "") + text) if obj.get("append") else text
            return
        if kind == "status-update" or kind == "task" or "status" in obj:
            self._ids(obj)
            status = obj.get("status") or {}
            self.state = str(status.get("state") or self.state)
            message = status.get("message")
            if isinstance(message, Mapping):
                self.status_text = text_of(message.get("parts"))
            for artifact in obj.get("artifacts") or ():
                key = str(artifact.get("artifactId") or len(self.artifacts))
                self.artifacts[key] = text_of(artifact.get("parts"))

    def _ids(self, obj: Mapping[str, Any]) -> None:
        self.task_id = str(obj.get("taskId") or obj.get("id") or self.task_id)
        self.context_id = str(obj.get("contextId") or self.context_id)

    @property
    def done(self) -> bool:
        return self.state in TERMINAL_STATES or self.state in INTERRUPTED_STATES

    def answer(self) -> str:
        if self.reply:
            return self.reply
        artifacts = "\n".join(text for text in self.artifacts.values() if text)
        return artifacts or self.status_text


# -- the SDK transport ------------------------------------------------------

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True, by_alias=True)
    return obj


def _unwrap(response: Any) -> dict:
    data = _dump(response)
    if isinstance(data, Mapping) and "root" in data and len(data) == 1:
        data = data["root"]
    if not isinstance(data, Mapping):
        raise A2aError(f"unreadable reply: {data!r}"[:300])
    if data.get("error"):
        error = data["error"]
        raise A2aError(f"remote error {error.get('code', '?')}: {error.get('message', '')}".strip())
    return dict(data.get("result", data))


class SdkTransport:
    """The official `a2a-sdk` client behind the four calls the tool needs,
    each returning the A2A JSON shape as a dict."""

    def __init__(self, agent: A2aAgentConfig) -> None:
        try:
            import httpx
            from a2a import types as a2a_types
            from a2a.client import A2ACardResolver, A2AClient
        except ImportError as exc:
            raise ToolUnconfigured(SDK_MISSING) from exc
        self._agent = agent
        self._httpx = httpx
        self._types = a2a_types
        self._resolver_cls = A2ACardResolver
        self._client_cls = A2AClient
        self._http = None
        self._client = None

    async def card(self, headers: Mapping[str, str] | None = None) -> dict:
        parsed = urlparse(self._agent.url)
        async with self._httpx.AsyncClient(timeout=self._agent.timeout_s) as http:
            resolver = self._resolver_cls(httpx_client=http, base_url=f"{parsed.scheme}://{parsed.netloc}")
            try:
                if headers:
                    card = await resolver.get_agent_card(http_kwargs={"headers": dict(headers)})
                else:
                    card = await resolver.get_agent_card()
            except Exception as exc:
                # The SDK's `A2AClientHTTPError` carries the status; the
                # httpx error it wraps carries the response's challenge.
                if getattr(exc, "status_code", None) in (401, 403):
                    raise CardUnauthorized(f"the agent card answered {exc.status_code}",
                                           challenge=_challenge_of(exc)) from exc
                raise
            return dict(_dump(card))

    async def connect(self, headers: Mapping[str, str]) -> None:
        self._http = self._httpx.AsyncClient(timeout=self._agent.timeout_s, headers=dict(headers))
        # The configured URL, not the card's own `url`: a card must not be
        # able to send the household's data somewhere a person did not name.
        self._client = self._client_cls(httpx_client=self._http, url=self._agent.url)

    def _send_params(self, message: dict):
        return self._types.MessageSendParams.model_validate({"message": message})

    async def send(self, message: dict) -> dict:
        request = self._types.SendMessageRequest(id=uuid.uuid4().hex, params=self._send_params(message))
        return _unwrap(await self._client.send_message(request))

    async def stream(self, message: dict):
        request = self._types.SendStreamingMessageRequest(id=uuid.uuid4().hex, params=self._send_params(message))
        async for event in self._client.send_message_streaming(request):
            yield _unwrap(event)

    async def get_task(self, task_id: str) -> dict:
        request = self._types.GetTaskRequest(id=uuid.uuid4().hex, params=self._types.TaskQueryParams(id=task_id))
        return _unwrap(await self._client.get_task(request))

    async def cancel(self, task_id: str) -> dict:
        request = self._types.CancelTaskRequest(id=uuid.uuid4().hex, params=self._types.TaskIdParams(id=task_id))
        return _unwrap(await self._client.cancel_task(request))

    async def close(self) -> None:
        if self._http is not None:
            with contextlib.suppress(Exception):
                await self._http.aclose()


def _challenge_of(exc: BaseException) -> str:
    """The `WWW-Authenticate` header of the HTTP response behind an SDK
    error, from the error or the httpx error it was raised from; ""."""
    seen = 0
    while exc is not None and seen < 4:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            with contextlib.suppress(Exception):
                return str(headers.get("www-authenticate") or "")
        exc, seen = exc.__cause__ or exc.__context__, seen + 1
    return ""


def sdk_transport(agent: A2aAgentConfig) -> SdkTransport:
    return SdkTransport(agent)


# -- the tools --------------------------------------------------------------

ProgressFn = Callable[[ToolContext, dict], Awaitable[None]]


def _data_classes(value: Any) -> tuple[str, ...]:
    """The classes a call says its message carries. Nothing said, or only
    blanks, is `public`: an empty tuple would pass every agent's
    `allowed_data` check, one that does not allow `public` included."""
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    elif value is None:
        items = []
    else:
        items = [value]
    classes = tuple(str(item).strip().lower() for item in items if str(item).strip())
    return classes or ("public",)


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true", "yes", "on")


class A2aCallTool:
    name = "a2a_call"
    description = (
        "Send a message to a remote agent a person has configured (A2A) and return its answer. Arguments: "
        "agent (its configured name), message, data (the data classes the message carries, default public; "
        "refused when the agent may not receive one), task_id (to answer a question the agent asked, or with "
        "no message to check on a task), cancel (true with task_id to cancel it). The message leaves the house."
    )
    read_only = False
    reversibility = "irreversible"
    args_schema = {
        "type": "object", "required": ["agent"],
        "properties": {
            "agent": {"type": "string"}, "message": {"type": "string"},
            "data": {"type": "array", "items": {"type": "string"}},
            "task_id": {"type": "string"}, "context_id": {"type": "string"},
            "cancel": {"type": "boolean"},
        },
    }

    def __init__(self, agents: tuple[A2aAgentConfig, ...], *, secrets=None,
                 transport_factory: Callable[[A2aAgentConfig], Any] | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 progress: ProgressFn | None = None, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._agents = {agent.name: agent for agent in agents}
        self._secrets = secrets
        self._transport_factory = transport_factory or sdk_transport
        self._sleep = sleep
        self._progress = progress or self._log_progress
        self._monotonic = monotonic
        self._cards: dict[str, tuple[float, dict]] = {}
        worst = max((a.max_wait_s + 3 * a.timeout_s for a in agents), default=45.0)
        self.timeout_s = worst + 15.0

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        name = str(args.get("agent", "")).strip()
        agent = self._agents.get(name)
        if agent is None:
            known = ", ".join(sorted(self._agents)) or "none"
            return ToolResult.refused(f"no A2A agent named {name!r} (configured: {known}); "
                                      "a person adds one, Sim may propose one with propose_a2a_agent")
        message_text = str(args.get("message", "") or "").strip()
        task_id = str(args.get("task_id", "") or "").strip()
        context_id = str(args.get("context_id", "") or "").strip()
        cancel = _truthy(args.get("cancel"))
        data = _data_classes(args.get("data"))
        if cancel and not task_id:
            return ToolResult.refused("cancel needs the task_id to cancel")
        if not cancel and not message_text and not task_id:
            return ToolResult.refused("nothing to send: give a message, or a task_id to check on")
        if message_text:
            allowed = set(agent.allowed_data)
            blocked = [item for item in data if "*" not in allowed and item not in allowed]
            if blocked:
                return ToolResult.refused(
                    f"agent {name!r} may not receive {', '.join(blocked)} data "
                    f"(allowed: {', '.join(agent.allowed_data) or 'nothing'}); nothing was sent")

        try:
            transport = self._transport_factory(agent)
        except ToolUnconfigured as exc:
            return ToolResult.unconfigured(f"a2a_call: {exc}", metadata={"agent": name})
        except Exception as exc:  # noqa: BLE001 -- a broken transport is a result, not a crash
            return ToolResult.failed(f"a2a_call: could not reach {name}: {exc!r}", metadata={"agent": name})
        try:
            return await self._call(agent, transport, ctx, message_text=message_text, task_id=task_id,
                                    context_id=context_id, cancel=cancel, data=data)
        except A2aError as exc:
            return ToolResult(ok=False, error=f"a2a_call {name}: {exc}", error_kind=exc.error_kind,
                              metadata={"agent": name})
        except ToolUnconfigured as exc:
            return ToolResult.unconfigured(f"a2a_call {name}: {exc}", metadata={"agent": name})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- network and SDK errors: the same call may work later
            return ToolResult.transient(f"a2a_call {name}: {exc!r}"[:600], metadata={"agent": name})
        finally:
            with contextlib.suppress(Exception):
                await transport.close()

    async def _card(self, agent: A2aAgentConfig, transport, secret: str) -> dict:
        cached = self._cards.get(agent.name)
        now = self._monotonic()
        if cached is not None and now - cached[0] < CARD_TTL_S:
            return cached[1]
        try:
            card = await transport.card()
        except CardUnauthorized as exc:
            # Asked again once, with the configured credential, of the
            # origin a person configured: a card behind a bearer (another
            # Sim's is) is still that agent's card. Only behind a bearer:
            # a card that asked for Basic, or for nothing it said, is not
            # sent a secret meant as a bearer token.
            if exc.scheme != "bearer" and agent.auth_scheme != "bearer":
                asked = f"asks for {exc.challenge!r}" if exc.challenge else "names no scheme"
                raise A2aError(f"the agent card is behind a credential and {asked}; Sim sends its secret only "
                               f"as a bearer: if {agent.name} takes one, set auth_scheme = \"bearer\" in its "
                               "table", error_kind="unconfigured") from None
            if not secret:
                raise A2aError(f"the agent's card needs a credential and no secret is set: put "
                               f"{agent.auth_secret or '<a key name>'} in secrets.toml and name it as this "
                               "agent's auth_secret", error_kind="unconfigured") from None
            card = await transport.card(headers={"Authorization": f"Bearer {secret}"})
        if not isinstance(card, Mapping):
            raise A2aError("the agent card is not an object")
        self._cards[agent.name] = (now, dict(card))
        return dict(card)

    async def _call(self, agent, transport, ctx, *, message_text, task_id, context_id, cancel, data) -> ToolResult:
        secret = ""
        if agent.auth_secret and self._secrets is not None:
            with contextlib.suppress(Exception):
                secret = str(self._secrets.get(agent.auth_secret) or "")
        card = await self._card(agent, transport, secret)
        check_card(card)
        version = negotiate_version(card)
        headers = auth_headers(card, secret_name=agent.auth_secret, secret=secret)
        await transport.connect({**headers, VERSION_HEADER: version})
        progress = _Progress()
        progress.task_id, progress.context_id = task_id, context_id

        if cancel:
            progress.fold(await transport.cancel(task_id))
            await self._record(ctx, "cancelled", agent, progress)
            return ToolResult(ok=True, output=f"{agent.name}: task {task_id} is {progress.state or 'cancel sent'}",
                              side_effects=(f"a2a:{agent.name}:cancel",),
                              metadata=self._meta(agent, progress))

        if message_text:
            message = user_message(message_text, task_id=task_id, context_id=context_id)
            await self._record(ctx, "sent", agent, progress, data=data, chars=len(message_text),
                               sha256=hashlib.sha256(message_text.encode("utf-8")).hexdigest())
            streamed = False
            if bool((card.get("capabilities") or {}).get("streaming")):
                streamed = await self._stream(agent, transport, ctx, message, progress)
            if not streamed:
                progress.fold(await transport.send(message))
        if not progress.done and not progress.out_of_time:
            await self._poll(agent, transport, ctx, progress, check_first=not message_text)
        return await self._result(agent, ctx, progress, sent=bool(message_text))

    async def _stream(self, agent, transport, ctx, message, progress: _Progress) -> bool:
        """True when the stream ran: to the end, until `max_wait_s` passed
        (the task is then reported still running, with its id), or until it
        broke after the task existed, which polling then follows. A stream
        that breaks before anything arrived is a transient error, not a
        `message/send`: the agent may already have the message, and
        sending it twice is not something a retry should decide."""
        deadline = self._monotonic() + max(0.0, agent.max_wait_s)
        try:
            async for event in transport.stream(message):
                before = (progress.state, progress.status_text)
                progress.fold(event)
                if event.get("kind") == "status-update" and (progress.state, progress.status_text) != before:
                    await self._emit(ctx, agent, progress)
                if progress.done:
                    break
                if self._monotonic() >= deadline:
                    progress.out_of_time = True
                    break
        except (A2aError, ToolUnconfigured):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a broken stream falls back to polling
            if not progress.task_id:
                ctx.logger.warning("a2a_stream_failed", agent=agent.name, error=repr(exc))
                raise A2aError(f"the stream broke before the agent answered: {exc!r}", error_kind="transient")
            ctx.logger.info("a2a_stream_fell_back_to_polling", agent=agent.name, task_id=progress.task_id)
        return True

    async def _poll(self, agent, transport, ctx, progress: _Progress, *, check_first: bool) -> None:
        if not progress.task_id:
            return
        interval = max(0.0, agent.poll_interval_s)
        polls = max(1, int(agent.max_wait_s // interval) if interval else 1)
        for attempt in range(polls):
            if attempt or not check_first:
                await self._sleep(interval)
            before = (progress.state, progress.status_text)
            progress.fold(await transport.get_task(progress.task_id))
            if (progress.state, progress.status_text) != before:
                await self._emit(ctx, agent, progress)
            if progress.done:
                return

    async def _result(self, agent, ctx, progress: _Progress, *, sent: bool) -> ToolResult:
        await self._record(ctx, progress.state or "unknown", agent, progress)
        meta = self._meta(agent, progress)
        effects = (f"a2a:{agent.name}:send",) if sent else ()
        state = progress.state
        if state == "completed":
            return ToolResult(ok=True, output=progress.answer() or f"{agent.name} finished with no text",
                              side_effects=effects, metadata=meta)
        if state == "input-required":
            question = progress.status_text or "(no question text)"
            meta["question"] = question
            return ToolResult(ok=True, side_effects=effects, metadata=meta, output=(
                f"{agent.name} needs input: {question}\nAnswer with a2a_call agent={agent.name} "
                f"task_id={progress.task_id} message=<the answer>"))
        if state == "auth-required":
            return ToolResult.unconfigured(f"{agent.name} asks for authentication Sim does not have: "
                                           f"{progress.status_text}".strip(), side_effects=effects, metadata=meta)
        if state in ("failed", "rejected", "canceled"):
            return ToolResult.failed(f"{agent.name}: task {state}: {progress.answer()}".rstrip(": "),
                                     side_effects=effects, metadata=meta)
        return ToolResult.transient(
            f"{agent.name} is still {state or 'working'} after {agent.max_wait_s:.0f}s; check again with "
            f"a2a_call agent={agent.name} task_id={progress.task_id}", side_effects=effects, metadata=meta)

    @staticmethod
    def _meta(agent: A2aAgentConfig, progress: _Progress) -> dict:
        return {"agent": agent.name, "task_id": progress.task_id, "context_id": progress.context_id,
                "state": progress.state}

    async def _emit(self, ctx, agent, progress: _Progress) -> None:
        event = {"agent": agent.name, "task_id": progress.task_id, "state": progress.state,
                 "text": progress.status_text[:500]}
        try:
            await self._progress(ctx, event)
        except Exception as exc:  # noqa: BLE001 -- progress is a report, never the call
            ctx.logger.warning("a2a_progress_failed", agent=agent.name, error=repr(exc))

    async def _log_progress(self, ctx, event: dict) -> None:
        await self._append(ctx, "progress", event)

    async def _record(self, ctx, type_: str, agent, progress: _Progress, **extra) -> None:
        payload = {"agent": agent.name, "url": agent.url, "task_id": progress.task_id,
                   "state": progress.state, **extra}
        if "data" in payload:
            payload["data"] = list(payload["data"])
        with contextlib.suppress(Exception):
            await self._append(ctx, type_, payload)

    @staticmethod
    async def _append(ctx, type_: str, payload: dict) -> None:
        if ctx is None or getattr(ctx, "ledger", None) is None:
            return
        await ctx.ledger.append(A2A_CALLS_STREAM, Event(
            stream=A2A_CALLS_STREAM, type=type_, ts=ctx.clock.now(), trace_id="", causation_id=None,
            payload={"action_id": ctx.action_id, "task": ctx.task_id, **payload}))


_PROPOSAL_KEYS = frozenset({"name", "url", "auth_secret", "allowed_data", "reason"})
_FIELD_RE = re.compile(r"^\s*([a-zA-Z_]+)\s*:\s*(.*)$")


def parse_proposal(text: str) -> dict[str, str]:
    """`key: value` lines, or a JSON object; unknown keys are dropped."""
    stripped = (text or "").strip()
    if stripped.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError):
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return {key: (", ".join(map(str, value)) if isinstance(value, list) else str(value))
                        for key, value in obj.items() if key in _PROPOSAL_KEYS and value is not None}
    fields: dict[str, str] = {}
    key: str | None = None
    for line in stripped.splitlines():
        match = _FIELD_RE.match(line)
        if match and match.group(1).lower() in _PROPOSAL_KEYS:
            key = match.group(1).lower()
            fields[key] = match.group(2).strip()
        elif key is not None:
            fields[key] = (fields[key] + "\n" + line).strip()
    return fields


class ProposeA2aAgentTool:
    """Sim's half of "propose a remote agent, a person approves". It only
    validates and records a proposal on `a2a:proposals`; writing the
    `[crew.a2a_agents.<name>]` table is a person's `a2a approve`, which
    no tool call can reach. `reversible` for the same reason
    `propose_mcp_server` is: nothing is granted by the proposal."""

    name = "propose_a2a_agent"
    description = (
        "Propose a remote A2A agent for a person to approve (the `a2a` command). Never adds or calls it. "
        "Argument is a block of `key: value` lines: name, url, allowed_data (comma-separated data classes it "
        "may receive), auth_secret (a key NAME in secrets.toml, never a value), reason."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "required": ["proposal"], "properties": {"proposal": {"type": "string"}}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        fields = parse_proposal(str(args.get("proposal", "")))
        name, url = fields.get("name", "").strip(), fields.get("url", "").strip()
        auth_secret, reason = fields.get("auth_secret", "").strip(), fields.get("reason", "").strip()
        allowed = [item.strip().lower() for item in fields.get("allowed_data", "public").split(",") if item.strip()]
        if not _NAME_RE.match(name):
            return ToolResult.refused("invalid or missing 'name' -- lowercase letters/digits/underscore, "
                                      "starting with a letter")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ToolResult.refused(f"'url' must be an http(s) URL, got {url!r}")
        if auth_secret and not _SECRET_RE.match(auth_secret):
            return ToolResult.refused(f"invalid auth_secret {auth_secret!r} -- a key NAME in UPPER_SNAKE_CASE, "
                                      "never a value")
        bad = [item for item in allowed if not _DATA_RE.match(item)]
        if bad or not allowed:
            return ToolResult.refused(f"invalid allowed_data {bad or allowed!r} -- lowercase class names")
        if not reason:
            return ToolResult.refused("missing 'reason' -- explain why this agent is needed")
        proposal_id = uuid.uuid4().hex[:12]
        payload = {"proposal_id": proposal_id, "name": name, "url": url, "auth_secret": auth_secret,
                   "allowed_data": allowed, "reason": reason, "status": "pending"}
        await ctx.ledger.append(A2A_PROPOSALS_STREAM, Event(
            stream=A2A_PROPOSALS_STREAM, type="proposed", ts=ctx.clock.now(),
            trace_id="", causation_id=None, payload=payload))
        return ToolResult(ok=True, output=f"proposal {proposal_id} recorded: A2A agent {name} ({url}) -- "
                                          "awaiting a person's review via `a2a`",
                          metadata={"proposal_id": proposal_id, "name": name, "reason": reason})


def a2a_tools(config, *, secrets=None) -> list:
    """`propose_a2a_agent` always; `a2a_call` only when a person has
    configured at least one agent."""
    agents = tuple(getattr(config, "a2a_agents", ()) or ())
    tools: list = [ProposeA2aAgentTool()]
    if agents:
        tools.append(A2aCallTool(agents, secrets=secrets))
    return tools


__all__ = [
    "A2A_CALLS_STREAM", "A2A_PROPOSALS_STREAM", "A2aAgentConfig", "A2aCallTool", "A2aError", "CLIENT_VERSIONS",
    "CardUnauthorized", "ProposeA2aAgentTool", "SDK_MISSING", "SdkTransport", "VERSION_HEADER",
    "a2a_agents_from_mapping", "a2a_tools", "auth_headers", "card_url", "card_versions", "challenge_scheme",
    "check_card", "negotiate_version",
]
