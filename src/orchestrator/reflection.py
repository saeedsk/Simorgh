"""Outcome logging and reflection: the feedback loop that lets Simorgh
learn from its mistakes without silently rewriting itself.

Every completed interaction can be logged as an Outcome (success, failure,
or creator-corrected). ReflectionAgent periodically reviews recent outcomes
looking for patterns -- e.g. one sub-agent failing or getting corrected
often -- and turns them into Proposals: plain-language, human-readable
suggestions for a change. Proposals are data, not actions; per
docs/SOUL.md, turning a proposal into an actual change to Simorgh's own
behavior always goes through the audit gate (src/orchestrator/audit.py)
and, currently, the creator. See docs/EVOLUTION.md, "Learning From
Mistakes."
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
    ) -> None:
        self._log = log
        self._concern_threshold = concern_threshold
        self._min_samples = min_samples

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
