"""Execution's own tool calls, through the action path (stage 1 item 7, S12).

Execution starts some tools by itself: the Ring and NVR watches and the
TV dashboard at boot, the charts when the dashboard's Charts view is
picked, and the camera watcher's `cam_list`/`ring_list`/`*_snapshot`.
Each of those used to call `tool.run(...)` straight from the registry,
with a made-up action id, no proposal, no Guardian decision, no token
and no `action:` stream -- six effects nobody could see or refuse.

`SelfActions.run` proposes the call like any other proposer does
(`action.proposed`, `proposed_by="execution"`) and waits for the
outcome keyed by the action id: `action.result` (the tool ran, through
`Service._on_approved` like every approved action) or `action.denied`
(Guardian refused, or the token failed). It never raises: a denial, a
timeout or a broken bus comes back as a `ToolResult(ok=False, ...)` so
the caller logs it and leaves its feature off.

The result is read back into a `ToolResult`: `stdout_preview` (or the
whole output when it was spilled to a blob) and the tool's metadata
from `metadata_ref` -- the camera watcher needs `metadata["cameras"]`
and `metadata["path"]`, not the printed lines.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolResult

PROPOSED_BY = "execution"
# How long Guardian gets to decide, on top of the tool's own budget.
GUARDIAN_MARGIN_S = 30.0


class SelfActions:
    """Propose one of Execution's own calls and wait for its outcome."""

    def __init__(self, *, bus, ledger, logger, registry, timeout_for) -> None:
        self._bus = bus
        self._ledger = ledger
        self._logger = logger
        self._registry = registry
        # `timeout_for(tool) -> seconds`: the same budget `_on_approved`
        # gives the tool, so the wait here outlasts the run it waits on.
        self._timeout_for = timeout_for

    async def run(self, tool_name: str, args: dict, *, rationale: str,
                  timeout: float | None = None) -> ToolResult:
        tool = self._registry.get(tool_name)
        if tool is None:
            return ToolResult.refused(f"unknown tool {tool_name!r}")
        action_id = f"execution-{tool_name}-{uuid.uuid4().hex[:12]}"
        if timeout is None:
            timeout = float(self._timeout_for(tool)) + GUARDIAN_MARGIN_S
        loop = asyncio.get_running_loop()
        done: asyncio.Future = loop.create_future()

        async def _on(message: Message) -> None:
            if not done.done() and (message.payload or {}).get("action_id") == action_id:
                done.set_result(message)

        subs: list = []
        try:
            # Subscribed BEFORE the proposal: a fast tool can answer
            # before a subscription made afterwards exists.
            for topic in (topics.ACTION_RESULT, topics.ACTION_DENIED):
                subs.append(await self._bus.subscribe(topic, _on))
            await self._bus.publish(Message.new(
                topics.ACTION_PROPOSED, source=PROPOSED_BY,
                payload={
                    "action_id": action_id, "tool": tool_name, "args": dict(args or {}),
                    "scope": {"paths": [], "network": True},
                    # Guardian recomputes the class for a physical tool and
                    # never widens on a proposer's label; the tool's own
                    # declaration is the honest floor.
                    "reversibility": str(getattr(tool, "reversibility", "") or "irreversible"),
                    "rationale": rationale, "proposed_by": PROPOSED_BY,
                },
            ))
            try:
                message = await asyncio.wait_for(done, timeout=timeout)
            except asyncio.TimeoutError:
                return ToolResult.transient(f"no answer to {tool_name} within {timeout:.0f}s "
                                                  f"(action {action_id})",
                                  metadata={"action_id": action_id, "timed_out": True})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a feature stays off; Execution stays up
            return ToolResult(ok=False, error=f"could not propose {tool_name}: {exc!r}",
                              metadata={"action_id": action_id})
        finally:
            for sub in subs:
                with contextlib.suppress(Exception):
                    await sub.unsubscribe()

        payload = message.payload or {}
        if message.type == topics.ACTION_DENIED:
            reasons = ", ".join(payload.get("reasons") or ()) or "no reason given"
            return ToolResult.refused(f"denied ({payload.get('layer', 'policy')}): {reasons}",
                              metadata={"action_id": action_id, "denied": True})
        return await self._as_tool_result(action_id, payload)

    async def _as_tool_result(self, action_id: str, payload: dict) -> ToolResult:
        output = str(payload.get("stdout_preview") or "")
        ref = str(payload.get("output_ref") or "")
        if ref and self._ledger is not None:
            with contextlib.suppress(Exception):
                output = (await self._ledger.get_blob(ref)).decode("utf-8", "replace")
        metadata: dict = {}
        meta_ref = str(payload.get("metadata_ref") or "")
        if meta_ref and self._ledger is not None:
            try:
                loaded = json.loads((await self._ledger.get_blob(meta_ref)).decode("utf-8"))
                if isinstance(loaded, dict):
                    metadata = loaded
            except Exception as exc:  # noqa: BLE001 -- a lost blob is a result without detail
                self._logger.warning("self_action_metadata_unreadable", action_id=action_id, error=repr(exc))
        metadata.setdefault("action_id", action_id)
        ok = bool(payload.get("ok"))
        error = payload.get("error")
        return ToolResult(ok=ok, output=output, error=(str(error) if error is not None else None),
                          side_effects=tuple(payload.get("side_effects") or ()), metadata=metadata,
                          error_kind="" if ok else str(payload.get("error_kind") or "failed"))


__all__ = ["GUARDIAN_MARGIN_S", "PROPOSED_BY", "SelfActions"]
