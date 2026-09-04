"""Live, partial self-update: hot-swappable sub-agents, versioned rollback,
and A/B trials.

Simorgh doesn't update by replacing its whole running process. Each named
slot in a Router (e.g. "logic", "emotion", "skills") can have a candidate
implementation staged alongside the currently active one, trialed against
a *cloned* copy of persona state (so a bad candidate never touches live
state while it's being evaluated -- the same isolation principle as
SandboxExecutor, applied to whole sub-agents), and only promoted to active
if the trial looks good. The previous version is kept, not deleted, so a
promotion can be undone immediately; it's only dropped once `purge_retired`
is called deliberately. See docs/EVOLUTION.md and docs/BIOMIMICRY.md
("Regeneration and apoptosis") for the biological framing this mirrors.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from src.memory.long_term import MemoryStore
from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.persona_state import EmotionalState, PersonaState
from src.orchestrator.router import AgentRequest, AgentResponse, Router, SubAgent


class VersionStatus(Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


@dataclass
class AgentVersion:
    slot: str
    version_id: str
    agent: SubAgent
    status: VersionStatus
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TrialOutcome:
    request_text: str
    succeeded: bool
    output: str
    error: str | None = None


@dataclass(frozen=True)
class TrialReport:
    slot: str
    candidate_version_id: str
    baseline_outcomes: list[TrialOutcome]
    candidate_outcomes: list[TrialOutcome]

    @property
    def baseline_success_rate(self) -> float:
        return _success_rate(self.baseline_outcomes)

    @property
    def candidate_success_rate(self) -> float:
        return _success_rate(self.candidate_outcomes)

    def candidate_is_at_least_as_good(self) -> bool:
        return self.candidate_success_rate >= self.baseline_success_rate


def _success_rate(outcomes: list[TrialOutcome]) -> float:
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.succeeded) / len(outcomes)


def _default_evaluator(response: AgentResponse) -> bool:
    """A response that was produced at all (no exception) counts as a
    success. Callers should pass a domain-specific evaluator -- e.g.
    checking `response.metadata` -- for a meaningful A/B comparison beyond
    "didn't crash."
    """
    return True


class DeploymentManager:
    """Owns versioning for the sub-agents registered in one Router.

    Registers the ACTIVE agent for each slot into the router directly, so
    normal dispatch is unaffected by staging or trialing a candidate --
    only `promote` and `rollback` ever change what the router actually
    dispatches to.
    """

    def __init__(self, router: Router, memory: MemoryStore | None = None) -> None:
        self._router = router
        self._memory = memory
        self._lock = threading.RLock()
        self._active: dict[str, AgentVersion] = {}
        self._candidates: dict[str, AgentVersion] = {}
        self._retired: dict[str, list[AgentVersion]] = {}

    def deploy(self, agent: SubAgent, version_id: str | None = None) -> AgentVersion:
        """Register `agent` as the initial ACTIVE version for its slot
        (`agent.name`). Use this for first-time setup, not for updates --
        use `stage_candidate` + `promote` once a slot already has an
        active version.
        """
        with self._lock:
            slot = agent.name
            if slot in self._active:
                raise ValueError(
                    f"slot {slot!r} already has an active version; use "
                    "stage_candidate() + promote() to update it"
                )
            version = AgentVersion(
                slot=slot,
                version_id=version_id or _new_version_id(),
                agent=agent,
                status=VersionStatus.ACTIVE,
            )
            self._router.register(agent)
            self._active[slot] = version
            self._log("deploy", slot, version.version_id, "initial deployment")
            return version

    def stage_candidate(
        self, agent: SubAgent, version_id: str | None = None
    ) -> AgentVersion:
        """Register a candidate ("B") for `agent.name`'s slot without
        touching live dispatch -- the router keeps sending traffic to the
        current active ("A") version.
        """
        with self._lock:
            slot = agent.name
            if slot not in self._active:
                raise ValueError(
                    f"slot {slot!r} has no active version yet; call deploy() first"
                )
            if slot in self._candidates:
                raise ValueError(
                    f"slot {slot!r} already has a staged candidate; "
                    "promote() or rollback() it before staging another"
                )
            version = AgentVersion(
                slot=slot,
                version_id=version_id or _new_version_id(),
                agent=agent,
                status=VersionStatus.CANDIDATE,
            )
            self._candidates[slot] = version
            self._log("stage_candidate", slot, version.version_id, "candidate staged")
            return version

    def run_trial(
        self,
        slot: str,
        requests: list[AgentRequest],
        evaluator: Callable[[AgentResponse], bool] = _default_evaluator,
        seed_state: EmotionalState | None = None,
    ) -> TrialReport:
        """Replay `requests` through the active version and the staged
        candidate, each against its own freshly cloned bus seeded from
        `seed_state` (defaults to neutral) -- neither run touches live
        persona state.
        """
        with self._lock:
            active = self._active.get(slot)
            candidate = self._candidates.get(slot)
        if active is None:
            raise ValueError(f"slot {slot!r} has no active version")
        if candidate is None:
            raise ValueError(f"slot {slot!r} has no staged candidate to trial")

        baseline_outcomes = _replay(active.agent, requests, evaluator, seed_state)
        candidate_outcomes = _replay(candidate.agent, requests, evaluator, seed_state)

        return TrialReport(
            slot=slot,
            candidate_version_id=candidate.version_id,
            baseline_outcomes=baseline_outcomes,
            candidate_outcomes=candidate_outcomes,
        )

    def promote(self, slot: str) -> AgentVersion:
        """Swap the staged candidate in as the new active version. The
        previous active version is kept as RETIRED, not deleted -- call
        `rollback` to undo this, or `purge_retired` once confident.
        """
        with self._lock:
            candidate = self._candidates.pop(slot, None)
            if candidate is None:
                raise ValueError(f"slot {slot!r} has no staged candidate to promote")

            previous_active = self._active[slot]
            previous_active.status = VersionStatus.RETIRED
            self._retired.setdefault(slot, []).append(previous_active)

            candidate.status = VersionStatus.ACTIVE
            self._router.register(candidate.agent)
            self._active[slot] = candidate

            self._log(
                "promote",
                slot,
                candidate.version_id,
                f"promoted to active, replacing {previous_active.version_id}",
            )
            return candidate

    def rollback(self, slot: str) -> AgentVersion:
        """Undo the most recent change to `slot`: if a candidate is merely
        staged, discard it and leave the active version untouched. If the
        slot has no staged candidate, restore the most recently retired
        version to active (undoing a promotion).
        """
        with self._lock:
            candidate = self._candidates.pop(slot, None)
            if candidate is not None:
                candidate.status = VersionStatus.ROLLED_BACK
                self._log(
                    "rollback", slot, candidate.version_id, "staged candidate discarded"
                )
                return self._active[slot]

            retired_list = self._retired.get(slot) or []
            if not retired_list:
                raise ValueError(
                    f"slot {slot!r} has nothing to roll back to "
                    "(no staged candidate and no retired version)"
                )
            restored = retired_list.pop()
            current_active = self._active[slot]
            current_active.status = VersionStatus.ROLLED_BACK

            restored.status = VersionStatus.ACTIVE
            self._router.register(restored.agent)
            self._active[slot] = restored

            self._log(
                "rollback",
                slot,
                restored.version_id,
                f"restored to active, replacing {current_active.version_id}",
            )
            return restored

    def hot_swap(
        self,
        candidate: SubAgent,
        requests: list[AgentRequest],
        evaluator: Callable[[AgentResponse], bool] = _default_evaluator,
        seed_state: EmotionalState | None = None,
    ) -> tuple[bool, TrialReport]:
        """Stage `candidate` for its own slot (`candidate.name`), trial
        it against `requests`, and `promote` it live if the trial looks
        at least as good as the current active version -- otherwise
        `rollback` (discard the candidate, active version untouched).
        One call for the whole stage/trial/decide sequence, since a
        caller doing this three-step dance manually would otherwise
        have to duplicate the same decision `run_trial`'s own
        `candidate_is_at_least_as_good` already encodes.

        This is what lets a self-patch to a file that defines a live
        Router sub-agent take effect via an in-process swap instead of
        the full-process `relaunch()` self-patching otherwise requires
        (see src/main.py's `_attempt_hot_swap`) -- narrower blast radius
        (only this one slot's dispatch changes, not the whole process),
        and no interruption to whatever else the process was doing.
        Requires `deploy()` to have already registered an active version
        for this slot; raises ValueError (same as `stage_candidate`)
        otherwise. If `run_trial` itself raises (a request replay
        raising something `evaluator` doesn't catch, or a real bug in
        the trial machinery -- distinct from a candidate's `handle()`
        raising, which `run_trial` already converts into a normal failed
        `TrialOutcome`), the candidate is rolled back before the
        exception propagates, so a broken trial never leaves a stale
        candidate staged.

        Returns `(promoted, TrialReport)` so the caller can report
        exactly what the trial found either way, not just yes/no.
        """
        self.stage_candidate(candidate)
        try:
            report = self.run_trial(
                candidate.name, requests, evaluator=evaluator, seed_state=seed_state
            )
        except Exception:
            self.rollback(candidate.name)
            raise

        if report.candidate_is_at_least_as_good():
            self.promote(candidate.name)
            return True, report
        self.rollback(candidate.name)
        return False, report

    def purge_retired(self, slot: str, keep_last: int = 0) -> int:
        """Permanently drop old RETIRED versions for `slot`, keeping only
        the most recent `keep_last`. This is the "then remove A" step --
        it only ever discards RETIRED versions, never the current ACTIVE
        one, so it can't accidentally remove what's live.
        """
        with self._lock:
            retired_list = self._retired.get(slot, [])
            if keep_last < 0:
                raise ValueError("keep_last must be >= 0")
            to_purge = retired_list[: max(0, len(retired_list) - keep_last)]
            self._retired[slot] = retired_list[len(to_purge) :]
            for version in to_purge:
                self._log("purge", slot, version.version_id, "permanently removed")
            return len(to_purge)

    def status(self, slot: str) -> dict:
        with self._lock:
            return {
                "active": self._active.get(slot),
                "candidate": self._candidates.get(slot),
                "retired": list(self._retired.get(slot, [])),
            }

    def _log(self, event: str, slot: str, version_id: str, detail: str) -> None:
        if self._memory is None:
            return
        self._memory.remember(
            "lineage",
            f"{event}: {slot} -> {version_id} ({detail})",
            event=event,
            slot=slot,
            version_id=version_id,
        )


def _replay(
    agent: SubAgent,
    requests: list[AgentRequest],
    evaluator: Callable[[AgentResponse], bool],
    seed_state: EmotionalState | None,
) -> list[TrialOutcome]:
    bus = SharedMemoryBus(PersonaState(initial_state=seed_state))
    outcomes = []
    for request in requests:
        try:
            response = agent.handle(request, bus)
        except Exception as exc:  # noqa: BLE001 -- trial isolation: a crashing
            # candidate must not abort the whole trial, just fail that request
            outcomes.append(
                TrialOutcome(
                    request_text=request.text,
                    succeeded=False,
                    output="",
                    error=repr(exc),
                )
            )
            continue
        outcomes.append(
            TrialOutcome(
                request_text=request.text,
                succeeded=evaluator(response),
                output=response.output,
            )
        )
    return outcomes


def _new_version_id() -> str:
    return uuid.uuid4().hex[:8]
