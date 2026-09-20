"""What went wrong, in a form somebody can act on (stage 11 item 10).

A run that says "3 expectations failed" has told nobody anything. The
person who fixes it then spends the first twenty minutes doing what
the run already did: working out which scenario, which beat, what Sim
actually said, and whether it happens every time.

So a failure here carries its reproduction. One command that runs it
again, the beat it died on, what Sim said and printed around it, and
whether the other repeats agreed. Failures that share a shape are one
cluster with one command, because five reports of one bug are four
pieces of noise.

The acting half is deliberately not Sim's. This writes findings and
appends candidates to the counting Sim already does (`growth:
candidates`); a person or an agent holding the module lock fixes the
cluster and runs the command again.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cluster:
    """Failures that are the same failure."""

    expectation: str        # "quiet", "identified as Devin", ...
    stage: str
    why: str                # the first one's reason, as the example
    scenarios: tuple = ()   # the scenario ids it shows up in
    beats: tuple = ()       # the beats it died on
    count: int = 1
    flaky: bool = False     # it passed on another repeat of the same scenario

    @property
    def command(self) -> str:
        """How to see it again."""
        first = self.scenarios[0] if self.scenarios else ""
        return f"python -m simorgh.evals house --one {first} --timing" if first else \
               "python -m simorgh.evals house"

    def describe(self) -> str:
        where = self.scenarios[0] if self.scenarios else "?"
        flaky = " (flaky: it passed on another run)" if self.flaky else ""
        return f"{self.count}x {self.expectation} in {where}{flaky}"


def cluster(outcomes, *, scenario_of=None) -> list[Cluster]:
    """Group the failures by what they are, worst first.

    The key is `(expectation, stage)` and not the scenario: the same
    expectation failing in three scenarios is usually one bug in Sim,
    and reporting it three times is how a list stops being read.
    """
    by_key: dict = {}
    passed_in: set = set()
    for outcome in outcomes:
        name, stage = outcome.case.name, outcome.case.level
        where = (scenario_of or {}).get(id(outcome), "") or str(outcome.case.detail.get("scenario", ""))
        if outcome.status == "passed":
            passed_in.add((name, stage))
            continue
        if outcome.status != "failed":
            continue
        row = by_key.setdefault((name, stage), {"why": outcome.why, "scenarios": [], "beats": [], "count": 0})
        row["count"] += 1
        if where and where not in row["scenarios"]:
            row["scenarios"].append(where)
        beat = str(outcome.case.detail.get("beat") or "")
        if beat and beat not in row["beats"]:
            row["beats"].append(beat)
    out = [Cluster(expectation=name, stage=stage, why=row["why"], scenarios=tuple(row["scenarios"]),
                   beats=tuple(row["beats"]), count=row["count"], flaky=(name, stage) in passed_in)
           for (name, stage), row in by_key.items()]
    out.sort(key=lambda c: (c.flaky, -c.count, c.expectation))
    return out


@dataclass
class Findings:
    """One run, written down."""

    outcomes: list = field(default_factory=list)
    clusters: list = field(default_factory=list)
    timing = None
    at: float = field(default_factory=time.time)

    @property
    def counted(self) -> list:
        return [o for o in self.outcomes if o.status != "skipped"]

    def render(self) -> str:
        passed = sum(1 for o in self.counted if o.status == "passed")
        by_stage = Counter(o.case.level for o in self.counted)
        lines = [f"# The house, {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.at))}", "",
                 f"{passed}/{len(self.counted)} expectations across "
                 f"{len(by_stage)} stage(s); {len(self.outcomes) - len(self.counted)} skipped.", ""]
        if not self.clusters:
            lines.append("Nothing failed.")
        for index, found in enumerate(self.clusters, start=1):
            lines += [f"## {index}. {found.describe()}", "",
                      f"- **stage** {found.stage or '-'}",
                      f"- **why** {found.why}",
                      f"- **beat** {found.beats[0] if found.beats else '-'}",
                      f"- **again** `{found.command}`", ""]
        if self.timing is not None:
            lines += ["## Where the seconds went", "", "```", self.timing.render(), "```", ""]
        return "\n".join(lines)

    def as_candidates(self) -> list[dict]:
        """The clusters as `growth:candidates` rows, so the counting
        Sim already does sees what the simulator found. Proposing is
        as far as it goes -- acting on one is a person's, through the
        lock."""
        return [{"source": "house", "subject": found.scenarios[0] if found.scenarios else "",
                 "what": f"{found.expectation}: {found.why}"[:300], "count": found.count,
                 "evidence": list(found.beats[:3])}
                for found in self.clusters if not found.flaky]


def write(findings: Findings, path) -> object:
    """The findings beside every other dated measurement."""
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(findings.render(), encoding="utf-8")
    return path


__all__ = ["Cluster", "Findings", "cluster", "write"]
