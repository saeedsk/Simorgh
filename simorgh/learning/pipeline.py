"""`PatchPipeline` / `SkillPipeline`: the self-patch and skill state
machine (spec section 5.2/5.3) -- policy only. Every actual file
read/write/test/commit/relaunch is an `action.proposed` to Guardian;
this class only ever decides *what* to propose next and *how many
times* to retry, correlating asynchronous `action.result`/`verify.result`
events by id (`correlator.py`) since Guardian/Execution/Verification
publish independently rather than replying to a request.

Deliberately simplified relative to the full spec for this build pass
(see README's build log and section 12 open questions): no distinct
"floor" signal on `action.result` (the real `ActionResult` schema has
no metadata field to carry one -- every `ok: false` is treated as a
retryable draft failure, using `error` as feedback) and the
`insufficient_evidence` re-verify is a single bounded retry, not a
separate un-charged attempt budget.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.ledger.client import LedgerClient

from .config import Config
from .correlator import Correlator

Publish = Callable[[str, dict], Awaitable[None]]
Propose = Callable[..., Awaitable[None]]  # (tool, args, scope, reversibility, rationale, action_id, task_id) -> None


class PatchPipeline:
    def __init__(self, *, task_id: str, kind: str, description: str, subject: str | None,
                 prior_reasons: list[str], config: Config, ledger: LedgerClient, clock,
                 propose_action: Propose, request_verify: Propose,
                 action_correlator: Correlator, verify_correlator: Correlator, publish: Publish) -> None:
        if kind == "patch" and not subject:
            raise ValueError("a patch pipeline requires a subject")
        self.task_id = task_id
        self.kind = kind
        self._description = description
        self._subject = subject
        self._prior_reasons = list(prior_reasons)
        self._config = config
        self._ledger = ledger
        self._clock = clock
        self._propose_action = propose_action
        self._request_verify = request_verify
        self._action_correlator = action_correlator
        self._verify_correlator = verify_correlator
        self._publish = publish
        self._stream = f"learn:patch:{task_id}"

    async def _checkpoint(self, event_type: str, payload: dict) -> None:
        await self._ledger.append(self._stream, Event(
            stream=self._stream, type=event_type, ts=self._clock(), trace_id=self.task_id,
            causation_id=None, payload=payload,
        ))

    async def run(self) -> dict:
        started = self._clock()
        await self._checkpoint("started", {"kind": self.kind, "subject": self._subject})
        reasons = list(self._prior_reasons)
        attempts = 0
        while attempts < self._config.max_draft_attempts:
            if self._clock() - started > self._config.max_pipeline_wall_seconds:
                return await self._finish("rejected", "timed out")
            attempts += 1
            draft = await self._propose_and_await(
                tool="self_patch.draft" if self.kind == "patch" else "skill.draft",
                args={"subject": self._subject, "description": self._description, "prior_reasons": reasons},
                scope={"paths": [p for p in [self._subject] if p], "network": False},
                reversibility="read_only",
                rationale=f"draft attempt {attempts}/{self._config.max_draft_attempts}",
                correlator=self._action_correlator,
                timeout=self._config.action_timeout_seconds,
            )
            await self._checkpoint("draft_result", {"attempt": attempts, "result": draft})
            if draft is None:
                return await self._finish("rejected", "draft action timed out")
            if draft.get("denied"):
                return await self._finish("rejected", f"draft denied: {draft.get('reasons')}")
            if not draft["ok"]:
                reasons = [draft.get("error") or "draft failed"]
                continue

            candidate_ref = draft["output_ref"]
            verify = await self._verify_once(candidate_ref)
            if verify is not None and verify["verdict"] == "insufficient_evidence":
                verify = await self._verify_once(candidate_ref)  # one bounded re-verify, no extra draft attempt
            await self._checkpoint("verify_result", {"attempt": attempts, "result": verify})
            if verify is None:
                return await self._finish("rejected", "verification timed out")
            if verify["verdict"] == "pass":
                return await self._apply_commit_activate(candidate_ref, verify)
            items = (verify.get("feedback") or {}).get("items") or []
            reasons = [i["why"] for i in items] or ["verification did not pass"]

        return await self._finish("rejected", f"rejected after {attempts} attempt(s): {'; '.join(reasons)}")

    async def _verify_once(self, candidate_ref: str) -> dict | None:
        verification_id = str(uuid.uuid4())
        fut = self._verify_correlator.wait_for(verification_id)
        await self._request_verify(
            verification_id=verification_id, task_id=self.task_id,
            kind="self_patch" if self.kind == "patch" else "skill",
            subject_ref=candidate_ref, checklist_hint=self._description,
        )
        try:
            return await asyncio.wait_for(fut, timeout=self._config.verify_timeout_seconds)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

    async def _propose_and_await(self, *, tool: str, args: dict, scope: dict, reversibility: str,
                                  rationale: str, correlator: Correlator, timeout: float) -> dict | None:
        action_id = str(uuid.uuid4())
        fut = correlator.wait_for(action_id)
        await self._propose_action(
            action_id=action_id, tool=tool, args=args, scope=scope, reversibility=reversibility,
            rationale=rationale, task_id=self.task_id,
        )
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

    async def _apply_commit_activate(self, candidate_ref: str, verify: dict) -> dict:
        apply_tool = "apply_source_patch" if self.kind == "patch" else "apply_skill"
        applied = await self._propose_and_await(
            tool=apply_tool, args={"subject": self._subject, "candidate_ref": candidate_ref},
            scope={"paths": [self._subject] if self._subject else [], "network": False},
            reversibility="reversible", rationale="apply the verified candidate",
            correlator=self._action_correlator, timeout=self._config.action_timeout_seconds,
        )
        if applied is None or applied.get("denied") or not applied.get("ok"):
            return await self._finish("rejected", "apply denied or failed", verification_ref=None)

        commit = await self._propose_and_await(
            tool="git_commit", args={"paths": [self._subject] if self._subject else [], "message": self._commit_message()},
            scope={"paths": [self._subject] if self._subject else [], "network": False},
            reversibility="reversible", rationale="commit the applied change",
            correlator=self._action_correlator, timeout=self._config.action_timeout_seconds,
        )
        commit_sha = (commit or {}).get("stdout_preview") or None
        tests = {"baseline": verify.get("mechanical", {}).get("baseline") or 0,
                 "patched": verify.get("mechanical", {}).get("patched") or 0}

        if self.kind == "skill":
            await self._publish(topics.LEARN_SKILL_ACQUIRED, {"name": self._skill_name(), "path": self._subject or "", "tests": tests["patched"]})
            # Skill acquisition as procedural memory (roadmap 4.7): the
            # `learn.skill.acquired` event itself carries no description
            # field (LearnSkillAcquired is `{name, path, tests}` only --
            # see the package README's open questions), so the
            # description this pipeline was actually given is stored
            # straight into Memory's procedural kind instead, over the
            # already-generic `memory.store` command. This is what makes
            # the skill discoverable by description later (Execution's
            # `memory.retrieve{kinds:[procedural]}` lookup on load).
            await self._publish(topics.MEMORY_STORE, {
                "kind": "procedural", "content": self._description,
                "tags": ["skill", self._skill_name()], "source_ref": self._subject or "",
            })
            return await self._finish("applied", "skill acquired", commit=commit_sha)

        activation_tool = "hot_swap" if self._subject in self._config.hot_swap_slots else "relaunch"
        activation = await self._propose_and_await(
            tool=activation_tool, args={"subject": self._subject, "commit": commit_sha},
            scope={"paths": [], "network": False}, reversibility="reversible",
            rationale="activate the committed change", correlator=self._action_correlator,
            timeout=self._config.action_timeout_seconds,
        )
        if activation is not None and not activation.get("denied") and activation.get("ok"):
            await self._publish(topics.LEARN_SELF_PATCH_APPLIED, {
                "subject": self._subject, "commit": commit_sha or "", "tests": tests,
            })
            return await self._finish("applied", "self-patch applied", commit=commit_sha)

        await self._propose_and_await(
            tool="git_revert_range", args={"from": commit_sha or "HEAD"},
            scope={"paths": [], "network": False}, reversibility="reversible",
            rationale="revert after activation failure", correlator=self._action_correlator,
            timeout=self._config.action_timeout_seconds,
        )
        await self._publish(topics.LEARN_SELF_PATCH_REVERTED, {
            "subject": self._subject, "commit": commit_sha or "", "tests": tests, "reason": "activation_failed",
        })
        return await self._finish("reverted", "activation failed; reverted")

    def _skill_name(self) -> str:
        return (self._subject or "skill").rsplit("/", 1)[-1].removesuffix(".py")

    def _commit_message(self) -> str:
        return f"[sim] {'Patch' if self.kind == 'patch' else 'Add skill'} {self._subject}\n\n{self._description}"

    async def _finish(self, outcome: str, detail: str, *, commit: str | None = None,
                       verification_ref: str | None = None) -> dict:
        payload = {"task_id": self.task_id, "outcome": outcome, "detail": detail}
        if commit is not None:
            payload["commit"] = commit
        if verification_ref is not None:
            payload["verification_ref"] = verification_ref
        await self._checkpoint("finished", payload)
        await self._publish(topics.LEARN_PIPELINE_COMPLETED, payload)
        return payload
