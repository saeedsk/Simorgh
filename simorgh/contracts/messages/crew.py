"""`crew.*` -- agents started by other agents, and what they say to each
other (stage 18: docs/plan/stage-18-agent-crews.md, "Definitions").

A crew is the tree of agents under one root session. `crew_id` is the
root's task or session id; a member's `handle` is its task id. The crew
is recorded on the ledger stream `crew:<crew_id>`
(`streamnames.crew_stream`), one event per change, never edited.

Four bus topics:
- `crew.spawned`  a member started;
- `crew.message`  a typed message between members (`kind` below);
- `crew.report`   a member's final `Report`;
- `crew.cancel`   stop a member, and by default its descendants.

Two more event types live only on the `crew:<id>` stream, the way
`session.turn.appended` lives only on `session:<id>`: `crew.member.status`
(a member's status changed) and `crew.board` (a blackboard write, last
write wins).

The data model is A2A's (`contracts/a2a.py` maps it both ways): member
status is an A2A task state, a `crew.message` is an A2A `Message`, a
`Report` is an A2A `Task` with artifacts. Anything long is a ledger blob
ref, never inline: messages carry conclusions and references, not
transcripts.

`Member`, `Report` and `MemberBudget` are pure shapes, not messages:
`to_dict`/`from_dict` round-trip and `validate_*` return the problems.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

# --- vocabularies (do not rename: the plan's Definitions) -------------------

#: A member's lifecycle. `waiting` is A2A's `input-required` (an
#: `ask_parent` outstanding, or suspended in `await_agents`).
MEMBER_STATUS = ("starting", "running", "waiting", "done", "failed", "blocked", "cancelled")
#: The statuses a member never leaves.
TERMINAL_STATUS = ("done", "failed", "blocked", "cancelled")
REPORT_STATUS = ("ok", "partial", "failed", "blocked", "cancelled")
MESSAGE_KIND = ("progress", "milestone", "question", "answer", "steer", "note", "report")
ISOLATION = ("fresh", "fork")
#: `every_steps:N` and `every_s:T` carry a number after the colon.
REPORT_POLICIES = ("end", "progress", "every_steps", "every_s", "milestones", "silent")

SUMMARY_MAX = 1200
FINDINGS_MAX = 20
BOARD_VALUE_MAX = 2000

#: Ledger event types on `crew:<id>` that are not bus topics.
MEMBER_STATUS_CHANGED = "crew.member.status"   # {handle, status, reason?}
BOARD = "crew.board"                           # {handle, key, value}
STREAM_EVENTS = (t.CREW_SPAWNED, t.CREW_MESSAGE, t.CREW_REPORT, t.CREW_CANCEL,
                 MEMBER_STATUS_CHANGED, BOARD)

# --- schema nodes -------------------------------------------------------------

BUDGET = Obj(
    O("steps", Int),
    O("tokens", Int),
    O("usd", Float),
    O("wall_s", Float),
)
FINDING = Obj(F("claim", Str), O("evidence_ref", Str))
REPORT = Obj(
    F("status", Enum(*REPORT_STATUS)),
    F("summary", Str),                  # <= SUMMARY_MAX characters (validate_report)
    O("findings", List(FINDING)),       # <= FINDINGS_MAX items
    O("artifacts", List(Str)),          # blob or path refs
    O("steps", Int),
    O("tokens", Int),
    O("cost_usd", Float),
    O("wall_s", Float),
    O("questions_unanswered", List(Str)),
)

# --- the four topics ------------------------------------------------------------

CrewSpawned = define(t.CREW_SPAWNED, [
    F("crew_id", Str),
    F("handle", Str),
    F("parent", Str),                   # the parent's handle; the root session id for a first-level member
    F("agent", Str),
    F("brief_ref", Str),                # a blob ref, or the brief itself when it is short
    F("report_policy", Str),            # parse_report_policy() reads it
    F("budget", BUDGET),
    O("depth", Int),
    O("isolation", Enum(*ISOLATION)),
    O("background", Bool),
], doc="A crew member started. Producer: orchestration. Also the first event on crew:<id> for that member.")

CrewMessage = define(t.CREW_MESSAGE, [
    F("crew_id", Str),
    F("from", Str),                     # sender handle (attribute `from_` on the dataclass)
    F("to", Str),                       # recipient handle
    F("kind", Enum(*MESSAGE_KIND)),
    F("body", Str),
    F("seq", Int),                      # per-crew sequence, from 1
    O("refs", List(Str)),
    O("reply_to", Int),                 # the seq this answers
], doc="One typed message between members; an A2A Message. A question always reaches the parent.")

CrewReport = define(t.CREW_REPORT, [
    F("crew_id", Str),
    F("handle", Str),
    F("report", REPORT),
], doc="A member's final typed Report; an A2A Task with artifacts.")

CrewCancel = define(t.CREW_CANCEL, [
    F("crew_id", Str),
    F("handle", Str),
    F("reason", Str),
    O("cascade", Bool),                 # absent means true: descendants are cancelled too
], doc="Stop a member; the crew budget running out cancels every member with reason 'crew budget'.")


CrewSpawn = define(t.CREW_SPAWN, [
    F("agent", Str),
    F("brief", Str),
    F("requester", Str),                # the person the crew acts for; "" when the caller names nobody
    F("requester_channel", Str),        # e.g. "a2a"
    O("device", Str),                   # the paired device that asked
    O("report", Str),                   # report policy for the member; parse_report_policy() reads it
    O("background", Bool),
    O("context_id", Str),               # the caller's own context, when it sent one; members sent with
                                        # the same one join one crew (`crew_id` = context_id)
    # A project's plan node (stage 18 item 4): Planning runs each ready node
    # of a project as a member of the crew rooted at the project.
    O("handle", Str),                   # the member's handle, chosen by the caller (the node's task id)
    O("subject", Str),                  # the file a patch node is about
    O("acceptance", List(Str)),         # what "done" means for the node; the verifier checks it
    O("max_steps", Int),                # the node's step cap (0/absent: the agent's own)
    O("plan_node", Bool),               # true: runs as the queued task would -- outside the crew's
                                        # member/dollar/wall bounds, verified, with a claimed task's
                                        # authority; only Planning may ask for it
], doc="Start a crew from outside any session: one member, the agent named, acting as `requester`. "
       "Producers: interface (the A2A server, stage 18 item 10), planning (a project's ready plan "
       "nodes, item 4). Consumer: orchestration, which answers with the member's handle and the "
       "crew it roots, or an error reply.")
CrewSpawnReply = define(t.CREW_SPAWN_REPLY, [
    F("crew_id", Str),
    F("handle", Str),
])


# --- pure shapes ------------------------------------------------------------------


@dataclass(frozen=True)
class MemberBudget:
    steps: int = 0                      # 0: no limit of this kind
    tokens: int = 0
    usd: float = 0.0
    wall_s: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in (("steps", self.steps), ("tokens", self.tokens),
                                  ("usd", self.usd), ("wall_s", self.wall_s)) if v}

    @classmethod
    def from_dict(cls, data: dict | None) -> "MemberBudget":
        data = data or {}
        return cls(steps=int(data.get("steps") or 0), tokens=int(data.get("tokens") or 0),
                   usd=float(data.get("usd") or 0.0), wall_s=float(data.get("wall_s") or 0.0))


@dataclass(frozen=True)
class Member:
    handle: str
    agent: str
    parent: str = ""
    depth: int = 1
    status: str = "starting"
    budget: MemberBudget = field(default_factory=MemberBudget)
    report_policy: str = "end"
    isolation: str = "fresh"
    crew_id: str = ""

    def to_dict(self) -> dict:
        return {"crew_id": self.crew_id, "handle": self.handle, "agent": self.agent,
                "parent": self.parent, "depth": self.depth, "status": self.status,
                "budget": self.budget.to_dict(), "report_policy": self.report_policy,
                "isolation": self.isolation}

    @classmethod
    def from_dict(cls, data: dict) -> "Member":
        return cls(handle=str(data.get("handle", "")), agent=str(data.get("agent", "")),
                   parent=str(data.get("parent", "")), depth=int(data.get("depth", 1) or 0),
                   status=str(data.get("status", "starting")),
                   budget=MemberBudget.from_dict(data.get("budget")),
                   report_policy=str(data.get("report_policy", "end")),
                   isolation=str(data.get("isolation", "fresh")),
                   crew_id=str(data.get("crew_id", "")))


@dataclass(frozen=True)
class Finding:
    claim: str
    evidence_ref: str = ""

    def to_dict(self) -> dict:
        return {"claim": self.claim, **({"evidence_ref": self.evidence_ref} if self.evidence_ref else {})}


@dataclass(frozen=True)
class Report:
    status: str
    summary: str
    findings: tuple[Finding, ...] = ()
    artifacts: tuple[str, ...] = ()
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    wall_s: float = 0.0
    questions_unanswered: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """The `crew.report` payload's `report`: every key, always."""
        return {"status": self.status, "summary": self.summary,
                "findings": [f.to_dict() for f in self.findings],
                "artifacts": list(self.artifacts), "steps": self.steps, "tokens": self.tokens,
                "cost_usd": self.cost_usd, "wall_s": self.wall_s,
                "questions_unanswered": list(self.questions_unanswered)}

    @classmethod
    def from_dict(cls, data: dict) -> "Report":
        return cls(
            status=str(data.get("status", "")), summary=str(data.get("summary", "")),
            findings=tuple(Finding(str(f.get("claim", "")), str(f.get("evidence_ref") or ""))
                           for f in data.get("findings") or () if isinstance(f, dict)),
            artifacts=tuple(str(a) for a in data.get("artifacts") or ()),
            steps=int(data.get("steps") or 0), tokens=int(data.get("tokens") or 0),
            cost_usd=float(data.get("cost_usd") or 0.0), wall_s=float(data.get("wall_s") or 0.0),
            questions_unanswered=tuple(str(q) for q in data.get("questions_unanswered") or ()))


def validate_report(report: Report | dict) -> list[str]:
    """The rules the schema cannot say: the status, and the size caps that
    keep a report a conclusion rather than a transcript."""
    r = report if isinstance(report, Report) else Report.from_dict(report)
    problems = []
    if r.status not in REPORT_STATUS:
        problems.append(f"status {r.status!r} is not one of {', '.join(REPORT_STATUS)}")
    if len(r.summary) > SUMMARY_MAX:
        problems.append(f"summary is {len(r.summary)} characters; at most {SUMMARY_MAX} (put the rest in a blob ref)")
    if len(r.findings) > FINDINGS_MAX:
        problems.append(f"{len(r.findings)} findings; at most {FINDINGS_MAX}")
    if any(not f.claim for f in r.findings):
        problems.append("a finding has no claim")
    return problems


def validate_member(member: Member) -> list[str]:
    problems = []
    if not member.handle:
        problems.append("member has no handle")
    if member.status not in MEMBER_STATUS:
        problems.append(f"status {member.status!r} is not one of {', '.join(MEMBER_STATUS)}")
    if member.isolation not in ISOLATION:
        problems.append(f"isolation {member.isolation!r} is not one of {', '.join(ISOLATION)}")
    try:
        parse_report_policy(member.report_policy)
    except ValueError as exc:
        problems.append(str(exc))
    return problems


def parse_report_policy(text: str) -> tuple[str, float]:
    """`"end"` -> ("end", 0); `"every_steps:5"` -> ("every_steps", 5);
    `"every_s:30"` -> ("every_s", 30.0). ValueError for anything else,
    including a missing, non-positive or non-finite number (`every_s:nan`
    would never fire, `every_s:inf` is `silent` under another name)."""
    name, _, arg = (text or "end").strip().partition(":")
    if name not in REPORT_POLICIES:
        raise ValueError(f"report policy {text!r} is not one of {', '.join(REPORT_POLICIES)}")
    if name in ("every_steps", "every_s"):
        try:
            n = int(arg) if name == "every_steps" else float(arg)
        except ValueError:
            raise ValueError(f"report policy {text!r} needs a number after the colon") from None
        if not math.isfinite(n) or n <= 0:
            raise ValueError(f"report policy {text!r} needs a positive number")
        return name, n
    if arg:
        raise ValueError(f"report policy {name!r} takes no argument")
    return name, 0


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUS


__all__ = [
    "BOARD", "BOARD_VALUE_MAX", "CrewCancel", "CrewMessage", "CrewReport", "CrewSpawn", "CrewSpawnReply",
    "CrewSpawned",
    "FINDINGS_MAX", "Finding", "ISOLATION", "MEMBER_STATUS", "MEMBER_STATUS_CHANGED", "MESSAGE_KIND",
    "Member", "MemberBudget", "REPORT_POLICIES", "REPORT_STATUS", "Report", "STREAM_EVENTS",
    "SUMMARY_MAX", "TERMINAL_STATUS", "is_terminal", "parse_report_policy",
    "validate_member", "validate_report",
]
