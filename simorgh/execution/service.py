"""Execution's Service (08-execution.md section 5): the only subsystem
the Kernel/Bus enforcement lets subscribe to `action.approved`. Verifies
every approval independently (verifier.py) before running anything,
dispatches to the tool registry, and reports `action.result`. Registry
and dispatch are kept in this one module for this build (the spec's
`registry.py`/`runner.py` split is a natural follow-up once the tool
count grows past what fits in one screenful).

Skill acquisition as procedural memory (Phase 4 roadmap item 4.7): per
08-execution.md's own dependency line ("Depends on ... learn.skill.
acquired") and section 5.2 ("`learn.skill.acquired` -> load the skill
module in a sandbox-backed SkillTool, register it, emit tool.registered"),
this Service subscribes to `learn.skill.acquired` and loads exactly the
one newly-acquired skill -- never a directory scan of every skill ever
acquired at boot, which is what makes this "on demand." `_load_skill`
also best-effort enriches the tool's `description` via a
`memory.retrieve{kinds:[procedural]}` request against the procedural
record Learning writes on acquisition (learning/pipeline.py) -- the
"discoverable by description" half of the same roadmap item. A second,
independent on-demand path lives in `_on_approved`: an approved action
naming an as-yet-unregistered `skill:<name>` tool (e.g. after a restart,
when no fresh `learn.skill.acquired` fired this process) triggers the
same `_load_skill` lazily, reconstructing the skill's path from the
`skill_dir/<name>.py` convention `ApplySkillTool` and `SkillPipeline`
both already use.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Health, ToolContext

from . import pathsafety
from .config import Config
from .mcp import McpClient, McpServerConfig, McpToolProxy
from .tools import SkillTool, builtin_tools
from .verifier import ApprovalVerifier

INFLIGHT_STREAM = "execution:inflight"
TOOLS_STREAM = "execution:tools"


class Service:
    name = "execution"
    version = "0.1.0"
    consumes = (topics.ACTION_APPROVED, topics.SYSTEM_STATE_CHANGED, topics.LEARN_SKILL_ACQUIRED)
    produces = (topics.ACTION_RESULT, topics.ACTION_DENIED, topics.TOOL_REGISTERED, topics.PERCEPT_WEB_FETCHED)

    def __init__(self, *, config: Config | None = None, extra_tools: list | None = None) -> None:
        self._config = config or Config()
        self._extra_tools = extra_tools or []
        self._registry: dict[str, object] = {}
        self._subs: list = []
        self._paused = False
        self._semaphore: asyncio.Semaphore | None = None
        self._degraded_detail = ""
        self._mcp_clients: list[McpClient] = []
        self._mcp_errors: list[str] = []

    async def start(self, ctx) -> None:
        self._ctx = ctx
        secret = ctx.secrets.get("__hmac__")
        if not secret:
            raise RuntimeError("execution: no guardian_hmac secret in Context -- refusing to start")
        self._secret = bytes.fromhex(secret) if isinstance(secret, str) else secret
        self._verifier = ApprovalVerifier(self._secret)
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_actions)

        for tool in builtin_tools(self._config) + self._extra_tools:
            self._registry[tool.name] = tool
            await ctx.bus.publish(Message.new(
                topics.TOOL_REGISTERED, source="execution",
                payload={"name": tool.name, "version": "1", "description": tool.description,
                         "read_only": tool.read_only, "reversibility": tool.reversibility,
                         "schema_ref": "", "provider": "builtin"},
            ))
            await ctx.ledger.append(TOOLS_STREAM, self._event(TOOLS_STREAM, "registered", {"name": tool.name}))

        for server in self._config.mcp_servers:
            await self._start_mcp_server(server)

        await self._replay_inflight()

        self._subs.append(await ctx.bus.subscribe(topics.ACTION_APPROVED, self._on_approved, group="execution"))
        self._subs.append(await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))
        self._subs.append(await ctx.bus.subscribe(topics.LEARN_SKILL_ACQUIRED, self._on_skill_acquired))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()
        for client in self._mcp_clients:
            await client.close()
        self._mcp_clients.clear()

    async def health(self) -> Health:
        if self._degraded_detail:
            return Health.degraded(self._degraded_detail)
        if self._mcp_errors:
            return Health.degraded("; ".join(self._mcp_errors))
        return Health.ok(f"{len(self._registry)} tools registered")

    # -- MCP servers (mcp.py's own module docstring: a human-configured,
    # static list -- never autonomously expanded) ---------------------------
    async def _start_mcp_server(self, server: McpServerConfig) -> None:
        """Start one configured MCP server and register every tool it
        declares. Never raises: a server that fails to launch, times out,
        or speaks a broken protocol is logged and skipped -- one
        misconfigured server must not stop the rest of Execution (and
        therefore the whole Kernel) from booting."""
        client = McpClient(server)
        try:
            await asyncio.wait_for(client.start(), timeout=server.timeout_s)
            specs = await asyncio.wait_for(client.list_tools(), timeout=server.timeout_s)
        except Exception as exc:  # noqa: BLE001 -- a bad server degrades, never crashes Execution's boot
            detail = f"mcp server {server.name!r} failed to start: {exc!r}"
            self._mcp_errors.append(detail)
            self._ctx.logger.warning("mcp_server_start_failed", server=server.name, detail=repr(exc))
            with contextlib.suppress(Exception):
                await client.close()
            return

        self._mcp_clients.append(client)
        for spec in specs:
            tool = McpToolProxy(client, server, spec)
            self._registry[tool.name] = tool
            await self._ctx.bus.publish(Message.new(
                topics.TOOL_REGISTERED, source="execution",
                payload={"name": tool.name, "version": "1", "description": tool.description,
                         "read_only": tool.read_only, "reversibility": tool.reversibility,
                         "schema_ref": "", "provider": "mcp"},
            ))
            await self._ctx.ledger.append(TOOLS_STREAM, self._event(TOOLS_STREAM, "registered", {"name": tool.name, "provider": "mcp"}))

    async def _on_state_changed(self, message: Message) -> None:
        self._paused = message.payload["state"] in ("paused", "stopping")

    # -- skill acquisition as procedural memory (roadmap 4.7) --------------------
    async def _on_skill_acquired(self, message: Message) -> None:
        name, path = message.payload.get("name", ""), message.payload.get("path", "")
        if name and path:
            await self._load_skill(name, path=path)

    async def _load_skill(self, name: str, *, path: str) -> object | None:
        """Register the one named skill as a `skill:<name>` tool, reading
        its source from `path` (readable-roots bounded) and its
        description from Memory's procedural record if one answers in
        time. Never raises; a load that cannot complete just leaves the
        tool unregistered for the caller to report as `unknown tool`."""
        existing = self._registry.get(f"skill:{name}")
        if existing is not None:
            return existing
        source = pathsafety.safe_read_file(self._config.repo_root, path, readable_roots=self._config.readable_roots)
        if source.startswith("[refused"):
            self._ctx.logger.warning("skill_load_refused", name=name, path=path, detail=source)
            return None
        description = await self._skill_description(name) or f"On-demand skill {name!r} acquired at {path}"
        tool = SkillTool(self._config, skill_name=name, source=source, description=description)
        self._registry[tool.name] = tool
        await self._ctx.bus.publish(Message.new(
            topics.TOOL_REGISTERED, source="execution",
            payload={"name": tool.name, "version": "1", "description": tool.description,
                     "read_only": tool.read_only, "reversibility": tool.reversibility,
                     "schema_ref": "", "provider": "skill"},
        ))
        await self._ctx.ledger.append(TOOLS_STREAM, self._event(TOOLS_STREAM, "registered", {"name": tool.name, "provider": "skill"}))
        return tool

    async def _skill_description(self, name: str) -> str | None:
        """Best-effort `memory.retrieve{kinds:[procedural]}` for the
        description Learning stored on acquisition (learning/pipeline.py)
        -- the "discoverable by description" half of roadmap item 4.7.
        Absence (timeout, no Memory booted, nothing stored yet) degrades
        to a synthesized description rather than blocking the load."""
        try:
            reply = await self._ctx.bus.request(
                Message.new(
                    topics.MEMORY_RETRIEVE, source="execution",
                    payload={"query": name, "kinds": ["procedural"], "k": 3,
                             "filters": {"tags": ["skill", name]}},
                ),
                timeout=self._config.skill_lookup_timeout_s,
            )
        except Exception:  # noqa: BLE001 -- a description lookup failure must never block loading the skill
            return None
        items = reply.payload.get("items") or []
        return items[0]["content"] if items else None

    async def _replay_inflight(self) -> None:
        events = await self._ctx.ledger.read(INFLIGHT_STREAM)
        started = {e.payload["action_id"] for e in events if e.type == "started"}
        finished = {e.payload["action_id"] for e in events if e.type == "finished"}
        for action_id in started - finished:
            await self._ctx.bus.publish(Message.new(
                topics.ACTION_RESULT, source="execution",
                payload={"action_id": action_id, "ok": False, "output_ref": "", "stdout_preview": "",
                         "duration_ms": 0, "side_effects": [], "error": "interrupted by restart"},
            ))
            await self._ctx.ledger.append(INFLIGHT_STREAM, self._event(INFLIGHT_STREAM, "finished", {"action_id": action_id, "ok": False}))

    async def _fetch_proposed_args(self, action_id: str) -> dict | None:
        events = await self._ctx.ledger.read(f"action:{action_id}")
        for event in events:
            if event.type == "received":
                return event.payload["proposal"].get("args")
        return None

    async def _on_approved(self, message: Message) -> None:
        approved = message.payload
        action_id = approved["action_id"]
        now = self._ctx.clock.now()
        args = await self._fetch_proposed_args(action_id)
        outcome = self._verifier.verify(approved, args, now=now)

        await self._ctx.ledger.append(f"action:{action_id}", self._event(
            f"action:{action_id}", "verified", {"outcome": outcome.ok, "reason": outcome.reason},
        ))

        if not outcome.ok:
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED,
                {"action_id": action_id, "reasons": [f"signature {outcome.reason}"], "layer": "token"},
                source="execution",
            ))
            self._degraded_detail = f"token verification failed: {outcome.reason}"
            return
        self._degraded_detail = ""

        if self._paused:
            await self._publish_result(message, action_id, ok=False, error="paused")
            return

        tool = self._registry.get(approved["tool"])
        if tool is None and approved["tool"].startswith("skill:"):
            # Lazy on-demand load: this process never saw this skill's own
            # `learn.skill.acquired` (e.g. it was acquired before this
            # restart), so resolve it from the `skill_dir/<name>.py`
            # convention `ApplySkillTool`/`SkillPipeline` both use, rather
            # than reporting a false "unknown tool" for a skill that is
            # really just not loaded *yet*.
            skill_name = approved["tool"][len("skill:"):]
            tool = await self._load_skill(skill_name, path=f"{self._config.skill_dir}/{skill_name}.py")
        if tool is None:
            await self._publish_result(message, action_id, ok=False, error="unknown tool")
            return

        async with self._semaphore:
            await self._ctx.ledger.append(INFLIGHT_STREAM, self._event(INFLIGHT_STREAM, "started", {"action_id": action_id, "tool": tool.name}))
            start = time.monotonic()
            timeout = approved.get("constraints", {}).get("timeout_s") or self._config.default_timeout_s
            ctx = ToolContext(
                action_id=action_id, task_id=None, scope={}, constraints=approved.get("constraints") or {},
                data_dir=self._config.repo_root, clock=self._ctx.clock, logger=self._ctx.logger,
                ledger=self._ctx.ledger,
            )
            try:
                result = await asyncio.wait_for(tool.run(args or {}, ctx=ctx), timeout=timeout)
            except asyncio.TimeoutError:
                await self._finish(action_id)
                await self._publish_result(message, action_id, ok=False, error="timeout",
                                            duration_ms=int((time.monotonic() - start) * 1000))
                return
            except Exception as exc:  # noqa: BLE001 -- a tool crash must become a result, never take Execution down
                await self._finish(action_id)
                await self._publish_result(message, action_id, ok=False, error=repr(exc),
                                            duration_ms=int((time.monotonic() - start) * 1000))
                return

            await self._finish(action_id)
            duration_ms = int((time.monotonic() - start) * 1000)
            output = result.output if isinstance(result.output, str) else result.output.decode("utf-8", "replace")
            output_ref = ""
            preview = output
            if len(output.encode("utf-8")) > self._config.blob_inline_threshold_bytes:
                output_ref = await self._ctx.ledger.put_blob(output.encode("utf-8"))
                preview = output[: self._config.max_output_bytes]
            await self._publish_result(
                message, action_id, ok=result.ok, error=result.error, output_ref=output_ref,
                stdout_preview=preview[: self._config.max_output_bytes], duration_ms=duration_ms,
                side_effects=list(result.side_effects),
            )
            await self._ctx.bus.publish(Message.new(
                topics.TOOL_INVOKED, source="execution",
                payload={"name": tool.name, "action_id": action_id, "duration_ms": duration_ms, "ok": result.ok},
            ))
            if tool.name == "web_fetch" and result.ok:
                # 08-execution.md section 4.2's `percept.web.fetched` row
                # ("after web_fetch -- memory, curiosity"): the contract
                # (`contracts/messages/percept.py`) requires a `content_ref`
                # unconditionally, not the size-gated inline preview above,
                # so a small fetch still gets its own blob rather than
                # reusing `output_ref` (which stays "" under the inline
                # threshold).
                content_ref = output_ref or await self._ctx.ledger.put_blob(output.encode("utf-8"), content_type="text/plain")
                await self._ctx.bus.publish(Message.new(
                    topics.PERCEPT_WEB_FETCHED, source="execution",
                    payload={
                        "url": result.metadata.get("url", ""),
                        "status": int(result.metadata.get("status") or 0),
                        "content_ref": content_ref,
                        "sha256": result.metadata.get("sha256", ""),
                        "fetched_at": float(result.metadata.get("fetched_at") or 0.0),
                    },
                ))

    async def _finish(self, action_id: str) -> None:
        await self._ctx.ledger.append(INFLIGHT_STREAM, self._event(INFLIGHT_STREAM, "finished", {"action_id": action_id}))

    async def _publish_result(self, message: Message, action_id: str, *, ok: bool, error: str | None = None,
                               output_ref: str = "", stdout_preview: str = "", duration_ms: int = 0,
                               side_effects: list | None = None) -> None:
        payload = {
            "action_id": action_id, "ok": ok, "output_ref": output_ref, "stdout_preview": stdout_preview,
            "duration_ms": duration_ms, "side_effects": side_effects or [],
        }
        if error is not None:
            payload["error"] = error
        await self._ctx.bus.publish(message.caused(topics.ACTION_RESULT, payload, source="execution"))

    def _event(self, stream: str, type: str, payload: dict) -> Event:
        return Event(stream=stream, type=type, ts=self._ctx.clock.now(), trace_id="", causation_id=None, payload=payload)
