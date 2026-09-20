"""What Sim has decided to do differently, and whether it worked (stage 8 item 4).

A lesson that is only ever written into a memory record changes nothing:
the next session recalls it if the vocabulary happens to match. A policy
is the durable form -- a rule, a skill, a routing change, a patch -- with
the evidence that motivated it, the baseline it was measured against, and
a verdict.

Three things keep this from becoming a machine for talking itself into
changes:

- **Evidence is refs, not prose.** A policy names the failures it came
  from, so anyone can read them.
- **A policy is adopted only against a measurement.** `baseline` and
  `result` are on the record, and `adopt` refuses without them.
- **Everything is reversible and time-bounded.** A policy has a TTL and
  can be retired, which is a status change and another event, never a
  deletion.
"""

from __future__ import annotations

import time

from simorgh.contracts import topics
import uuid
from dataclasses import dataclass, field, replace

STREAM = "growth:policies"
KINDS = ("rule", "skill", "routing", "patch")
STATUSES = ("proposed", "adopted", "refused", "retired")

#: A policy nobody has re-measured in this long is retired: the world it
#: was measured in was four weeks ago.
DEFAULT_TTL_S = 28 * 24 * 3600.0


@dataclass(frozen=True)
class Policy:
    id: str
    kind: str
    task_type: str
    body: str
    status: str = "proposed"
    evidence_refs: tuple[str, ...] = ()
    baseline: float | None = None
    result: float | None = None
    evaluated_on: int = 0        # how many held-out cases it was measured on
    proposed_at: float = 0.0
    adopted_at: float | None = None
    retired_at: float | None = None
    why: str = ""
    ttl_s: float = DEFAULT_TTL_S
    #: How many outcomes the task type had when this was adopted, so
    #: "has it got worse since?" can be asked of the outcomes that came
    #: AFTER it (stage 8 item 6). Comparing against all of history
    #: would judge a policy on work that predates it.
    samples_at_adoption: int = 0

    @property
    def live(self) -> bool:
        return self.status == "adopted" and self.retired_at is None

    def expired(self, now: float) -> bool:
        return self.live and self.adopted_at is not None and (now - self.adopted_at) > self.ttl_s

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "task_type": self.task_type, "body": self.body,
                "status": self.status, "evidence_refs": list(self.evidence_refs), "baseline": self.baseline,
                "result": self.result, "evaluated_on": self.evaluated_on,
                "samples_at_adoption": self.samples_at_adoption, "proposed_at": self.proposed_at,
                "adopted_at": self.adopted_at, "retired_at": self.retired_at, "why": self.why,
                "ttl_s": self.ttl_s}


def from_dict(data: dict) -> Policy:
    return Policy(
        id=str(data.get("id") or ""), kind=str(data.get("kind") or "rule"),
        task_type=str(data.get("task_type") or ""), body=str(data.get("body") or ""),
        status=str(data.get("status") or "proposed"),
        evidence_refs=tuple(str(r) for r in (data.get("evidence_refs") or ())),
        baseline=data.get("baseline"), result=data.get("result"),
        evaluated_on=int(data.get("evaluated_on") or 0), proposed_at=float(data.get("proposed_at") or 0.0),
        samples_at_adoption=int(data.get("samples_at_adoption") or 0),
        adopted_at=data.get("adopted_at"), retired_at=data.get("retired_at"),
        why=str(data.get("why") or ""), ttl_s=float(data.get("ttl_s") or DEFAULT_TTL_S),
    )


class PolicyStore:
    """The policies, in memory over an append-only stream."""

    def __init__(self, ledger=None, *, clock=None, publish=None) -> None:
        self._ledger = ledger
        self._clock = clock or time.time
        self._policies: dict[str, Policy] = {}
        self._cursor = 0
        #: `async (topic, payload) -> None`, so a change to how Sim
        #: works is visible when it happens rather than only in the
        #: stream (stage 8 item 4). None in a bare store.
        self._publish = publish

    def _now(self) -> float:
        return float(self._clock() if callable(self._clock) else self._clock.now())

    async def sync(self) -> None:
        if self._ledger is None:
            return
        for event in await self._ledger.read(STREAM, from_seq=self._cursor + 1):
            self._cursor = event.seq
            policy = from_dict(event.payload or {})
            if policy.id:
                self._policies[policy.id] = policy

    async def _write(self, policy: Policy) -> Policy:
        self._policies[policy.id] = policy
        if self._ledger is not None:
            from simorgh.contracts.envelope import Event

            await self._ledger.append(STREAM, Event(
                stream=STREAM, type=f"policy.{policy.status}", ts=self._now(), trace_id=policy.id,
                causation_id=None, payload=policy.to_dict()))
        await self._announce(policy)
        return policy

    #: status -> topic. `refused` is deliberately absent: a policy that
    #: did not clear its measurement is in the stream for whoever looks,
    #: and announcing every refusal would train the household to ignore
    #: the ones that matter.
    _TOPICS = {"proposed": topics.GROWTH_POLICY_PROPOSED,
               "adopted": topics.GROWTH_POLICY_ADOPTED,
               "retired": topics.GROWTH_POLICY_RETIRED}

    async def _announce(self, policy: Policy) -> None:
        topic = self._TOPICS.get(policy.status)
        if self._publish is None or topic is None:
            return
        payload = {"policy_id": policy.id, "kind": policy.kind, "task_type": policy.task_type,
                   "body": policy.body, "why": policy.why,
                   "evidence_refs": list(policy.evidence_refs)}
        if policy.status == "adopted":
            payload.update(baseline=float(policy.baseline or 0.0), result=float(policy.result or 0.0),
                           evaluated_on=policy.evaluated_on, ttl_s=policy.ttl_s)
        if policy.status == "retired":
            payload["reason"] = policy.why or "it ran out"
        await self._publish(topic, payload)

    async def propose(self, *, kind: str, task_type: str, body: str, evidence_refs=(), why: str = "") -> Policy:
        if kind not in KINDS:
            raise ValueError(f"unknown policy kind {kind!r}; the kinds are {', '.join(KINDS)}")
        if not body.strip():
            raise ValueError("a policy with no body changes nothing")
        return await self._write(Policy(
            id=uuid.uuid4().hex[:12], kind=kind, task_type=task_type, body=body.strip(),
            evidence_refs=tuple(evidence_refs), why=why, proposed_at=self._now()))

    async def adopt(self, policy_id: str, *, baseline: float, result: float, evaluated_on: int,
                    fixed_a_motivating_case: bool, samples_at_adoption: int = 0) -> Policy | None:
        """Adopt only against a measurement.

        Two conditions, both from the plan and both refusals in practice:
        no regression against the stored baseline, and at least one of the
        failures that motivated it actually fixed. A change that makes
        nothing worse and nothing better is not an improvement.
        """
        policy = self._policies.get(policy_id)
        if policy is None or policy.status != "proposed":
            return None
        if evaluated_on <= 0:
            return await self._write(replace(policy, status="refused", why="never measured"))
        if result < baseline:
            return await self._write(replace(
                policy, status="refused", baseline=baseline, result=result, evaluated_on=evaluated_on,
                why=f"regressed: {result:.2f} against a baseline of {baseline:.2f}"))
        if not fixed_a_motivating_case:
            return await self._write(replace(
                policy, status="refused", baseline=baseline, result=result, evaluated_on=evaluated_on,
                why="fixed none of the failures it came from"))
        return await self._write(replace(
            policy, status="adopted", baseline=baseline, result=result, evaluated_on=evaluated_on,
            adopted_at=self._now(), samples_at_adoption=max(0, int(samples_at_adoption)),
            why=f"{result:.2f} against a baseline of {baseline:.2f} over {evaluated_on}"))

    async def retire(self, policy_id: str, *, why: str) -> Policy | None:
        policy = self._policies.get(policy_id)
        if policy is None or not policy.live:
            return None
        return await self._write(replace(policy, status="retired", retired_at=self._now(), why=why))

    #: How many outcomes a task type must produce AFTER an adoption
    #: before the adoption can be judged on them (stage 8 item 6). Below
    #: this, a run of bad luck retires a policy that was working.
    MIN_SAMPLES_AFTER = 5

    async def review(self, posterior_of, *, min_samples_after: int | None = None) -> list[Policy]:
        """Retire every live policy whose task type has got worse since
        it was adopted (stage 8 item 6).

        `posterior_of(task_type) -> (mean, samples)` -- the estimate
        part's own numbers, so "worse" means worse by the measure that
        justified the adoption in the first place.

        Two things keep this from being trigger-happy. It only judges a
        policy on outcomes recorded AFTER it was adopted, because
        comparing against all of history judges it on work that
        predates it. And it needs `MIN_SAMPLES_AFTER` of them, because
        a run of bad luck should not retire something that is working.
        A policy retired here is retired the ordinary way -- reversible,
        recorded, announced -- not rolled back in a panic.
        """
        floor = self.MIN_SAMPLES_AFTER if min_samples_after is None else max(1, int(min_samples_after))
        out: list[Policy] = []
        for policy in list(self._policies.values()):
            if not policy.live or policy.baseline is None or not policy.task_type:
                continue
            try:
                mean, samples = posterior_of(policy.task_type)
            except Exception:  # noqa: BLE001 -- no estimate is not evidence of harm
                continue
            if samples - policy.samples_at_adoption < floor:
                continue
            if mean >= policy.baseline:
                continue
            retired = await self.retire(
                policy.id,
                why=(f"{policy.task_type} is at {mean:.2f} since, against the {policy.baseline:.2f} "
                     f"it was adopted over"))
            if retired is not None:
                out.append(retired)
        return out

    async def retire_expired(self) -> list[Policy]:
        now = self._now()
        out = []
        for policy in list(self._policies.values()):
            if policy.expired(now):
                retired = await self.retire(policy.id, why="its measurement is older than its ttl")
                if retired is not None:
                    out.append(retired)
        return out

    def live_for(self, task_type: str) -> list[Policy]:
        return [p for p in self._policies.values() if p.live and p.task_type in (task_type, "")]

    def all(self) -> list[Policy]:
        return sorted(self._policies.values(), key=lambda p: p.proposed_at)


__all__ = ["DEFAULT_TTL_S", "KINDS", "Policy", "PolicyStore", "STATUSES", "STREAM", "from_dict"]
