"""The structural safety proof (docs/blueprint/subsystems/03-kernel.md
section 5.4): before any real work is allowed, `--self-check` proves the
guarded action path actually works -- proposal to approval to execution
with a verified token, a forged token rejected, a pause denying new
proposals, and the reserved-topic subscribe restriction actually
enforced. This replaces v1's `self_check()` (import-and-construct) with
a *behavioral* proof; `learning`'s `relaunch` tool calls this (via `simorgh
--self-check`) before `execv`, exactly as v1's `self_patch.relaunch()` did.

The Guardian/Execution used here are minimal stubs, not the real
subsystems (`guardian`/`execution` land in Phase 1B) -- their only job is
to speak the token contract correctly, so this proves the *path*, not
any subsystem's actual policy. Once the real ones exist, this module is
unchanged: it is a proof about the wire, not about who is on it.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from simorgh.bus.api import PolicyViolation
from simorgh.bus.client import BusClient
from simorgh.bus.enforcement import ReservedTopologyPolicy
from simorgh.bus.factory import make_backend as make_bus_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import security, topics
from simorgh.contracts.envelope import Message, validate
from simorgh.ledger.client import LedgerClient
from simorgh.ledger.backends.memory import InMemoryBackend as InMemoryLedgerBackend

NOOP_TOOL = "noop"


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class SelfCheckResult:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.passed for s in self.steps)

    def report(self) -> str:
        lines = [f"{'PASS' if s.passed else 'FAIL'}  {s.name}" + (f" -- {s.detail}" if s.detail else "")
                for s in self.steps]
        lines.append("OVERALL: " + ("PASS" if self.passed else "FAIL"))
        return "\n".join(lines)


class _StubGuardian:
    """Approves anything not explicitly denied, honoring `system.pause`
    with `layer="paused"` -- just enough policy to prove the wire; the
    real Guardian (09-guardian.md) supersedes this without changing the
    proof's shape."""

    def __init__(self, *, hmac_secret: bytes, events: list, clock=time.time) -> None:
        self._secret = hmac_secret
        self._events = events
        self._clock = clock
        self._paused = False
        self._subs = []

    async def start(self, bus: BusClient) -> None:
        self._subs.append(await bus.subscribe(topics.ACTION_PROPOSED, self._on_proposed, group="guardian"))
        self._subs.append(await bus.subscribe(topics.SYSTEM_PAUSE, self._on_pause))
        self._subs.append(await bus.subscribe(topics.SYSTEM_RESUME, self._on_resume))
        self._bus = bus

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()

    async def _on_pause(self, message: Message) -> None:
        self._paused = True

    async def _on_resume(self, message: Message) -> None:
        self._paused = False

    async def _on_proposed(self, message: Message) -> None:
        p = message.payload
        action_id = p["action_id"]
        if self._paused:
            self._events.append((action_id, "denied", "paused"))
            await self._bus.publish(Message.new(
                topics.ACTION_DENIED, source="guardian", trace_id=message.trace_id, causation_id=message.id,
                payload={"action_id": action_id, "reasons": ["system is paused"], "layer": "paused"},
                clock=self._clock,
            ))
            return
        args_sha = security.canonical_args_sha256(p["args"])
        expires_at = self._clock() + security.DEFAULT_TOKEN_TTL_SECONDS
        token = security.approval_token(self._secret, action_id, p["tool"], args_sha, expires_at)
        self._events.append((action_id, "approved", token))
        await self._bus.publish(Message.new(
            topics.ACTION_APPROVED, source="guardian", trace_id=message.trace_id, causation_id=message.id,
            payload={"action_id": action_id, "tool": p["tool"], "args_sha256": args_sha,
                     "expires_at": expires_at, "approval_token": token, "mode_at_approval": "guarded"},
            clock=self._clock,
        ))


class _StubExecution:
    """Verifies the token before doing anything -- a forged/expired
    token never reaches `tool.invoked` (recorded here in `events` since
    there is no real tool registry yet)."""

    def __init__(self, *, hmac_secret: bytes, events: list, clock=time.time) -> None:
        self._secret = hmac_secret
        self._events = events
        self._clock = clock
        self._subs = []

    async def start(self, bus: BusClient) -> None:
        self._subs.append(await bus.subscribe(topics.ACTION_APPROVED, self._on_approved, group="execution"))
        self._bus = bus

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()

    async def _on_approved(self, message: Message) -> None:
        p = message.payload
        action_id = p["action_id"]
        ok_token = security.verify_approval_token(
            self._secret, p["approval_token"], action_id=action_id, tool=p["tool"],
            args_sha256=p["args_sha256"], expires_at=p["expires_at"], now=self._clock(),
        )
        if not ok_token:
            self._events.append((action_id, "result", False))
            await self._bus.publish(Message.new(
                topics.ACTION_RESULT, source="execution", trace_id=message.trace_id, causation_id=message.id,
                payload={"action_id": action_id, "ok": False, "output_ref": "", "stdout_preview": "",
                         "duration_ms": 0, "side_effects": [], "error": "invalid_token"},
                clock=self._clock,
            ))
            return
        self._events.append((action_id, "tool_invoked", p["tool"]))
        self._events.append((action_id, "result", True))
        await self._bus.publish(Message.new(
            topics.ACTION_RESULT, source="execution", trace_id=message.trace_id, causation_id=message.id,
            payload={"action_id": action_id, "ok": True, "output_ref": "", "stdout_preview": "noop ok",
                     "duration_ms": 0, "side_effects": []},
            clock=self._clock,
        ))


async def _wait_for(events: list, action_id: str, kind: str, *, timeout: float) -> tuple | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for e in events:
            if e[0] == action_id and e[1] == kind:
                return e
        await asyncio.sleep(0.01)
    return None


def _noop_proposal(action_id: str) -> Message:
    return Message.new(
        topics.ACTION_PROPOSED, source="kernel",
        payload={"action_id": action_id, "tool": NOOP_TOOL, "args": {}, "rationale": "self-check",
                 "proposed_by": "kernel", "scope": {"network": False}, "reversibility": "read_only"},
    )


async def run(*, timeout: float = 5.0) -> SelfCheckResult:
    result = SelfCheckResult()
    ledger = LedgerClient(InMemoryLedgerBackend())
    await ledger.start()
    bus_backend = make_bus_backend(BusConfig())
    await bus_backend.start()
    policy = ReservedTopologyPolicy()  # single-mode: identity is the client object; no token check
    events: list = []
    hmac_secret = security.new_run_secret()

    guardian_client = make_client(bus_backend, source="guardian", ledger=ledger, policy=policy)
    execution_client = make_client(bus_backend, source="execution", ledger=ledger, policy=policy)
    kernel_client = make_client(bus_backend, source="kernel", ledger=ledger, policy=policy)

    guardian = _StubGuardian(hmac_secret=hmac_secret, events=events)
    execution = _StubExecution(hmac_secret=hmac_secret, events=events)
    await guardian.start(guardian_client)
    await execution.start(execution_client)

    try:
        # Step 1 — a legitimate proposal is approved (with a verifiable token) and executed.
        action_id = str(uuid.uuid4())
        await kernel_client.publish(validate(_noop_proposal(action_id)))
        approved = await _wait_for(events, action_id, "approved", timeout=timeout)
        outcome = await _wait_for(events, action_id, "result", timeout=timeout)
        ok = approved is not None and outcome is not None and outcome[2] is True
        result.steps.append(StepResult(
            "noop proposal is approved with a valid token and executed", ok,
            "" if ok else f"approved={approved!r} result={outcome!r}",
        ))

        # Step 2 — a forged approval is rejected by Execution's own token check, never runs the tool.
        forged_id = str(uuid.uuid4())
        forged = Message.new(
            topics.ACTION_APPROVED, source="kernel",
            payload={"action_id": forged_id, "tool": NOOP_TOOL, "args_sha256": "0" * 64,
                     "expires_at": time.time() + 60, "approval_token": "f" * 64, "mode_at_approval": "guarded"},
        )
        await kernel_client.publish(validate(forged))
        forged_result = await _wait_for(events, forged_id, "result", timeout=timeout)
        invoked = await _wait_for(events, forged_id, "tool_invoked", timeout=0.2)
        ok = forged_result is not None and forged_result[2] is False and invoked is None
        result.steps.append(StepResult(
            "a forged approval token is rejected before the tool runs", ok,
            "" if ok else f"result={forged_result!r} invoked={invoked!r}",
        ))

        # Step 3 — while paused, a new proposal is denied at the paused layer.
        await kernel_client.publish(validate(Message.new(
            topics.SYSTEM_PAUSE, source="kernel", payload={"reason": "self-check", "requested_by": "kernel"},
            priority=9,
        )))
        await asyncio.sleep(0.05)
        paused_id = str(uuid.uuid4())
        await kernel_client.publish(validate(_noop_proposal(paused_id)))
        denied = await _wait_for(events, paused_id, "denied", timeout=timeout)
        ok = denied is not None and denied[2] == "paused"
        result.steps.append(StepResult("a proposal made while paused is denied", ok,
                                       "" if ok else f"denied={denied!r}"))
        await kernel_client.publish(validate(Message.new(
            topics.SYSTEM_RESUME, source="kernel", payload={"reason": "self-check", "requested_by": "kernel"},
            priority=9,
        )))
        await asyncio.sleep(0.02)

        # Step 4 — a throwaway subsystem may not subscribe to a reserved topic.
        throwaway = make_client(bus_backend, source="throwaway", ledger=ledger, policy=policy)
        try:
            await throwaway.subscribe(topics.ACTION_PROPOSED, guardian._on_proposed)  # noqa: SLF001 -- proof only
            result.steps.append(StepResult("a throwaway source cannot subscribe to action.proposed", False,
                                           "subscribe unexpectedly succeeded"))
        except PolicyViolation:
            result.steps.append(StepResult("a throwaway source cannot subscribe to action.proposed", True))
    finally:
        await guardian.stop()
        await execution.stop()
        await bus_backend.stop()
        await ledger.stop()

    return result


__all__ = ["SelfCheckResult", "StepResult", "run"]
