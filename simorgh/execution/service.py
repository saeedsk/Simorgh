"""Execution's Service (08-execution.md section 5): the only subsystem
the Kernel/Bus enforcement lets subscribe to `action.approved`. Verifies
every approval independently (verifier.py) before running anything,
dispatches to the tool registry, and reports `action.result`. Registry
and dispatch are kept in this one module for this build (the spec's
`registry.py`/`runner.py` split is a natural follow-up once the tool
count grows past what fits in one screenful).
"""

from __future__ import annotations

import asyncio
import time

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Health, ToolContext

from .config import Config
from .tools import builtin_tools
from .verifier import ApprovalVerifier

INFLIGHT_STREAM = "execution:inflight"
TOOLS_STREAM = "execution:tools"


class Service:
    name = "execution"
    version = "0.1.0"
    consumes = (topics.ACTION_APPROVED, topics.SYSTEM_STATE_CHANGED)
    produces = (topics.ACTION_RESULT, topics.ACTION_DENIED, topics.TOOL_REGISTERED)

    def __init__(self, *, config: Config | None = None, extra_tools: list | None = None) -> None:
        self._config = config or Config()
        self._extra_tools = extra_tools or []
        self._registry: dict[str, object] = {}
        self._subs: list = []
        self._paused = False
        self._semaphore: asyncio.Semaphore | None = None
        self._degraded_detail = ""

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

        await self._replay_inflight()

        self._subs.append(await ctx.bus.subscribe(topics.ACTION_APPROVED, self._on_approved, group="execution"))
        self._subs.append(await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()

    async def health(self) -> Health:
        if self._degraded_detail:
            return Health.degraded(self._degraded_detail)
        return Health.ok(f"{len(self._registry)} tools registered")

    async def _on_state_changed(self, message: Message) -> None:
        self._paused = message.payload["state"] in ("paused", "stopping")

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
