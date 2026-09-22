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

#: A failure mode that shows up in this many task types is a property of
#: the system, not a lesson about any one kind of work. A timeout is the
#: example: patch tasks time out, research tasks time out, and "patch
#: tasks time out" is advice nobody can act on.
GENERAL_ACROSS = 3


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

    A cluster must be big enough, above the baseline for other task
    types, and not seen across `GENERAL_ACROSS` kinds of work: "patch
    tasks fail" is not a lesson, and neither is a failure mode every
    kind of task has equally. The last test exists because the share
    test alone does not catch it -- a task type whose only failures are
    timeouts scores a share of 1.0 and looks specific to itself.
    """
    by_key: dict[tuple, list[Failure]] = {}
    for failure in failures:
        if not failure.task_type:
            continue
        by_key.setdefault(failure.key(), []).append(failure)
    per_type = Counter(f.task_type for f in failures)
    # How many task types each SIGNATURE (the key without the type)
    # shows up in, at strength. See `GENERAL_ACROSS`.
    spread: Counter = Counter()
    for key, members in by_key.items():
        if len(members) >= min_members:
            spread[key[1:]] += 1
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
        if spread[key[1:]] >= GENERAL_ACROSS:
            # Seen in this many kinds of work, it is a property of the
            # system rather than a lesson about this kind. The share
            # test above does not catch it: a type whose ONLY failures
            # are timeouts scores a share of 1.0 and looks specific.
            continue
        out.append(Cluster(key=key, members=list(members), share=round(share, 3), baseline=round(baseline, 3)))
    out.sort(key=lambda c: (-len(c.members), c.key))
    return out


@dataclass(frozen=True)
class Candidate:
    """One thing that might be worth a lesson, whatever found it.

    The fold (stage 8 item 3). Three things used to notice that
    something keeps going wrong, in three shapes nobody could compare:
    this module's failure clusters, the monitors' denial miner (the
    same tool refused for the same reason, again and again) and its
    pattern miner (a task type whose success rate has fallen). They
    are all the same claim -- *this keeps happening, and it is
    specific enough to say something about* -- so they arrive here as
    one shape, and one place decides what is worth phrasing.

    `count` is what makes it a pattern rather than an anecdote;
    `evidence` is what a person would want to read before believing it.
    """

    source: str                 # failures | denials | patterns
    what: str                   # the shared cause, in as few words as it takes
    count: int
    subject: str = ""           # the task type or the tool it is about
    evidence: tuple[str, ...] = ()
    #: Where a person can read the evidence: `task:<id>` for each member
    #: of a failure cluster, `reflect:patterns:<task_type>` for the
    #: pattern miner's window. A policy drafted from this candidate
    #: carries these as its `evidence_refs` (`propose.py`).
    refs: tuple[str, ...] = ()

    def describe(self) -> str:
        about = f" in {self.subject}" if self.subject else ""
        return f"{self.count}x{about}: {self.what}"


def from_clusters(clusters) -> list[Candidate]:
    return [Candidate(source="failures", what=(c.key[1] or c.key[2] or c.key[3]),
                      count=len(c.members), subject=c.task_type,
                      evidence=tuple(m.reason[:160] for m in c.members[:5] if m.reason),
                      refs=tuple(f"task:{m.task_id}" for m in c.members if m.task_id))
            for c in clusters]


def from_denials(counts, *, min_repeats: int = 5) -> list[Candidate]:
    """The denial miner's window as lesson candidates.

    `counts` is `{(tool, reason): n}` -- `monitors.denials.DenialMiner.
    counts()`. A tool refused for the same reason over and over is
    either a rule that is wrong for that tool or a tool being asked
    for in the wrong kind of session, and either way somebody should
    know.
    """
    out = [Candidate(source="denials", what=reason, count=n, subject=tool)
           for (tool, reason), n in (counts or {}).items() if n >= min_repeats and tool and reason]
    out.sort(key=lambda c: (-c.count, c.subject, c.what))
    return out


def from_patterns(patterns) -> list[Candidate]:
    """The pattern miner's findings as lesson candidates: a task type
    whose failure rate over the window is worth saying out loud."""
    return [Candidate(source="patterns", what=f"{p.kind} {p.rate:.0%}", count=1,
                      subject=p.task_type, evidence=(p.proposal[:200],) if p.proposal else (),
                      refs=(f"reflect:patterns:{p.task_type}",) if p.task_type else ())
            for p in (patterns or ())]


def candidates(failures=(), *, denials=None, patterns=(), min_members: int = MIN_MEMBERS,
               min_repeats: int = 5) -> list[Candidate]:
    """Everything worth a lesson right now, from all three sources,
    strongest first (stage 8 item 3).

    This is the only entry point a caller needs. Counting decides what
    is here; a model is asked one thing afterwards, and only about
    what is already in the list.
    """
    found = (from_clusters(cluster(failures, min_members=min_members))
             + from_denials(denials, min_repeats=min_repeats)
             + from_patterns(patterns))
    found.sort(key=lambda c: (-c.count, c.source, c.subject, c.what))
    return found


def candidate_prompt(candidate: Candidate) -> str:
    """What to ask a model once the counting is done -- for any source."""
    lines = "\n".join(f"- {e}" for e in candidate.evidence)
    return (
        "This keeps happening. Write the one sentence of advice that would have prevented it, "
        "addressed to whoever does this kind of work next. No preamble, no restating the "
        "problem, nothing you cannot see below.\n\n"
        f"What it is about: {candidate.subject or 'this system'}\n"
        f"What keeps happening ({candidate.count} times): {candidate.what}"
        + (f"\nHow it reads:\n{lines}" if lines else "")
    )


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


__all__ = ["Candidate", "Cluster", "Failure", "GENERAL_ACROSS", "MIN_MEMBERS", "candidate_prompt",
           "candidates", "cluster", "from_clusters", "from_denials", "from_patterns", "phrasing_prompt"]
