"""Outcome logging and reflection: the feedback loop that lets Simorgh
learn from its mistakes without silently rewriting itself.

Every completed interaction can be logged as an Outcome (success, failure,
or creator-corrected). Two distinct reflection passes read that log:

- `ReflectionAgent.reflect()` -- batched, periodic: reviews a whole
  window of recent outcomes looking for *patterns* (e.g. one sub-agent
  failing or getting corrected often).
- `ReflectionAgent.reflect_on_outcome()` -- immediate, per-turn: the
  creator's explicit ask that Simorgh evaluate "how it can do that task
  better next time" for every situation, not only in aggregate. Fires
  right after a single outcome that failed or was corrected, using free
  heuristics rather than an LLM call -- reflecting on literally every
  turn should not multiply LLM spend (see docs/SOUL.md, "ai api call
  might become expensive," the creator's own words that shaped
  src/cognition/budget.py).

Both produce Proposals: plain-language, human-readable suggestions for a
change. Proposals are data, not actions -- turning one into an actual
change to Simorgh's own code goes through the self-patch pipeline
(src/orchestrator/self_patch.py), which is always triggered by a literal
`patch <path> <description>` command a human operator types, never
automatically from a reflection alone. See docs/EVOLUTION.md, "Learning
From Mistakes."

A third pass, `ReflectionAgent.promote_recurring_patterns()`, looks
across the takeaways and feedback already accumulated by the two passes
above and, when the same agent keeps showing up, promotes that recurring
pattern once into durable self-knowledge (kind="self_knowledge") -- so
later cycles can recall "this is a known, stable issue" instead of
re-deriving the same conclusion from raw outcomes every time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.memory.long_term import MemoryStore


@dataclass(frozen=True)
class Outcome:
    agent: str
    request_text: str
    output: str
    succeeded: bool
    corrected_by_creator: bool = False
    note: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Proposal:
    """A human-readable suggestion for a change, generated from observed
    outcomes. Never applied automatically -- see src/orchestrator/audit.py.
    """

    subject: str
    rationale: str
    evidence_count: int


@dataclass(frozen=True)
class ConfidenceRecord:
    """One self-prediction paired with what actually happened, for a
    given kind of decision (e.g. "which sub-agent to route to"). The gap
    between `predicted_confidence` and `actual_outcome` is what lets
    `ReflectionAgent.calibrate_confidence` tell a decision type Simorgh
    has been reliably well-calibrated on from one it habitually over- or
    under-trusts itself on.
    """

    decision_type: str
    predicted_confidence: float
    actual_outcome: float
    timestamp: float = field(default_factory=time.time)

    @property
    def delta(self) -> float:
        """Positive: outcome beat the prediction (under-confident).
        Negative: outcome fell short of the prediction (over-confident).
        """
        return self.actual_outcome - self.predicted_confidence


TAKEAWAY_KIND = "takeaway"
FEEDBACK_KIND = "feedback"
SELF_KNOWLEDGE_KIND = "self_knowledge"
CONFIDENCE_KIND = "confidence_calibration"


def _intent_alignment_score(request_text: str, output: str) -> float:
    """Cheap, LLM-free heuristic: fraction of significant request words
    that reappear in the output. Not a semantic judge -- just enough
    signal to flag outputs that plausibly drifted from the ask.
    """
    request_words = {w.lower() for w in request_text.split() if len(w) > 3}
    if not request_words:
        return 1.0
    output_words = {w.lower() for w in output.split()}
    return len(request_words & output_words) / len(request_words)

# Where each sub-agent's own logic actually lives, so a per-outcome
# takeaway can point at something patch-able rather than just naming the
# agent in the abstract. Kept in sync by hand with src/main.py's
# build_router -- there's no runtime introspection here, on purpose,
# since this heuristic must never itself import or execute agent code.
# Public (shared with src/orchestrator/discovery.py, which turns a
# takeaway into a persisted, patchable Task using the same mapping) --
# one source of truth, not two copies that could drift.
AGENT_SOURCE_FILES = {
    "logic": "src/agents/logic/base.py",
    "emotion": "src/agents/emotion/base.py",
    "skills": "src/agents/skills/base.py",
}


class OutcomeLog:
    """Records Outcomes into a MemoryStore (kind="outcome") and reads them
    back for reflection.
    """

    KIND = "outcome"

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def record(self, outcome: Outcome) -> None:
        self._store.remember(
            self.KIND,
            outcome.output,
            agent=outcome.agent,
            request_text=outcome.request_text,
            succeeded=outcome.succeeded,
            corrected_by_creator=outcome.corrected_by_creator,
            note=outcome.note,
            timestamp=outcome.timestamp,
        )

    def recent(self, limit: int = 100) -> list[Outcome]:
        records = self._store.query(kind=self.KIND, limit=limit)
        return [
            Outcome(
                agent=r.metadata["agent"],
                request_text=r.metadata["request_text"],
                output=r.content,
                succeeded=r.metadata["succeeded"],
                corrected_by_creator=r.metadata.get("corrected_by_creator", False),
                note=r.metadata.get("note", ""),
                timestamp=r.metadata.get("timestamp", r.created_at),
            )
            for r in records
        ]


class ConfidenceTracker:
    """Records predicted-vs-actual confidence per decision type into a
    MemoryStore (kind="confidence_calibration"), so `ReflectionAgent` can
    later check whether a given kind of decision -- e.g. "which sub-agent
    to route to" -- has run systematically over- or under-confident
    before trusting a fresh prediction of the same kind at face value.
    """

    KIND = CONFIDENCE_KIND

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def record(self, record: ConfidenceRecord) -> None:
        self._store.remember(
            self.KIND,
            f"{record.decision_type}: predicted {record.predicted_confidence:.2f}, "
            f"actual {record.actual_outcome:.2f}",
            decision_type=record.decision_type,
            predicted_confidence=record.predicted_confidence,
            actual_outcome=record.actual_outcome,
            timestamp=record.timestamp,
        )

    def recent(self, decision_type: str, limit: int = 100) -> list[ConfidenceRecord]:
        records = self._store.query(kind=self.KIND, limit=limit)
        return [
            ConfidenceRecord(
                decision_type=r.metadata["decision_type"],
                predicted_confidence=r.metadata["predicted_confidence"],
                actual_outcome=r.metadata["actual_outcome"],
                timestamp=r.metadata.get("timestamp", r.created_at),
            )
            for r in records
            if r.metadata.get("decision_type") == decision_type
        ]


class ReflectionAgent:
    """Reviews recent outcomes, grouped by sub-agent, and proposes -- never
    applies -- a review whenever an agent's failure/correction rate over
    the reviewed window crosses `concern_threshold`.
    """

    def __init__(
        self,
        log: OutcomeLog,
        concern_threshold: float = 0.3,
        min_samples: int = 5,
        store: MemoryStore | None = None,
        confidence: ConfidenceTracker | None = None,
    ) -> None:
        self._log = log
        self._concern_threshold = concern_threshold
        self._min_samples = min_samples
        self._store = store
        self._confidence = confidence

    def calibrate_confidence(
        self, decision_type: str, predicted_confidence: float, min_samples: int = 5
    ) -> float:
        """Adjusts a fresh confidence prediction for `decision_type` using
        the historical mean gap between past predictions and their actual
        outcomes (`ConfidenceRecord.delta`) -- if this decision type has
        systematically run over- or under-confident, nudges the raw
        prediction toward what actually happened rather than trusting it
        at face value. Returns `predicted_confidence` unchanged when no
        tracker is configured or there isn't yet enough history
        (`min_samples`) to distinguish a real pattern from noise.
        """
        if self._confidence is None:
            return predicted_confidence
        records = self._confidence.recent(decision_type, limit=min_samples * 4)
        if len(records) < min_samples:
            return predicted_confidence
        mean_delta = sum(r.delta for r in records) / len(records)
        return max(0.0, min(1.0, predicted_confidence + mean_delta))

    def reflect_on_outcome(self, outcome: Outcome) -> Proposal | None:
        """Immediate, per-turn takeaway: "what was the shortcoming here,
        and how might it be overcome" -- for a single Outcome, not a
        batch. Returns None for an ordinary successful outcome (nothing
        to learn from a turn that went fine). A free heuristic, not an
        LLM call, so this can run after literally every turn without
        adding to LLM spend; if `store` was given, also durably records
        the takeaway (kind="takeaway") so it survives past this process
        and shows up in ActivityLog's unified timeline.
        """
        if outcome.succeeded and not outcome.corrected_by_creator:
            return None

        source_file = AGENT_SOURCE_FILES.get(outcome.agent)
        suggestion = (
            f"consider `patch {source_file} <fix>` to address this directly"
            if source_file is not None
            else "no known source file to patch for this agent -- needs a human look"
        )
        if not outcome.succeeded:
            rationale = (
                f"'{outcome.agent}' failed on {outcome.request_text!r}"
                f"{' (' + outcome.note + ')' if outcome.note else ''} -- {suggestion}."
            )
        else:
            rationale = (
                f"'{outcome.agent}' answered {outcome.request_text!r} but the creator "
                f"corrected it -- worth revisiting why that answer was wrong; {suggestion}."
            )

        proposal = Proposal(subject=outcome.agent, rationale=rationale, evidence_count=1)
        if self._store is not None:
            self._store.remember(
                TAKEAWAY_KIND,
                proposal.rationale,
                agent=outcome.agent,
                request_text=outcome.request_text,
            )
        return proposal

    def critique_intent(
        self, outcome: Outcome, alignment_threshold: float = 0.3
    ) -> Proposal | None:
        """Structured self-critique: scores a completed task's output
        against its original request (intent), independent of the
        succeeded/corrected_by_creator flags `reflect_on_outcome` relies
        on. Catches drift that a "did it technically succeed" check
        would miss -- an output can be marked successful yet barely
        address what was actually asked. Uses the same free-heuristic
        approach as `reflect_on_outcome` (no LLM call per turn); a
        mismatch is stored as its own feedback memory (kind="feedback"),
        kept separate from takeaways so future turns can be checked
        against concrete intent/output pairs rather than only pass/fail
        history.
        """
        score = _intent_alignment_score(outcome.request_text, outcome.output)
        if score >= alignment_threshold:
            return None

        rationale = (
            f"'{outcome.agent}' output for {outcome.request_text!r} scored "
            f"{score:.0%} alignment with the original intent -- output may "
            "have drifted from the ask; worth a targeted review."
        )
        proposal = Proposal(subject=outcome.agent, rationale=rationale, evidence_count=1)
        if self._store is not None:
            self._store.remember(
                FEEDBACK_KIND,
                proposal.rationale,
                agent=outcome.agent,
                request_text=outcome.request_text,
                alignment_score=score,
            )
        return proposal

    def reflect(self, limit: int = 100) -> list[Proposal]:
        outcomes = self._log.recent(limit=limit)
        by_agent: dict[str, list[Outcome]] = {}
        for outcome in outcomes:
            by_agent.setdefault(outcome.agent, []).append(outcome)

        proposals = []
        for agent, agent_outcomes in by_agent.items():
            if len(agent_outcomes) < self._min_samples:
                continue
            trouble = sum(
                1 for o in agent_outcomes if not o.succeeded or o.corrected_by_creator
            )
            rate = trouble / len(agent_outcomes)
            if rate >= self._concern_threshold:
                proposals.append(
                    Proposal(
                        subject=agent,
                        rationale=(
                            f"'{agent}' failed or was corrected in {trouble}/"
                            f"{len(agent_outcomes)} recent outcomes ({rate:.0%}) -- "
                            "worth reviewing its logic for a systematic issue."
                        ),
                        evidence_count=len(agent_outcomes),
                    )
                )
        return proposals

    def promote_recurring_patterns(
        self, limit: int = 200, min_cluster_size: int = 3
    ) -> list[Proposal]:
        """Clusters the takeaways (`reflect_on_outcome`) and feedback
        (`critique_intent`) already accumulated for each agent and, once a
        cluster is large enough to look like a stable pattern rather than
        one-off noise, promotes it into durable self-knowledge
        (kind="self_knowledge") -- a plain fact Simorgh can recall directly
        in future cycles instead of re-deriving the same conclusion from
        raw outcomes each time. Requires `store` (returns [] without one,
        same as the other store-backed passes). Idempotent per agent: a
        pattern is only re-promoted when new evidence has grown the
        cluster past the size it was last promoted at, so this can be run
        repeatedly (e.g. alongside `reflect()`) without spamming duplicate
        self-knowledge entries.
        """
        if self._store is None:
            return []

        records = list(self._store.query(kind=TAKEAWAY_KIND, limit=limit))
        records += list(self._store.query(kind=FEEDBACK_KIND, limit=limit))

        by_agent: dict[str, list] = {}
        for record in records:
            agent = record.metadata.get("agent", "unknown")
            by_agent.setdefault(agent, []).append(record)

        previously_promoted: dict[str, int] = {}
        for record in self._store.query(kind=SELF_KNOWLEDGE_KIND, limit=limit):
            agent = record.metadata.get("agent")
            count = record.metadata.get("evidence_count", 0)
            if agent is not None and count > previously_promoted.get(agent, 0):
                previously_promoted[agent] = count

        proposals = []
        for agent, agent_records in by_agent.items():
            count = len(agent_records)
            if count < min_cluster_size:
                continue
            if count <= previously_promoted.get(agent, 0):
                continue

            source_file = AGENT_SOURCE_FILES.get(agent)
            rationale = (
                f"'{agent}' has accumulated {count} recurring takeaway/feedback "
                "entries -- this looks like a stable pattern rather than a "
                "one-off, promoting to durable self-knowledge"
                f"{' (see ' + source_file + ')' if source_file else ''}."
            )
            proposal = Proposal(subject=agent, rationale=rationale, evidence_count=count)
            self._store.remember(
                SELF_KNOWLEDGE_KIND,
                proposal.rationale,
                agent=agent,
                evidence_count=count,
            )
            proposals.append(proposal)

        return proposals