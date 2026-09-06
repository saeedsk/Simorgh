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

Both `reflect_on_outcome()` and `critique_intent()` also each write a
structured self-critique delta (kind="self_critique_delta") -- what
changed since the last delta on that subject, a confidence score, and an
open question -- via `ReflectionAgent.record_self_critique()`. Unlike the
takeaway/feedback records above, a delta is built by reading the most
recent prior delta for the same subject first, so consecutive reflection
cycles compound on each other's reasoning instead of each one starting
cold from raw outcomes.
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


@dataclass(frozen=True)
class SelfCritique:
    """A structured self-critique delta for one subject (typically a
    sub-agent): what changed since the last delta on that subject, how
    confident this assessment is, and what remains unresolved. Stored
    durably (kind="self_critique_delta") so the next reflection cycle on
    the same subject can read the prior delta first instead of
    re-deriving its reasoning from raw outcomes cold.
    """

    subject: str
    what_changed: str
    confidence: float
    open_questions: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SelfModelSnapshot:
    """A point-in-time summary of what Simorgh currently knows about its
    own capabilities and behavior: the durable self-knowledge facts
    (kind="self_knowledge") and self-critique confidence levels
    (kind="self_critique_delta") accumulated so far, one entry per
    subject/agent. Built fresh each time by `ReflectionAgent.build_self_model`
    from the store's own records rather than tracked incrementally, so it
    always reflects current state rather than an accumulated diff of
    diffs -- `ReflectionAgent.diff_self_model` is what compares two of
    these snapshots against each other.
    """

    knowledge_by_subject: dict[str, str]
    critique_confidence_by_subject: dict[str, float]
    timestamp: float = field(default_factory=time.time)


TAKEAWAY_KIND = "takeaway"
FEEDBACK_KIND = "feedback"
SELF_KNOWLEDGE_KIND = "self_knowledge"
CONFIDENCE_KIND = "confidence_calibration"
SELF_CRITIQUE_KIND = "self_critique_delta"
SELF_MODEL_SNAPSHOT_KIND = "self_model_snapshot"


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

    def _latest_self_critique(self, subject: str) -> SelfCritique | None:
        """Reads back the most recent self-critique delta for `subject`,
        if any, so `record_self_critique` can describe a fresh delta
        against it rather than starting cold. Returns None without a
        store or when no prior delta exists for this subject.
        """
        if self._store is None:
            return None
        records = self._store.query(kind=SELF_CRITIQUE_KIND, limit=50)
        matches = [r for r in records if r.metadata.get("subject") == subject]
        if not matches:
            return None
        latest = max(matches, key=lambda r: r.metadata.get("timestamp", r.created_at))
        return SelfCritique(
            subject=subject,
            what_changed=latest.metadata["what_changed"],
            confidence=latest.metadata["confidence"],
            open_questions=latest.metadata.get("open_questions", ""),
            timestamp=latest.metadata.get("timestamp", latest.created_at),
        )

    def record_self_critique(
        self, subject: str, note: str, source_file: str | None
    ) -> SelfCritique | None:
        """Builds and stores one structured self-critique delta for
        `subject`: reads the most recent prior delta (if any) via
        `_latest_self_critique` so `what_changed` is phrased as a delta
        against that prior reasoning rather than a cold restart, assigns
        a `confidence` that grows the more times the same `note` has
        recurred (a repeat is a stronger signal than a single
        observation), and records an `open_questions` prompt for the next
        cycle to pick up. Requires `store` (returns None without one,
        same as the other store-backed passes).
        """
        if self._store is None:
            return None

        previous = self._latest_self_critique(subject)
        if previous is None:
            what_changed = f"first recorded critique for '{subject}': {note}"
            confidence = 0.4
        elif previous.what_changed.endswith(note):
            what_changed = f"issue persists for '{subject}': {note}"
            confidence = min(1.0, previous.confidence + 0.15)
        else:
            what_changed = f"new observation for '{subject}': {note}"
            confidence = 0.4

        open_questions = (
            f"is this a recurring, systemic issue in {source_file}, or a one-off?"
            if source_file is not None
            else f"no known source file for '{subject}' -- where does this actually live?"
        )

        critique = SelfCritique(
            subject=subject,
            what_changed=what_changed,
            confidence=confidence,
            open_questions=open_questions,
        )
        self._store.remember(
            SELF_CRITIQUE_KIND,
            f"{what_changed} (confidence {confidence:.2f}) -- {open_questions}",
            subject=subject,
            what_changed=what_changed,
            confidence=confidence,
            open_questions=open_questions,
            timestamp=critique.timestamp,
        )
        return critique

    def build_self_model(self) -> SelfModelSnapshot:
        """Builds a fresh summary of current self-knowledge (kind=
        "self_knowledge") and self-critique confidence (kind=
        "self_critique_delta"), one entry per subject/agent, taking the
        most recent record for each -- `query()` already returns records
        most-recent-first, so the first occurrence per subject in
        iteration order is the latest. This is the "current capabilities/
        behavior" half of `diff_self_model`: read live from the store
        rather than cached, since self-knowledge can be promoted or a
        critique delta recorded at any point between diffs.
        """
        knowledge_by_subject: dict[str, str] = {}
        critique_confidence_by_subject: dict[str, float] = {}
        if self._store is not None:
            for record in self._store.query(kind=SELF_KNOWLEDGE_KIND):
                subject = record.metadata.get("agent")
                if subject is not None and subject not in knowledge_by_subject:
                    knowledge_by_subject[subject] = record.content
            for record in self._store.query(kind=SELF_CRITIQUE_KIND):
                subject = record.metadata.get("subject")
                if subject is not None and subject not in critique_confidence_by_subject:
                    critique_confidence_by_subject[subject] = record.metadata.get(
                        "confidence", 0.0
                    )

        return SelfModelSnapshot(
            knowledge_by_subject=knowledge_by_subject,
            critique_confidence_by_subject=critique_confidence_by_subject,
        )

    def _latest_self_model_snapshot(self) -> SelfModelSnapshot | None:
        """Reads back the most recently stored self-model snapshot (kind=
        "self_model_snapshot"), if any, so `diff_self_model` has a
        baseline to compare the freshly built snapshot against. Returns
        None without a store or before the first snapshot has ever been
        recorded.
        """
        if self._store is None:
            return None
        records = self._store.query(kind=SELF_MODEL_SNAPSHOT_KIND, limit=1)
        if not records:
            return None
        latest = records[0]
        return SelfModelSnapshot(
            knowledge_by_subject=latest.metadata.get("knowledge_by_subject", {}),
            critique_confidence_by_subject=latest.metadata.get(
                "critique_confidence_by_subject", {}
            ),
            timestamp=latest.metadata.get("timestamp", latest.created_at),
        )

    def diff_self_model(self) -> str | None:
        """Self-model diffing pass: compares the current self-model
        (`build_self_model`) against the last stored snapshot to
        explicitly surface what has changed about Simorgh's own
        capabilities/behavior since then -- new self-knowledge gained,
        facts that were revised, and subjects whose self-critique
        confidence moved meaningfully (>= 0.15). Always stores the freshly
        built snapshot afterward (kind="self_model_snapshot") so the next
        call diffs against this one; on the very first call there is
        nothing yet to compare against, so this seeds the baseline
        snapshot and returns None rather than a diff. Requires `store`
        (returns None without one, same as the other store-backed
        passes).
        """
        if self._store is None:
            return None

        current = self.build_self_model()
        previous = self._latest_self_model_snapshot()

        self._store.remember(
            SELF_MODEL_SNAPSHOT_KIND,
            f"self-model snapshot at {current.timestamp}",
            knowledge_by_subject=current.knowledge_by_subject,
            critique_confidence_by_subject=current.critique_confidence_by_subject,
            timestamp=current.timestamp,
        )

        if previous is None:
            return None

        changes = []
        for subject, fact in current.knowledge_by_subject.items():
            prior_fact = previous.knowledge_by_subject.get(subject)
            if prior_fact is None:
                changes.append(f"gained new self-knowledge about '{subject}': {fact}")
            elif prior_fact != fact:
                changes.append(f"revised self-knowledge about '{subject}': {fact}")

        for subject, confidence in current.critique_confidence_by_subject.items():
            prior_confidence = previous.critique_confidence_by_subject.get(subject)
            if prior_confidence is None:
                continue
            delta = confidence - prior_confidence
            if abs(delta) >= 0.15:
                direction = "grew more confident" if delta > 0 else "grew less confident"
                changes.append(
                    f"{direction} about '{subject}' (self-critique confidence "
                    f"{prior_confidence:.2f} -> {confidence:.2f})"
                )

        if not changes:
            return None
        return "self-model diff since last reflection: " + "; ".join(changes)

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
            note = outcome.note or ("failed" if not outcome.succeeded else "corrected by creator")
            self.record_self_critique(outcome.agent, note, source_file)
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
            note = f"low intent alignment ({score:.0%})"
            self.record_self_critique(
                outcome.agent, note, AGENT_SOURCE_FILES.get(outcome.agent)
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