"""Guardian's Service (09-guardian.md section 5): the only subsystem the
Kernel/Bus enforcement lets subscribe to `action.proposed`. Runs every
proposal through `pipeline.DEFAULT_PIPELINE`, mints a real HMAC token on
approval, and records the full decision on `action:<action_id>` plus
`guardian:rejected`/`guardian:trust` as the pipeline's checks require.
"""

from __future__ import annotations

from dataclasses import dataclass

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Health

from . import rules as rule_defs
from .api import BudgetStatus, DecisionContext, Proposal
from .charter import load_charter
from .config import Config
from .pipeline import Pipeline
from .posture import Posture
from .tokens import TokenIssuer

REJECTED_STREAM = "guardian:rejected"
TRUST_STREAM = "guardian:trust"

# `action.denied`'s wire schema (contracts/messages/action.py's DENY_LAYER)
# only enumerates {policy, denylist, immunity, budget, paused, scope,
# classifier, token} -- a coarser set than the pipeline's own internal
# rule layers (09-guardian.md section 5.1's pseudocode names `mode`,
# `protected`, and `reversibility` as distinct layers). Those three
# collapse to the contract's general-purpose `policy` bucket on the wire;
# the specific rule that fired is still visible in `reasons`. This is a
# genuine spec/contract naming gap, noted in 09-guardian.md section 12
# rather than resolved by editing the shared contract unilaterally.
_WIRE_DENY_LAYER = {"mode": "policy", "protected": "policy", "reversibility": "policy"}


@dataclass
class _TaskInfo:
    mode: str = "execute"
    origin: str = "human"


class Service:
    name = "guardian"
    version = "0.1.0"
    consumes = (
        topics.ACTION_PROPOSED,
        topics.SYSTEM_STATE_CHANGED,
        topics.TASK_CREATED,
        topics.TASK_COMPLETED,
        topics.TASK_FAILED,
    )
    produces = (
        topics.ACTION_APPROVED,
        topics.ACTION_DENIED,
        topics.ACTION_NEEDS_HUMAN,
        topics.GUARDIAN_POSTURE_CHANGED,
    )

    def __init__(self, *, config: Config | None = None, pipeline: Pipeline | None = None) -> None:
        self._config = config or Config()
        self._pipeline = pipeline or Pipeline(rule_defs.DEFAULT_PIPELINE)
        self._posture = Posture(level=self._config.baseline_posture, baseline=self._config.baseline_posture)
        self._system_state = "running"
        self._tasks: dict[str, _TaskInfo] = {}
        self._budgets: dict[str, BudgetStatus] = {}
        self._rejected_excerpts: list[str] = []
        self._failure_streak: dict[str, int] = {}
        self._subs: list = []
        self._degraded_detail = ""
        self.charter_text = ""

    async def start(self, ctx) -> None:
        self._ctx = ctx
        secret = ctx.secrets.get("__hmac__")
        if not secret:
            raise RuntimeError("guardian: no guardian_hmac secret in Context -- refusing to start")
        self._secret = bytes.fromhex(secret) if isinstance(secret, str) else secret
        self._tokens = TokenIssuer(self._secret, ttl_s=self._config.approval_ttl_s, clock=ctx.clock)
        self.charter_text = load_charter()

        await self._rebuild_rejected_index()

        self._subs.append(await ctx.bus.subscribe(topics.ACTION_PROPOSED, self._on_proposed, group="guardian"))
        self._subs.append(await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_CREATED, self._on_task_created))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_outcome))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_outcome))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()

    async def health(self) -> Health:
        if self._degraded_detail:
            return Health.degraded(self._degraded_detail)
        return Health.ok(f"posture={self._posture.level}")

    # -- projections ---------------------------------------------------

    async def _rebuild_rejected_index(self) -> None:
        events = await self._ctx.ledger.read(REJECTED_STREAM)
        self._rejected_excerpts = [e.payload["code_excerpt"] for e in events if e.type == "rejected"]

    async def _on_state_changed(self, message: Message) -> None:
        self._system_state = message.payload["state"]

    async def _on_task_created(self, message: Message) -> None:
        p = message.payload
        self._tasks[p["task_id"]] = _TaskInfo(mode=p.get("mode", "execute"), origin=p.get("origin", "human"))

    async def _on_task_outcome(self, message: Message) -> None:
        p = message.payload
        origin = self._tasks.get(p.get("task_id", ""), _TaskInfo()).origin
        if origin not in self._config.autonomous_origins:
            return
        succeeded = p.get("succeeded")
        if succeeded is False or message.type == topics.TASK_FAILED:
            self._failure_streak[origin] = self._failure_streak.get(origin, 0) + 1
            if self._failure_streak[origin] >= self._config.max_consecutive_failures:
                await self._tighten("locked", f"{self._failure_streak[origin]} consecutive failed {origin} actions")
        elif succeeded is True:
            self._failure_streak[origin] = 0

    async def _tighten(self, to: str, reason: str) -> None:
        if self._posture.level == to:
            return
        self._posture.tighten(to, reason)
        await self._ctx.ledger.append(TRUST_STREAM, self._event(TRUST_STREAM, "tightened", {"to": to, "reason": reason}))
        await self._ctx.bus.publish(Message.new(
            topics.GUARDIAN_POSTURE_CHANGED, source="guardian",
            payload={"mode": to, "trust_score": 0.0, "reason": reason},
        ))

    # -- the pipeline ----------------------------------------------------

    async def _on_proposed(self, message: Message) -> None:
        p = message.payload
        action_id = p["action_id"]
        task = self._tasks.get(p.get("task_id") or "", _TaskInfo())
        proposal = Proposal(
            action_id=action_id, tool=p["tool"], args=p["args"], scope=p["scope"],
            reversibility=p["reversibility"], rationale=p["rationale"], proposed_by=p["proposed_by"],
            task_id=p.get("task_id"), task_mode=task.mode, origin=task.origin,
        )
        ctx = DecisionContext(
            now=self._ctx.clock.now(), system_state=self._system_state, posture=self._posture,
            config=self._config, budgets=dict(self._budgets),
            rejected_similarity=self._rejected_similarity,
        )

        stream = f"action:{action_id}"
        await self._ctx.ledger.append(stream, self._event(stream, "received", {"proposal": p}))
        verdict = await self._pipeline.decide(proposal, ctx)
        await self._ctx.ledger.append(stream, self._event(
            stream, "decided", {"kind": verdict.kind, "layer": verdict.layer},
        ))

        if verdict.kind == "denied":
            if verdict.layer in ("protected", "denylist", "immunity"):
                await self._remember_rejection(proposal, verdict.reasons, verdict.layer, source="action")
            reasons = () if verdict.layer == "classifier" else verdict.reasons
            wire_layer = _WIRE_DENY_LAYER.get(verdict.layer, verdict.layer)
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED, {"action_id": action_id, "reasons": list(reasons), "layer": wire_layer},
                source="guardian",
            ))
            return

        if verdict.kind == "needs_human":
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_NEEDS_HUMAN,
                {"action_id": action_id, "question": f"Approve {p['tool']}? ({'; '.join(verdict.reasons)})",
                 "options": ["yes", "no"], "default": "no"},
                source="guardian",
            ))
            return

        token, expires_at, args_sha256 = self._tokens.issue(action_id, p["tool"], p["args"])
        await self._ctx.bus.publish(message.caused(
            topics.ACTION_APPROVED,
            {"action_id": action_id, "tool": p["tool"], "args_sha256": args_sha256, "expires_at": expires_at,
             "approval_token": token, "mode_at_approval": self._config.mode},
            source="guardian",
        ))

    def _rejected_similarity(self, code: str):
        return rule_defs.similarity(code, self._rejected_excerpts, self._config.immunity_similarity_threshold)

    async def _remember_rejection(self, proposal: Proposal, reasons, layer: str, *, source: str) -> None:
        code = proposal.args.get("code")
        if not isinstance(code, str) or not code:
            return
        excerpt = code[:4096]
        await self._ctx.ledger.append(REJECTED_STREAM, self._event(REJECTED_STREAM, "rejected", {
            "subject": proposal.args.get("subject", ""), "code_sha": _sha256(code),
            "code_excerpt": excerpt, "reasons": list(reasons), "layer": layer, "source": source,
        }))
        self._rejected_excerpts.append(excerpt)

    def _event(self, stream: str, type: str, payload: dict):
        from simorgh.contracts.envelope import Event
        return Event(stream=stream, type=type, ts=self._ctx.clock.now(), trace_id="", causation_id=None, payload=payload)


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
