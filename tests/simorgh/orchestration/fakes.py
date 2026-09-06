"""Fakes for the subsystems Orchestration depends on but does not own
(16 section 9). Each is a real bus subscriber speaking the real message
shapes, not a mock of `Worker`/`SessionRunner` internals.
"""

from __future__ import annotations

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message


class FakeCognition:
    """Replies to `cognition.think` with a scripted sequence, one reply
    per call (last one repeats). `[{"text": "..."}]` or
    `[{"tool_calls": [{"tool": "read_file", "args": {"path": "x"}}]}]`.
    """

    def __init__(self, bus, script: list[dict], *, floor: bool = False) -> None:
        self._bus = bus
        self._script = script
        self._floor = floor
        self.calls: list[Message] = []
        self._sub = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self) -> None:
        if self._sub:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        self.calls.append(message)
        i = min(len(self.calls) - 1, len(self._script) - 1)
        step = self._script[i] if self._script else {"text": ""}
        payload = {
            "text": step.get("text", ""), "tool_calls": step.get("tool_calls", []),
            "provider": "fake", "cost_usd": 0.0, "tokens": 10,
            "floor": self._floor, "non_answer": False,
        }
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload=payload)


class FakeGuardianExecution:
    """Approves and "runs" every proposed action trivially (echoes
    `args` back as the result) -- stands in for real Guardian+Execution,
    which are built by a different track this same session.
    """

    def __init__(self, bus, *, deny: bool = False) -> None:
        self._bus = bus
        self._deny = deny
        self.proposals: list[Message] = []
        self._sub = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self) -> None:
        if self._sub:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        self.proposals.append(message)
        if self._deny:
            reply = message.caused(topics.ACTION_DENIED, {
                "action_id": message.payload["action_id"], "reasons": ["test denial"], "layer": "policy",
            }, source="guardian")
            await self._bus.publish(reply)
            return
        result = message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": True,
            "output_ref": "", "stdout_preview": f"ran {message.payload['tool']}",
            "duration_ms": 1, "side_effects": [],
        }, source="execution")
        await self._bus.publish(result)


class FakeVerification:
    def __init__(self, bus, verdicts: list[str] | None = None) -> None:
        self._bus = bus
        self._verdicts = verdicts or ["pass"]
        self.requests: list[Message] = []
        self._sub = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.VERIFY_REQUESTED, self._on)

    async def stop(self) -> None:
        if self._sub:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        self.requests.append(message)
        i = min(len(self.requests) - 1, len(self._verdicts) - 1)
        verdict = self._verdicts[i]
        feedback = {"items": [{"what": "docstring", "why": "dropped", "suggested_fix": "restore it"}]} if verdict == "fail" else None
        payload = {
            "verification_id": message.payload["verification_id"], "task_id": message.payload["task_id"],
            "verdict": verdict, "checklist": [],
            "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0},
            "mechanical": {},
        }
        if feedback:
            payload["feedback"] = feedback
        reply = message.caused(topics.VERIFY_RESULT, payload, source="verification")
        await self._bus.publish(reply)


class FakePlanning:
    """Grants any `task.claim` for a task it was told about via
    `add_task`, mirroring Planning's request/reply shape (07 section 3)."""

    def __init__(self, bus) -> None:
        self._bus = bus
        self._tasks: dict[str, dict] = {}
        self._sub = None

    def add_task(self, task_id: str, **fields) -> None:
        self._tasks[task_id] = fields

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.TASK_CLAIM, self._on)

    async def stop(self) -> None:
        if self._sub:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        task_id = message.payload["task_id"]
        task = self._tasks.get(task_id)
        payload = {"granted": task is not None, "task": task or {}}
        await self._bus.reply(message, type=topics.TASK_CLAIM_REPLY, payload=payload)
