"""What a benchmark is, in this system.

The creator, 2026-09-07: "create a benchmarking unit that can benchmark
system against different standard benchmark systems and keep track of
historical benchmark results per model". So the shapes here are
deliberately *not* GAIA-specific -- GAIA is the first suite loaded
(`datasets/gaia.py`), and BFCL, SWE-bench and the rest are meant to
slot in behind the same three types.

A `Case` is one question with a known answer. A `Suite` is a named,
versioned bag of cases. A `RunRecord` is what happened when one model
answered some of them -- the durable thing, appended to the Ledger and
read back for the history graph.

Scores are always per level as well as overall: GAIA's three levels are
its whole point (a system that answers every Level 1 and no Level 3 is
a different system from one that scores the same overall spread out),
and any suite without levels simply reports one.
"""

from __future__ import annotations

import time
import uuid
import json

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Case:
    """One benchmark question and its known answer."""

    id: str
    question: str
    answer: str
    # GAIA is 1|2|3. A suite without difficulty tiers uses "" and
    # everything reports under one level.
    level: str = ""
    suite: str = ""
    # A GAIA question may name a file the answering system needs. We
    # record it rather than pretending the question is self-contained:
    # a case that needs a file we did not fetch is *skipped*, not failed,
    # so a missing attachment never looks like a wrong answer.
    attachment: str = ""
    tools_hint: str = ""
    steps_hint: int = 0
    # How this case is scored: "gaia" is quasi-exact match on a final
    # answer line; "bfcl" compares the function calls the system chose
    # against the expected ones. A suite says which; the scorer
    # dispatches on it, so a new benchmark with a new scoring rule adds
    # a mode rather than editing the runner.
    mode: str = "gaia"
    # For a tool-calling case: the function schemas the system is given.
    functions: str = ""
    # Everything a scorer needs that is not a string to compare. A
    # SWE-bench case is scored by running its own tests, so it carries
    # the container image, the eval script, the log parser's name and
    # the two test lists as JSON here. Kept as text so a cached suite is
    # still plain JSON and a `Case` stays comparable and hashable.
    data: str = ""

    def payload(self) -> dict:
        """`data` decoded, or `{}`. Never raises: a cache written by an
        older version simply has nothing here."""
        if not self.data:
            return {}
        try:
            loaded = json.loads(self.data)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @property
    def needs_attachment(self) -> bool:
        return bool(self.attachment)


@dataclass(frozen=True)
class Suite:
    """A named set of cases, with enough provenance to compare two runs.

    `version` is the dataset's own revision where it has one; two runs
    are only comparable when their suite name *and* version match, and
    the history view groups on both."""

    name: str
    cases: tuple[Case, ...]
    version: str = "unknown"
    description: str = ""

    def __len__(self) -> int:
        return len(self.cases)

    def levels(self) -> tuple[str, ...]:
        return tuple(sorted({c.level for c in self.cases}))

    def sample(self, limit: int, *, level: str = "") -> "Suite":
        """The first `limit` cases, optionally of one level.

        First rather than random: a run you can repeat is worth more
        here than an unbiased one, because the point is to see movement
        between two runs of the same thing. `shuffle` is deliberately
        not offered."""
        cases = tuple(c for c in self.cases if not level or c.level == level)
        return replace(self, cases=cases[:limit] if limit > 0 else cases)


@dataclass(frozen=True)
class CaseResult:
    """One case, answered."""

    case_id: str
    level: str
    correct: bool
    answer: str = ""
    expected: str = ""
    seconds: float = 0.0
    steps: int = 0
    # Not scored, but recorded: the article this came from is right that
    # a system can pass by brute force and still be unusable, so the
    # cost of a right answer is part of the result.
    cost_usd: float = 0.0
    # A case we could not fairly ask (an attachment we do not have, a
    # crash in the harness). Skipped cases are excluded from the score
    # rather than counted wrong.
    skipped: bool = False
    error: str = ""
    # The system had this answer and something of ours stopped it
    # delivering: verification objected, the step budget ran out. It is
    # still scored -- GAIA scores the answer, and our verifier is not
    # part of GAIA -- but the fact is recorded, because "our own
    # verifier threw away a right answer" and "the model was wrong" are
    # different problems with different fixes (2026-09-08).
    blocked_by: str = ""


@dataclass
class RunRecord:
    """One benchmark run: the durable unit the history graph plots."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    suite: str = ""
    suite_version: str = "unknown"
    model: str = "unknown"
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    results: list[CaseResult] = field(default_factory=list)
    # Set when a run ended early (interrupted, budget spent). A partial
    # run is still recorded -- it is real evidence -- but it is labelled,
    # because comparing a 5-case run against a 50-case one as if they
    # were the same measurement is how a benchmark starts lying.
    partial: bool = False
    note: str = ""
    # Set only when a record was rebuilt from a summary payload with no
    # per-case detail: the totals it can no longer recompute. Live-caught
    # 2026-09-08 -- `benchmark` reported "0s total" for a run that had
    # really taken 31 seconds, because the round trip through the history
    # summary dropped everything the synthetic results could not carry.
    totals: dict = field(default_factory=dict)

    # -- scoring -------------------------------------------------------
    @property
    def scored(self) -> list[CaseResult]:
        return [r for r in self.results if not r.skipped]

    @property
    def attempted(self) -> int:
        return len(self.scored)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.scored if r.correct)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    @property
    def accuracy(self) -> float:
        return self.correct / self.attempted if self.attempted else 0.0

    @property
    def seconds(self) -> float:
        return self.totals.get("seconds", sum(r.seconds for r in self.results))

    @property
    def cost_usd(self) -> float:
        return self.totals.get("cost_usd", sum(r.cost_usd for r in self.results))

    @property
    def blocked(self) -> int:
        """Answers our own pipeline stopped, right or wrong."""
        return sum(1 for r in self.scored if r.blocked_by)

    @property
    def blocked_but_correct(self) -> int:
        """The number that says whether our verifier is costing us."""
        return sum(1 for r in self.scored if r.blocked_by and r.correct)

    def by_level(self) -> dict[str, tuple[int, int]]:
        """level -> (correct, attempted), lowest level first."""
        out: dict[str, tuple[int, int]] = {}
        for result in self.scored:
            correct, attempted = out.get(result.level, (0, 0))
            out[result.level] = (correct + (1 if result.correct else 0), attempted + 1)
        return dict(sorted(out.items()))

    # -- wire ----------------------------------------------------------
    def to_payload(self, *, with_cases: bool = True) -> dict:
        payload = {
            "run_id": self.run_id, "suite": self.suite, "suite_version": self.suite_version,
            "model": self.model, "started_at": self.started_at, "finished_at": self.finished_at,
            "attempted": self.attempted, "correct": self.correct, "skipped": self.skipped,
            "accuracy": round(self.accuracy, 4), "seconds": round(self.seconds, 2),
            "cost_usd": round(self.cost_usd, 6), "partial": self.partial, "note": self.note,
            "blocked": self.blocked, "blocked_but_correct": self.blocked_but_correct,
            "by_level": {level: list(pair) for level, pair in self.by_level().items()},
        }
        if with_cases:
            payload["cases"] = [
                {
                    "case_id": r.case_id, "level": r.level, "correct": r.correct,
                    "answer": r.answer[:500], "expected": r.expected[:500],
                    "seconds": round(r.seconds, 2), "steps": r.steps,
                    "cost_usd": round(r.cost_usd, 6), "skipped": r.skipped, "error": r.error[:300],
                    "blocked_by": r.blocked_by[:200],
                }
                for r in self.results
            ]
        return payload

    @classmethod
    def from_payload(cls, payload: dict) -> "RunRecord":
        record = cls(
            run_id=payload.get("run_id", ""), suite=payload.get("suite", ""),
            suite_version=payload.get("suite_version", "unknown"), model=payload.get("model", "unknown"),
            started_at=float(payload.get("started_at", 0.0)), finished_at=float(payload.get("finished_at", 0.0)),
            partial=bool(payload.get("partial", False)), note=payload.get("note", ""),
        )
        for case in payload.get("cases") or ():
            record.results.append(CaseResult(
                case_id=case.get("case_id", ""), level=case.get("level", ""),
                correct=bool(case.get("correct")), answer=case.get("answer", ""),
                expected=case.get("expected", ""), seconds=float(case.get("seconds", 0.0)),
                steps=int(case.get("steps", 0)), cost_usd=float(case.get("cost_usd", 0.0)),
                skipped=bool(case.get("skipped")), error=case.get("error", ""),
                blocked_by=case.get("blocked_by", ""),
            ))
        if not record.results:
            record._rebuild_from_summary(payload)
        return record

    def _rebuild_from_summary(self, payload: dict) -> None:
        """Rebuild synthetic results from a summary that kept no cases.

        The compact form (the history endpoint's) carries totals only, so
        every property here has to be recomputed from them. Two of them
        used to come back wrong, and both understated a problem rather
        than overstating it -- the direction that lets a benchmark
        flatter itself (2026-09-08):

        - `skipped` and `blocked` returned 0 for every stored run,
          because a synthetic case defaulted to `skipped=False` and an
          empty `blocked_by`. A run that skipped 8 of 20 cases displayed
          as a clean 12-case run, and the count that says "our own
          verifier threw away a right answer" read zero forever.
        - a payload with no `by_level` produced no results at all, so
          `accuracy` was 0.0 no matter what `correct`/`attempted` said.
          Only GAIA writes per-level data; BFCL runs read as total
          failures.
        """
        self.totals = {
            "seconds": float(payload.get("seconds") or 0.0),
            "cost_usd": float(payload.get("cost_usd") or 0.0),
        }
        by_level = payload.get("by_level") or {}
        if by_level:
            pairs = [(level, int(p[0]), int(p[1])) for level, p in by_level.items()]
        else:
            # No per-level detail: one unnamed bucket carrying the totals,
            # which is still the truth, just less of it.
            pairs = [("", int(payload.get("correct") or 0), int(payload.get("attempted") or 0))]

        scored: list[CaseResult] = []
        for level, correct, attempted in pairs:
            scored.extend(
                CaseResult(case_id="", level=level, correct=i < correct) for i in range(attempted)
            )

        # Spread the blocked cases over the scored ones, correct-first, so
        # both `blocked` and `blocked_but_correct` come back as recorded.
        note = "(recorded in summary; per-case detail not stored)"
        blocked = int(payload.get("blocked") or 0)
        blocked_correct = min(int(payload.get("blocked_but_correct") or 0), blocked)
        blocked_wrong = blocked - blocked_correct
        marked: list[CaseResult] = []
        for result in scored:
            if result.correct and blocked_correct:
                blocked_correct -= 1
                marked.append(replace(result, blocked_by=note))
            elif not result.correct and blocked_wrong:
                blocked_wrong -= 1
                marked.append(replace(result, blocked_by=note))
            else:
                marked.append(result)
        scored = marked

        self.results = scored + [
            CaseResult(case_id="", level="", correct=False, skipped=True, error=note)
            for _ in range(int(payload.get("skipped") or 0))
        ]


__all__ = ["Case", "CaseResult", "RunRecord", "Suite"]
