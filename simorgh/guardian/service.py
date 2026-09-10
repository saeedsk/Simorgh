"""Guardian's Service (09-guardian.md section 5): the only subsystem the
Kernel/Bus enforcement lets subscribe to `action.proposed`. Runs every
proposal through `pipeline.DEFAULT_PIPELINE`, mints a real HMAC token on
approval, and records the full decision on `action:<action_id>` plus
`guardian:rejected`/`guardian:trust` as the pipeline's checks require.
"""

from __future__ import annotations

import re

import asyncio
from dataclasses import dataclass

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Health

from . import rules as rule_defs
from .api import BudgetStatus, DecisionContext, Proposal, ToolInfo
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


#: How many decided action ids to remember. Enough that a redelivery
#: minutes later is still recognised, small enough that a long-running
#: process does not grow a map nobody prunes.
_MAX_DECIDED = 50_000

#: Argument names whose VALUE must never be printed in a question, even
#: truncated. The name is shown so the person knows a secret is in play.
_SECRET_ARG = ("token", "secret", "password", "passwd", "key", "credential", "api_key")
_ARG_PREVIEW_CHARS = 60
_QUESTION_MAX_CHARS = 400


def _preview_arg(name: str, value: object) -> str:
    """One argument, short enough to read and honest about what it hides."""
    if any(word in name.lower() for word in _SECRET_ARG):
        return f"{name}=<hidden>"
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(str(text).split())
    if len(text) > _ARG_PREVIEW_CHARS:
        # A file body or a patch: say how big rather than showing a slice
        # nobody can judge.
        return f"{name}=<{len(text)} chars>"
    return f"{name}={text}"


def approval_question(tool: str, args: dict, reasons) -> str:
    """What the person is actually being asked to approve.

    It used to be `f"Approve {tool}? ({reasons})"` -- so a human saw
    "Approve install_package? (irreversible action requires human
    approval)" with no package name, no registry, and no sign that
    `allow_new` had switched the typosquat check off. The same sentence
    covered `run_shell` without the command and a write without the
    path. Guardian has the arguments two lines earlier; the person
    deciding was the only party who could not see them (observer,
    2026-09-10).
    """
    parts = [_preview_arg(str(name), value) for name, value in (args or {}).items()]
    detail = ", ".join(parts)
    why = "; ".join(reasons or ())
    question = f"Approve {tool}" + (f" ({detail})" if detail else "") + (f"? [{why}]" if why else "?")
    if len(question) > _QUESTION_MAX_CHARS:
        question = question[:_QUESTION_MAX_CHARS - 1] + "…"
    return question


class Service:
    name = "guardian"
    version = "0.1.0"
    consumes = (
        topics.ACTION_PROPOSED,
        topics.GUARDIAN_REVIEW,
        topics.SYSTEM_STATE_CHANGED,
        topics.TASK_CREATED,
        topics.TASK_COMPLETED,
        topics.TASK_FAILED,
        topics.REFLECT_DRIFT_DETECTED,
        topics.REFLECT_HEALTH_FINDING,
        topics.COGNITION_PROVIDER_STATUS,
        topics.SYSTEM_RESUME,
        topics.GUARDIAN_POSTURE_REQUEST,
        topics.UI_PROMPT_ANSWERED,
    )
    produces = (
        topics.ACTION_APPROVED,
        topics.GUARDIAN_REVIEW_REPLY,
        topics.ACTION_DENIED,
        topics.ACTION_NEEDS_HUMAN,
        topics.UI_PROMPT,
        topics.GUARDIAN_POSTURE_CHANGED,
        topics.GUARDIAN_POSTURE_REPLY,
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
        self._lock_expiry: asyncio.Task | None = None
        self._degraded_detail = ""
        # One decision per action id. The gate had none, so a duplicate
        # `action.proposed` -- which an at-least-once bus is entitled to
        # deliver -- was decided twice and minted a second token. The
        # second token then failed Execution's replay guard, so a real,
        # successful action was ALSO reported as `action.denied` with
        # reason "signature replayed", and Execution marked itself
        # degraded over a redelivery. Orchestration takes whichever of
        # result and denial lands first, so the model could be told the
        # action it had just run was refused for a token-integrity
        # failure (observer, 2026-09-10). Nothing wrong ever executed --
        # Execution pins the args from the FIRST proposal and fails
        # closed -- but a tamper alarm that fires on ordinary
        # redelivery is worse than no alarm.
        #
        # In memory and per process: a Guardian restart forgets, and so
        # does Execution's own replay guard, so the two stay consistent.
        # action_id -> (fingerprint, answered). `answered` matters: the
        # claim is taken before the work, and if anything between the
        # claim and the verdict raises -- an oversized-args spill whose
        # `put_blob` fails is the path a real patch takes -- the id
        # stayed claimed and the legitimate retry was then dropped as a
        # duplicate, answering nobody. Before this dedupe existed, that
        # retry was answered (observer, 2026-09-10, on the fix from the
        # same morning).
        self._decided: dict[str, tuple[str, bool]] = {}
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
        # `guardian.review` had a caller and no listener: Verification
        # asks for one on every self-patch and skill review
        # (verification/service.py::_review), waited out the full action
        # timeout, and silently degraded to `approved=False, ok=False`.
        # A gate that has never run is not a gate (audit, 2026-09-08).
        self._subs.append(await ctx.bus.subscribe(topics.GUARDIAN_REVIEW, self._on_review))
        self._subs.append(await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_CREATED, self._on_task_created))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_outcome))
        self._subs.append(await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_outcome))
        self._subs.append(await ctx.bus.subscribe(topics.REFLECT_DRIFT_DETECTED, self._on_drift_detected))
        self._subs.append(await ctx.bus.subscribe(topics.REFLECT_HEALTH_FINDING, self._on_health_finding))
        self._subs.append(await ctx.bus.subscribe(topics.COGNITION_PROVIDER_STATUS, self._on_provider_status))
        self._subs.append(await ctx.bus.subscribe(topics.SYSTEM_RESUME, self._on_resume))
        self._subs.append(await ctx.bus.subscribe(topics.GUARDIAN_POSTURE_REQUEST, self._on_posture_request))
        self._subs.append(await ctx.bus.subscribe(topics.UI_PROMPT_ANSWERED, self._on_prompt_answered))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()
        if self._lock_expiry is not None and not self._lock_expiry.done():
            self._lock_expiry.cancel()
            self._lock_expiry = None

    async def health(self) -> Health:
        if self._degraded_detail:
            return Health.degraded(self._degraded_detail)
        return Health.ok(f"posture={self._posture.level}")

    # -- projections ---------------------------------------------------

    async def _rebuild_rejected_index(self) -> None:
        events = await self._ctx.ledger.read(REJECTED_STREAM)
        self._rejected_excerpts = [e.payload["code_excerpt"] for e in events if e.type == "rejected"]

    async def _on_review(self, message: Message) -> None:
        """Review a body of code before it is applied.

        The same denylist that guards a live `apply_source_patch`, run
        over the candidate ahead of time. Deliberately narrow: this
        answers "does this code do something we forbid outright", not
        "is this code good" -- judging quality is Verification's job and
        it is the one asking.
        """
        payload = message.payload
        code = ""
        ref = payload.get("code_ref") or ""
        if ref:
            try:
                code = (await self._ctx.ledger.get_blob(ref)).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 -- an unreadable body is reviewable as "no evidence"
                code = ""
        if not code:
            await self._ctx.bus.reply(message, type=topics.GUARDIAN_REVIEW_REPLY, payload={
                "approved": False, "reasons": ["no code to review"], "layers_run": ["denylist"],
            })
            return
        reasons = [
            f"denied: {explanation}"
            for pattern, explanation in self._config.denylist.items()
            if re.search(pattern, code)
        ]
        await self._ctx.bus.reply(message, type=topics.GUARDIAN_REVIEW_REPLY, payload={
            "approved": not reasons, "reasons": reasons, "layers_run": ["denylist"],
        })

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
        """Live-caught (observer, 2026-09-09): this used to bail out
        entirely -- no ledger entry, no reason recorded, nothing -- the
        instant `to` equaled the *current* level, which is true on every
        boot for `guarded`-level triggers (health-critical default,
        drift-detected, budget-pressure) since `baseline_posture` is
        itself `"guarded"` by default. `Posture.tighten` was already
        written to keep recording the reason on a same-level or
        no-op-rank tighten (see its own tests); this wrapper's stricter
        equality guard threw that audit trail away before `Posture` ever
        saw it, and also fed `GUARDIAN_POSTURE_CHANGED` the *requested*
        `to` rather than the posture's real resulting level -- so a
        `guarded`-targeted trigger arriving while already `locked` would
        have wrongly announced `mode: "guarded"`. `posture.reasons` also
        feeds `trust_score` in `_on_posture_request` (the `budget`
        command's answer), so the dropped reason silently reported
        "fully trusted" right after a critical health finding, drift
        detection, or budget-pressure warning that changed nothing about
        the posture level. Record the reason unconditionally; only
        announce a change (and arm a lock-expiry) when the level
        actually moved."""
        before = self._posture.level
        self._posture.tighten(to, reason)
        await self._ctx.ledger.append(TRUST_STREAM, self._event(TRUST_STREAM, "tightened", {"to": to, "reason": reason}))
        if self._posture.level == before:
            return
        await self._ctx.bus.publish(Message.new(
            topics.GUARDIAN_POSTURE_CHANGED, source="guardian",
            payload={"mode": self._posture.level, "trust_score": 0.0, "reason": reason},
        ))
        if self._posture.level == "locked" and self._config.lock_ttl_s > 0:
            self._arm_lock_expiry()

    def _arm_lock_expiry(self) -> None:
        if self._lock_expiry is not None and not self._lock_expiry.done():
            self._lock_expiry.cancel()
        self._lock_expiry = asyncio.ensure_future(self._expire_lock(self._config.lock_ttl_s))

    async def _expire_lock(self, ttl_s: float) -> None:
        """A lock is a circuit breaker, not a verdict: the creator
        (2026-09-07) asked for autonomy that doesn't stall until a human
        types `resume`. After `lock_ttl_s` a still-locked posture goes
        back to baseline on its own -- the only non-human loosening path,
        and only ever from `locked`, never from `guarded` (a budget or
        drift tightening stays until a human or a restart)."""
        await self._ctx.clock.sleep(ttl_s)
        if self._posture.level != "locked":
            return
        self._posture.reset_to_baseline()
        self._failure_streak.clear()
        await self._ctx.ledger.append(TRUST_STREAM, self._event(TRUST_STREAM, "reset_to_baseline", {"by": "ttl"}))
        await self._ctx.bus.publish(Message.new(
            topics.GUARDIAN_POSTURE_CHANGED, source="guardian",
            payload={"mode": self._posture.level, "trust_score": 0.0, "reason": f"lock expired after {ttl_s:.0f}s"},
        ))

    # -- 09-guardian.md section 5.3's other tightening triggers --------------
    # `_on_task_outcome` above already wires the failure-streak trigger;
    # these three plus `_on_resume` complete the table. Each calls the
    # same `_tighten`, whose own `Posture.tighten` never raises the level
    # -- so an event here can only ever hold or lower posture, matching
    # "there is deliberately no message that loosens posture" even though
    # none of these handlers checks the current level itself.

    async def _on_drift_detected(self, message: Message) -> None:
        p = message.payload
        await self._tighten("guarded", f"drift detected on task {p.get('task_id', '')}: {p.get('evidence', '')}")

    async def _on_health_finding(self, message: Message) -> None:
        p = message.payload
        if p.get("severity") == "critical":
            # `guarded` by default now (config.py's own note): live-caught,
            # a floor-reply-pinned valence locked the whole session for
            # hours over what was really a budget problem.
            await self._tighten(self._config.health_critical_tightens_to, f"critical health finding: {p.get('detail', '')}")

    async def _on_provider_status(self, message: Message) -> None:
        p = message.payload
        fraction = _fraction_used(p.get("budget") or {}, p.get("available", True))
        self._budgets[p["provider"]] = BudgetStatus(provider=p["provider"], fraction_used=fraction)
        if fraction >= self._config.budget_pressure_tighten_at:
            await self._tighten("guarded", f"{p['provider']} budget at {fraction:.0%} of window cap")

    async def _on_resume(self, message: Message) -> None:
        """The only loosening path (09-guardian.md section 5.3): a human
        action (`system.resume`), never a message any autonomous
        subsystem can emit -- `SYSTEM_RESUME`'s publisher allow-list
        (`contracts/topics.py`) already restricts it to interface/kernel."""
        if self._posture.level == self._posture.baseline and not self._posture.reasons:
            return
        self._posture.reset_to_baseline()
        self._failure_streak.clear()
        if self._lock_expiry is not None and not self._lock_expiry.done():
            self._lock_expiry.cancel()
        await self._ctx.ledger.append(TRUST_STREAM, self._event(TRUST_STREAM, "reset_to_baseline", {"by": "human"}))
        await self._ctx.bus.publish(Message.new(
            topics.GUARDIAN_POSTURE_CHANGED, source="guardian",
            payload={"mode": self._posture.level, "trust_score": 1.0, "reason": "system.resume"},
        ))

    async def _on_prompt_answered(self, message: Message) -> None:
        """Resolves a real human answer to a `needs_human` escalation
        (`_on_proposed`'s own comment on the matching `ui.prompt` publish
        has the "why" -- `action.needs_human` alone was never
        answerable). `prompt_id` doubles as `action_id`; any other
        `ui.prompt` (Planning's own plan-mode approval, for instance)
        answers here too but is harmlessly ignored -- its `prompt_id`
        never names a real `action:<id>` stream with a `received` event,
        so the lookup below just finds nothing and returns. The full
        original proposal is read back from the Ledger, the same
        re-fetch-don't-trust-the-message pattern `execution/README.md`'s
        `_fetch_proposed_args` already uses for approved actions --
        Guardian's own in-memory state discarded the proposal the moment
        it escalated (`_on_proposed`'s `needs_human` branch just
        `return`s), but the `received` event this same method appended
        beforehand is still there."""
        p = message.payload
        action_id = p.get("prompt_id", "")
        if not action_id:
            return
        stream = f"action:{action_id}"
        events = await self._ctx.ledger.read(stream)
        received = next((e for e in events if e.type == "received"), None)
        if received is None:
            return  # not one of ours -- a different prompt_id namespace entirely
        if any(e.type == "answered" for e in events):
            return  # already resolved -- a stray duplicate (e.g. the timeout watchdog raced a real answer)

        proposal = received.payload["proposal"]
        answer = p.get("answer", "no")
        if answer != "yes":
            await self._ctx.ledger.append(stream, self._event(stream, "answered", {"answer": answer, "outcome": "denied"}))
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED, {"action_id": action_id, "reasons": ["human declined"], "layer": "policy"},
                source="guardian",
            ))
            return
        if self._system_state in ("paused", "stopping"):
            await self._ctx.ledger.append(stream, self._event(stream, "answered", {"answer": answer, "outcome": "denied"}))
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED, {"action_id": action_id, "reasons": [f"system is {self._system_state}"], "layer": "policy"},
                source="guardian",
            ))
            return

        token, expires_at, args_sha256 = self._tokens.issue(action_id, proposal["tool"], proposal["args"])
        await self._ctx.ledger.append(stream, self._event(stream, "answered", {"answer": answer, "outcome": "approved"}))
        await self._ctx.bus.publish(message.caused(
            topics.ACTION_APPROVED,
            {"action_id": action_id, "tool": proposal["tool"], "args_sha256": args_sha256, "expires_at": expires_at,
             "approval_token": token, "mode_at_approval": self._config.mode},
            source="guardian",
        ))

    async def _on_posture_request(self, message: Message) -> None:
        """`guardian.posture.request` -> `.reply` (contracts/messages/
        guardian.py). Live-caught (post-cutover review, 2026-09-06): the
        pair existed in the catalog and Interface's `budget` command sent
        the request, but nothing ever answered -- the command timed out
        every time. The reply is the same projection `health()` reports."""
        await self._ctx.bus.reply(message, type=topics.GUARDIAN_POSTURE_REPLY, payload={
            "mode": self._posture.level,
            "trust_score": 1.0 if self._posture.level == self._posture.baseline and not self._posture.reasons else 0.0,
            "tightened_by": list(self._posture.reasons),
        })

    # -- the pipeline ----------------------------------------------------

    async def _spill_oversized_args(self, proposal: dict) -> dict:
        """A copy of the proposal safe to record: any string argument the
        Ledger would refuse inline is stored as a blob and replaced by its
        ref. Execution resolves the refs back (`_fetch_proposed_args`), so
        the verifier still hashes the real arguments."""
        ledger = self._ctx.ledger
        threshold = getattr(ledger, "inline_threshold", 4096)
        args = proposal.get("args")
        if not isinstance(args, dict):
            return proposal
        spilled: dict = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > threshold:
                spilled[key] = await ledger.put_blob(value.encode("utf-8"), content_type="text/plain")
            else:
                spilled[key] = value
        return {**proposal, "args": spilled}

    @staticmethod
    def _fingerprint(payload: dict) -> str:
        """What makes two proposals the same action."""
        from simorgh.contracts import security

        try:
            args_hash = security.canonical_args_sha256(payload.get("args") or {})
        except Exception:  # noqa: BLE001 -- an unhashable payload is still comparable by repr
            args_hash = repr(payload.get("args"))
        return f"{payload.get('tool', '')}:{args_hash}"

    async def _record_duplicate(self, action_id: str, why: str) -> None:
        stream = f"action:{action_id}"
        try:
            await self._ctx.ledger.append(stream, self._event(stream, "duplicate", {"why": why}))
        except Exception:  # noqa: BLE001 -- a note about a duplicate must never break the gate
            pass

    async def _on_proposed(self, message: Message) -> None:
        p = message.payload
        action_id = p["action_id"]
        fingerprint = self._fingerprint(p)
        seen = self._decided.get(action_id)
        if seen is not None and not seen[1]:
            # Claimed and never answered: whatever went wrong last time
            # left nobody a reply. Let this delivery through.
            self._decided.pop(action_id, None)
            seen = None
        if seen is not None:
            if seen[0] == fingerprint:
                # The same proposal again: already decided, already
                # answered. Recorded so the stream shows what happened,
                # and NOT re-answered, because the answer is already on
                # its way to whoever asked.
                await self._record_duplicate(action_id, "identical proposal redelivered")
                return
            # A different action wearing an id that has already been
            # decided. Denied at the gate rather than left to fail as a
            # token mismatch downstream, which reads as tampering.
            await self._record_duplicate(action_id, "same id, different action")
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED,
                {"action_id": action_id, "layer": "policy", "tool": p.get("tool", ""),
                 "reasons": ["this action id has already been decided; an id may not be reused "
                             "for a different call"]},
                source="guardian",
            ))
            return
        # Claimed before the first await, so two deliveries racing each
        # other cannot both get through. Bounded, oldest first: an
        # unbounded map is a leak in a process meant to run for months
        # (`security.ReplayGuard` beside it evicts at 10,000).
        if len(self._decided) >= _MAX_DECIDED:
            for stale in list(self._decided)[: max(1, _MAX_DECIDED // 10)]:
                self._decided.pop(stale, None)
        self._decided[action_id] = (fingerprint, False)
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
            # Live-caught 2026-09-07: this was never passed, so `ctx.tool`
            # was always None, and `ModeRule`'s `bool(ctx.tool and
            # ctx.tool.read_only)` was therefore always False -- every
            # tool looked like a writing tool. In plan mode that denies
            # *everything*, `read_file` and `list_dir` included, which are
            # the only tools a plan session has. So plan sessions could
            # not read a single file, which is why all 20 of the creator's
            # projects sat at 0/0 steps: nothing could ever produce a plan
            # to decompose. The proposal already carries the declared
            # reversibility Execution registered for that tool, which is
            # exactly the fact the rule needs.
            tool=ToolInfo(
                name=proposal.tool,
                read_only=proposal.reversibility == "read_only",
                reversibility=proposal.reversibility,
            ),
        )

        stream = f"action:{action_id}"
        # Record the proposal with any oversized argument spilled to a
        # blob first. The Ledger refuses inline strings over its
        # `inline_threshold` (4096 chars), and this append used to hand it
        # the whole proposal -- a patch's complete new file body included
        # -- so for any real-sized file it raised *before* `decide()` ran,
        # the bus retried and dead-lettered it, and no verdict of any kind
        # was ever published. The proposer waited out its timeout and was
        # told "no response". Found independently by four watched trials,
        # 2026-09-07: Sim structurally could not patch 89 of its 223
        # source files, and the failure was invisible three ways over
        # (the dead-letter record hit the same cap).
        #
        # A logging failure must never cancel a decision either, so the
        # append is guarded: if the Ledger still refuses, the proposal is
        # denied with the real reason rather than dropped.
        recorded = await self._spill_oversized_args(p)
        try:
            await self._ctx.ledger.append(stream, self._event(stream, "received", {"proposal": recorded}))
        except Exception as exc:  # noqa: BLE001 -- a proposal Guardian cannot record is refused, never lost
            # Undecided after all: let a genuine retry be heard.
            self._decided.pop(action_id, None)
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED,
                {"action_id": action_id, "reasons": [f"could not record the proposal: {exc}"],
                 "layer": "policy", "tool": proposal.tool},
                source="guardian",
            ))
            return
        verdict = await self._pipeline.decide(proposal, ctx)
        # NOT answered here. This line used to read "answered from here
        # on: every branch below publishes something," and several
        # things below it raise BEFORE anything is published: the
        # `decided` append (the same Ledger whose failure the `received`
        # append above is explicitly guarded against), the rejected
        # append inside `_remember_rejection`, `approval_question`,
        # `tokens.issue`, and `bus.publish` itself. Any of those left
        # `answered=True` on an action nobody had been told about, and
        # the legitimate retry was then dropped as a duplicate --
        # exactly the bug this dedupe's own fix says it closed, three
        # lines further down. Reproduced 2026-09-10 by failing only the
        # `decided` append: the first delivery answered nobody and the
        # retry was swallowed too.
        #
        # The claim is marked answered where the invariant is true:
        # right after a publish has actually succeeded, on each branch.
        decided = {"kind": verdict.kind, "layer": verdict.layer}
        if verdict.notes:
            # What a rule noticed and chose not to act on -- shellcheck's
            # non-dangerous findings, say. `ShellcheckRule` has always
            # said these ride along "so the finding is visible in the
            # trace"; until they were written here that was not true of
            # anywhere.
            decided["notes"] = list(verdict.notes)
        await self._ctx.ledger.append(stream, self._event(stream, "decided", decided))

        if verdict.kind == "denied":
            if verdict.layer in ("protected", "denylist", "immunity"):
                await self._remember_rejection(proposal, verdict.reasons, verdict.layer, source="action")
            reasons = () if verdict.layer == "classifier" else verdict.reasons
            wire_layer = _WIRE_DENY_LAYER.get(verdict.layer, verdict.layer)
            payload = {"action_id": action_id, "reasons": list(reasons), "layer": wire_layer, "tool": proposal.tool}
            # Carry the task_id through so a consumer that tracks
            # per-task state (Reflection's DriftTracker) can attribute
            # this denial to the task it happened on -- needed for
            # layer="scope" denials to ever reach observe_scope_denial().
            if proposal.task_id:
                payload["task_id"] = proposal.task_id
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_DENIED,
                payload,
                source="guardian",
            ))
            self._decided[action_id] = (fingerprint, True)
            return

        if verdict.kind == "needs_human":
            question = approval_question(p["tool"], p.get("args") or {}, verdict.reasons)
            await self._ctx.bus.publish(message.caused(
                topics.ACTION_NEEDS_HUMAN,
                {"action_id": action_id, "question": question, "options": ["yes", "no"], "default": "no"},
                source="guardian",
            ))
            # Somebody has been told. The `ui.prompt` below is how the
            # answer gets back, not whether one was given.
            self._decided[action_id] = (fingerprint, True)
            # Live-caught (the creator, real use: answered "yes" three
            # separate times and every one silently resolved "no"
            # instead): `action.needs_human` alone was never actually
            # answerable -- nothing consumed a reply to it. `ui.prompt`/
            # `ui.prompt_answered` already existed as a real, working
            # question/answer pair (Interface renders it and now
            # actually waits, `interface/service.py`'s own docstring);
            # `prompt_id = action_id` is what lets `_on_prompt_answered`
            # below find its way back to this exact pending proposal.
            await self._ctx.bus.publish(message.caused(
                topics.UI_PROMPT,
                {"prompt_id": action_id, "question": question, "options": ["yes", "no"],
                 "timeout_s": self._config.human_prompt_timeout_s, "default": "no"},
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
        self._decided[action_id] = (fingerprint, True)

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


def _fraction_used(budget: dict, available: bool) -> float:
    """`cognition.provider.status`'s `budget` object -> Guardian's own
    0..1+ `fraction_used` (`api.BudgetStatus`). Prefers spend over the
    window's `max_spend_usd`, falls back to `calls`/`max_calls`, and
    reports 0.0 (never fabricated pressure) when neither cap is
    configured -- "no data" and "not exhausted" are the same signal
    here, matching `BudgetRule`'s own "no data must not be treated as
    exhausted" (this package's README)."""
    if budget.get("exhausted") or not available:
        return 1.0
    max_spend, spend = budget.get("max_spend_usd"), budget.get("spend_usd")
    if isinstance(max_spend, (int, float)) and max_spend and isinstance(spend, (int, float)):
        return spend / max_spend
    max_calls, calls = budget.get("max_calls"), budget.get("calls")
    if isinstance(max_calls, (int, float)) and max_calls and isinstance(calls, (int, float)):
        return calls / max_calls
    return 0.0
