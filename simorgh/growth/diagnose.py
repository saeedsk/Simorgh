"""What keeps going wrong, found by counting rather than by asking (stage 8 item 3).

Reflection already asks a model "what patterns do you see in these
failures?", which is expensive, unrepeatable, and answers with something
plausible whether or not a pattern exists. Failures cluster on facts that
are already recorded: the task type, the verify check that failed, the
tool that was denied, what the checkpoint critic said was unmet. Counting
those is deterministic, costs nothing, and a cluster either clears the
bar or does not.

The model is asked one thing only, and only afterwards: to phrase the
lesson. Phrasing is what it is good at; deciding what counts as a pattern
is not.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

#: A cluster is worth a lesson at this many failures. Three is the
#: smallest number that is not a coincidence and not an anecdote.
MIN_MEMBERS = 3


@dataclass(frozen=True)
class Failure:
    """One terminal failure, as the ledger already records it."""

    task_id: str
    task_type: str
    failed_check: str = ""      # the verify check that came back false
    denied_tool: str = ""       # the tool Guardian refused
    unmet: str = ""             # what the checkpoint critic said was unmet
    reason: str = ""

    def key(self) -> tuple[str, str, str, str]:
        """What makes two failures the same failure."""
        return (self.task_type, self.failed_check, self.denied_tool, _norm(self.unmet))


@dataclass
class Cluster:
    """Failures that are the same failure, and how unusual that is."""

    key: tuple[str, str, str, str]
    members: list[Failure] = field(default_factory=list)
    share: float = 0.0          # of this task type's failures
    baseline: float = 0.0       # of every other type's

    @property
    def task_type(self) -> str:
        return self.key[0]

    def describe(self) -> str:
        what = self.key[1] or self.key[2] or self.key[3] or "no recorded cause"
        return f"{len(self.members)} {self.task_type} failures share: {what}"


def cluster(failures, *, min_members: int = MIN_MEMBERS) -> list[Cluster]:
    """The clusters worth a lesson, biggest first.

    A cluster must be above the baseline for other task types as well as
    big enough: "patch tasks fail" is not a lesson, and neither is a
    failure mode every kind of task has equally.
    """
    by_key: dict[tuple, list[Failure]] = {}
    for failure in failures:
        if not failure.task_type:
            continue
        by_key.setdefault(failure.key(), []).append(failure)
    per_type = Counter(f.task_type for f in failures)
    out: list[Cluster] = []
    for key, members in by_key.items():
        if len(members) < min_members:
            continue
        if not (key[1] or key[2] or key[3]):
            continue        # "these failed, cause unrecorded" is not a pattern
        task_type = key[0]
        share = len(members) / max(1, per_type[task_type])
        elsewhere = [f for f in failures if f.task_type != task_type]
        baseline = (sum(1 for f in elsewhere if f.key()[1:] == key[1:]) / len(elsewhere)) if elsewhere else 0.0
        if share <= baseline:
            continue        # every type has this one; it is not about this type
        out.append(Cluster(key=key, members=list(members), share=round(share, 3), baseline=round(baseline, 3)))
    out.sort(key=lambda c: (-len(c.members), c.key))
    return out


def phrasing_prompt(cluster: Cluster) -> str:
    """What to ask a model once the counting is done."""
    examples = "\n".join(f"- {m.reason[:160]}" for m in cluster.members[:5])
    return (
        "These failures are the same failure. Write the one sentence of advice that would have "
        "prevented them, addressed to whoever does this kind of work next. No preamble, no "
        "restating the failures, nothing you cannot see below.\n\n"
        f"Kind of task: {cluster.task_type}\n"
        f"What they share: {cluster.key[1] or cluster.key[2] or cluster.key[3]}\n"
        f"How they read:\n{examples}"
    )


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())[:120]


__all__ = ["Cluster", "Failure", "MIN_MEMBERS", "cluster", "phrasing_prompt"]
