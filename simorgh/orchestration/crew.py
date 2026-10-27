"""Agent crews (stage 18 item 2, docs/plan/stage-18-agent-crews.md).

A crew is the tree of agents under one root session: the root, the
members it spawned, the members they spawned. This module is the core of
it, testable without a bus: who is in the crew and in what state, how a
member's budget is carved from what is left, how many run at once (and
how many of those may write), how a cancel reaches the descendants, which
messages a parent hears under its report policy, the shared blackboard,
and the `crew:<id>` fold a restart rebuilds the tree from.

The session wiring (spawn, await_agents, ask_parent ...) is in
`session.py`; the shapes are the contracts' (`contracts/messages/crew.py`),
and every payload built here carries exactly their field names.

Nothing here talks to a model or to Guardian. The crew tools coordinate;
everything a member does in the world is still a proposal.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from simorgh.contracts import topics
from simorgh.contracts.messages.crew import (
    BOARD, BOARD_VALUE_MAX, FINDINGS_MAX, MEMBER_STATUS_CHANGED, SUMMARY_MAX, Finding, MemberBudget, Report,
    is_terminal, parse_report_policy,
)

#: The cancel reason when the crew's dollars, tokens or wall-clock run out.
#: A member cancelled for it reports `partial`, not `cancelled`: what it
#: found so far is still worth having.
CREW_BUDGET = "crew budget"
#: A brief longer than this goes to a blob and `brief_ref` names it.
BRIEF_INLINE_MAX = 1000
#: The most of one claim a parsed finding keeps.
CLAIM_MAX = 300

Append = Callable[[str, dict], Awaitable[None]]


class CrewRefused(Exception):
    """A spawn the crew will not take; the text is what the model is told."""


class Inbox:
    """One member's undelivered messages, in arrival order (the plan's
    "one `asyncio.Queue` per member"). Rendered once, at the head of the
    member's next think, after the cacheable prefix."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        #: Undelivered questions: an `await_agents` wakes on one.
        self.questions = 0

    def put(self, message: dict) -> None:
        self._queue.put_nowait(dict(message))
        if message.get("kind") == "question":
            self.questions += 1

    def drain(self) -> list[dict]:
        out = []
        while not self._queue.empty():
            out.append(self._queue.get_nowait())
        self.questions = 0
        return out

    def take_answer(self, seq: int) -> dict | None:
        """The answer to question `seq`, taken out; the rest stay queued."""
        found, kept = None, []
        for message in self.drain():
            if found is None and message.get("kind") == "answer" and int(message.get("reply_to") or 0) == seq:
                found = message
            else:
                kept.append(message)
        for message in kept:
            self.put(message)
        return found

    def __len__(self) -> int:
        return self._queue.qsize()


def render_inbox(messages: list[dict]) -> str:
    """One compact `inbox` turn: who said what, one line each. Conclusions
    and refs, never transcripts -- a body is already capped at send."""
    if not messages:
        return ""
    lines = [f"[crew inbox] {len(messages)} message{'s' if len(messages) != 1 else ''} since your last step:"]
    for m in messages:
        head = f"- from {m.get('from')} ({m.get('kind')} #{m.get('seq')})"
        refs = f" [refs: {', '.join(m.get('refs') or ())}]" if m.get("refs") else ""
        lines.append(f"{head}: {m.get('body')}{refs}")
    if any(m.get("kind") == "question" for m in messages):
        lines.append("Answer a question with send_agent{to: <handle>, kind: \"answer\", text}; "
                     "the member is waiting for it.")
    return "\n".join(lines)


@dataclass
class CrewMember:
    """One member's live state. `Member` (contracts) is its frozen view."""

    handle: str
    agent: str
    parent: str
    depth: int = 1
    status: str = "starting"
    budget: MemberBudget = field(default_factory=MemberBudget)
    report_policy: str = "end"
    isolation: str = "fresh"
    writer: bool = False
    via: str = "spawn"            # "spawn" | "delegate" (delegate keeps its old shape)
    # Who asked, as Guardian sees it on every proposal (`Session.speaker`,
    # `Session.channel`): kept on `crew.spawned` so a member resumed after
    # a restart acts for the same person, never for the owner's console.
    requester: str = ""
    requester_channel: str = ""
    brief: str = ""
    brief_ref: str = ""
    brief_blob: bool = False      # `brief_ref` is a ledger blob, not the brief
    background: bool = False
    last_progress: str = ""
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    started_at: float = 0.0
    report: Report | None = None
    collected: bool = False       # the parent has had this report (await_agents)
    cancel_reason: str = ""
    questions_unanswered: list = field(default_factory=list)
    # The periodic-report engine's last mark.
    reported_step: int = 0
    reported_at: float = 0.0
    task: object = None           # the asyncio task running it, in this process


class Crew:
    """The tree under one root session, and every rule the plan puts on it.

    `append(type, payload)` writes one event to `crew:<crew_id>` (and the
    caller publishes it where it is a topic). `now` is a monotonic clock.
    """

    def __init__(self, crew_id: str, *, append: Append | None = None, now=time.monotonic,
                 max_members: int = 8, max_concurrent: int = 4, max_writers: int = 1,
                 max_usd: float = 0.5, max_wall_s: float = 900.0, max_tokens: int = 0) -> None:
        self.crew_id = crew_id
        self.root = crew_id
        self._append = append
        self._now = now
        self.max_members = max(1, int(max_members))
        self.max_concurrent = max(1, int(max_concurrent))
        self.max_writers = max(1, int(max_writers))
        self.max_usd = max(0.0, float(max_usd))
        self.max_wall_s = max(0.0, float(max_wall_s))
        self.max_tokens = max(0, int(max_tokens))
        self.members: dict[str, CrewMember] = {}
        self.inboxes: dict[str, Inbox] = {crew_id: Inbox()}
        self.board: dict[str, dict] = {}
        #: The open question each member asked its parent: asker -> seq.
        self.questions: dict[str, int] = {}
        self.seq = 0
        self.spent_usd = 0.0
        self.spent_tokens = 0
        #: When the first `spawn` member joined: the crew's wall-clock runs
        #: from there. None while the crew has only `delegate` helpers.
        self.started: float | None = None
        self.exhausted = ""
        #: refs a report, message or board value has named: `read_ref` reads only these.
        self.refs: set[str] = set()
        #: the root's last `await_agents`, so a restarted root re-enters it.
        self.root_await: dict | None = None
        #: One per parent, so a member waiting on its own children never
        #: holds the slot they need (`max_children_concurrent` per parent).
        self._running: dict[str, asyncio.Semaphore] = {}
        self._writing = asyncio.Semaphore(self.max_writers)
        self._changed = asyncio.Event()

    # -- the tree ------------------------------------------------------------------------

    def children(self, parent: str) -> list[CrewMember]:
        return [m for m in self.members.values() if m.parent == parent]

    def descendants(self, handle: str) -> list[CrewMember]:
        out, frontier = [], [handle]
        while frontier:
            kids = [m for p in frontier for m in self.children(p)]
            out.extend(kids)
            frontier = [k.handle for k in kids]
        return out

    def parent_of(self, handle: str) -> str:
        member = self.members.get(handle)
        return member.parent if member else ""

    def is_cancelled(self, handle: str) -> bool:
        member = self.members.get(handle)
        return bool(member and member.cancel_reason)

    def live(self) -> list[CrewMember]:
        return [m for m in self.members.values() if not is_terminal(m.status)]

    @staticmethod
    def bounded(member: CrewMember) -> bool:
        """Whether the crew's bounds (members, dollars, tokens, wall-clock)
        apply to `member`. A `delegate` helper keeps the bounds it always
        had -- its step cap, one at a time, its parent's own budget -- so a
        task that delegates is not refused or cut short by a crew it never
        asked for (the plan: "with `delegate` used as today, the behaviour
        is unchanged")."""
        return member.via != "delegate"

    def _elapsed(self) -> float:
        return self._now() - self.started if self.started is not None else 0.0

    # -- budgets -------------------------------------------------------------------------

    def remaining(self) -> MemberBudget:
        """What the crew has left; 0 in a field means that kind is unbounded."""
        usd = max(0.0, self.max_usd - self.spent_usd) if self.max_usd else 0.0
        tokens = max(0, self.max_tokens - self.spent_tokens) if self.max_tokens else 0
        wall = max(0.0, self.max_wall_s - self._elapsed()) if self.max_wall_s else 0.0
        return MemberBudget(tokens=tokens, usd=usd, wall_s=wall)

    def carve(self, parent: str, asked: MemberBudget) -> MemberBudget:
        """A child's budget, carved from what its parent has left: never
        more than it asked for, its parent's own budget less what that
        parent has spent, or the crew's remainder."""
        crew = self.remaining()
        up = self.members.get(parent)
        if up is not None:
            mine = MemberBudget(
                tokens=max(0, up.budget.tokens - up.tokens) if up.budget.tokens else 0,
                usd=max(0.0, up.budget.usd - up.cost_usd) if up.budget.usd else 0.0,
                wall_s=max(0.0, up.budget.wall_s - (self._now() - up.started_at)) if up.budget.wall_s else 0.0,
            )
        else:
            mine = MemberBudget()

        def least(*values):
            bounded = [v for v in values if v]
            return min(bounded) if bounded else type(values[0])(0)

        return MemberBudget(
            steps=asked.steps,
            tokens=least(asked.tokens, mine.tokens, crew.tokens),
            usd=round(least(asked.usd, mine.usd, crew.usd), 6),
            wall_s=round(least(asked.wall_s, mine.wall_s, crew.wall_s), 3),
        )

    def over_budget(self) -> str:
        """Which crew bound is spent, or ""."""
        if self.exhausted:
            return self.exhausted
        if self.max_usd and self.spent_usd >= self.max_usd:
            return f"usd (${self.spent_usd:.3f} of ${self.max_usd:.2f})"
        if self.max_tokens and self.spent_tokens >= self.max_tokens:
            return f"tokens ({self.spent_tokens} of {self.max_tokens})"
        if self.max_wall_s and self.started is not None and self._elapsed() >= self.max_wall_s:
            return f"wall ({self._elapsed():.0f} s of {self.max_wall_s:.0f} s)"
        return ""

    async def charge(self, handle: str, *, usd: float = 0.0, tokens: int = 0) -> str:
        """Count what a member's think cost. Returns the bound that ran out
        (and has cancelled every member), or ""."""
        member = self.members.get(handle)
        if member is not None:
            member.cost_usd += float(usd or 0.0)
            member.tokens += int(tokens or 0)
            if not self.bounded(member):
                return ""
        self.spent_usd += float(usd or 0.0)
        self.spent_tokens += int(tokens or 0)
        return await self.enforce()

    async def enforce(self) -> str:
        spent = self.over_budget()
        if spent and not self.exhausted:
            self.exhausted = spent
            for member in self.live():
                if self.bounded(member):
                    await self.cancel(member.handle, CREW_BUDGET, cascade=False, record=True)
        return spent

    # -- membership ----------------------------------------------------------------------

    def next_handle(self, parent: str) -> str:
        """`<parent>-h<n>`: the stage 7 helper ids, so `task:<handle>` streams
        keep their names, numbered across every child this parent ever had."""
        taken = {m.handle for m in self.members.values()}
        n = len(self.children(parent)) + 1
        while f"{parent}-h{n}" in taken:
            n += 1
        return f"{parent}-h{n}"

    async def admit(self, *, parent: str, agent: str, brief: str, depth: int, budget: MemberBudget,
                    report_policy: str = "end", isolation: str = "fresh", writer: bool = False,
                    via: str = "spawn", background: bool = False, brief_ref: str = "",
                    handle: str = "", requester: str = "", requester_channel: str = "") -> CrewMember:
        """Add a member and record `crew.spawned`; CrewRefused with the reason.
        `brief_ref` is a blob ref for a long brief; "" keeps it inline.
        A `delegate` helper is outside the crew's bounds (`bounded`)."""
        bounded = via != "delegate"
        counted = [m for m in self.members.values() if self.bounded(m)]
        if bounded and self.exhausted:
            raise CrewRefused(f"the crew budget is spent ({self.exhausted})")
        if bounded and len(counted) >= self.max_members:
            raise CrewRefused(f"the crew already has {len(counted)} members; "
                              f"{self.max_members} is the cap")
        parse_report_policy(report_policy)  # ValueError for the caller to say
        up = self.members.get(parent)
        while writer and up is not None:
            if up.writer:
                # It would wait for the writer slot its own ancestor holds.
                raise CrewRefused(f"{up.handle} is a writer already; a writer may not start another")
            up = self.members.get(up.parent)
        member = CrewMember(
            handle=handle or self.next_handle(parent), agent=agent, parent=parent, depth=depth,
            budget=budget, report_policy=report_policy, isolation=isolation, writer=writer, via=via,
            brief=brief, brief_ref=brief_ref or brief, brief_blob=bool(brief_ref), background=background,
            started_at=self._now(), requester=requester, requester_channel=requester_channel,
        )
        member.reported_at = member.started_at
        if bounded and self.started is None:
            self.started = member.started_at
        self.members[member.handle] = member
        self.inboxes.setdefault(member.handle, Inbox())
        await self._record(topics.CREW_SPAWNED, self.spawned_payload(member))
        self._notify()
        return member

    def spawned_payload(self, member: CrewMember) -> dict:
        return {
            "crew_id": self.crew_id, "handle": member.handle, "parent": member.parent, "agent": member.agent,
            "brief_ref": member.brief_ref, "report_policy": member.report_policy,
            "budget": member.budget.to_dict(), "depth": member.depth, "isolation": member.isolation,
            "background": member.background,
            # Extra fields (the schema admits them): what a restart needs to
            # run the member again as what it was.
            "via": member.via, "writer": member.writer, "brief_blob": member.brief_blob,
            "requester": member.requester, "requester_channel": member.requester_channel,
        }

    async def set_status(self, handle: str, status: str, reason: str = "") -> None:
        member = self.members.get(handle)
        if member is not None:
            if member.status == status or is_terminal(member.status):
                return
            member.status = status
        await self._record(MEMBER_STATUS_CHANGED, {"handle": handle, "status": status,
                                                   **({"reason": reason} if reason else {})})
        self._notify()

    class _Slot:
        def __init__(self, crew: "Crew", member: CrewMember) -> None:
            self._crew, self._member = crew, member

        async def __aenter__(self):
            running = self._crew._running.setdefault(self._member.parent, asyncio.Semaphore(self._crew.max_concurrent))
            await running.acquire()
            if self._member.writer:
                try:
                    await self._crew._writing.acquire()
                except BaseException:
                    running.release()
                    raise
            if not self._member.cancel_reason:
                await self._crew.set_status(self._member.handle, "running")
            return self._member

        async def __aexit__(self, *exc):
            if self._member.writer:
                self._crew._writing.release()
            self._crew._running[self._member.parent].release()
            return False

    def slot(self, member: CrewMember) -> "_Slot":
        """Held while a member runs: one of its parent's `max_concurrent`,
        and for a writer one of the crew's `max_writers` as well. A member
        waits for them in `starting`."""
        return Crew._Slot(self, member)

    # -- cancellation --------------------------------------------------------------------

    async def cancel(self, handle: str, reason: str, *, cascade: bool = True, record: bool = True) -> list[str]:
        """Cancel `handle` and, by default, everything under it. Cooperative:
        a running member stops at its next step boundary, a waiting one
        wakes now. Returns the handles cancelled."""
        targets = [self.members[handle]] if handle in self.members else []
        if cascade:
            targets += self.descendants(handle)
        hit = []
        for member in targets:
            if is_terminal(member.status) or member.cancel_reason:
                continue
            member.cancel_reason = reason or "cancelled"
            hit.append(member.handle)
        if record and (hit or handle in self.members):
            await self._record(topics.CREW_CANCEL, {"crew_id": self.crew_id, "handle": handle,
                                                    "reason": reason or "cancelled", "cascade": cascade})
        self._notify()
        return hit

    # -- messages ------------------------------------------------------------------------

    def policy_allows(self, sender: str, kind: str, *, milestone: bool = False, automatic: bool = False) -> bool:
        """Whether progress from `sender` reaches its parent under the policy
        the parent set at spawn (the plan's "Report policy")."""
        if kind == "question":
            return True
        if kind not in ("progress", "milestone"):
            return True
        member = self.members.get(sender)
        if member is None:
            return True
        name, _ = parse_report_policy(member.report_policy)
        if automatic:
            return name in ("every_steps", "every_s")
        if name == "progress":
            return True
        if name in ("milestones", "every_steps", "every_s"):
            return milestone or kind == "milestone"
        return False  # end, silent

    async def send(self, sender: str, to: str, kind: str, body: str, *, refs: tuple = (),
                   reply_to: int = 0, deliver: bool = True) -> dict:
        """Record one `crew.message` and, when `deliver`, queue it in the
        recipient's inbox and wake anybody waiting on the crew."""
        self.seq += 1
        payload = {"crew_id": self.crew_id, "from": sender, "to": to, "kind": kind,
                   "body": str(body), "seq": self.seq, "refs": [str(r) for r in refs or ()]}
        if reply_to:
            payload["reply_to"] = int(reply_to)
        self.refs.update(payload["refs"])
        self._track_question(payload)
        await self._record(topics.CREW_MESSAGE, payload)
        if deliver:
            self.inboxes.setdefault(to, Inbox()).put(payload)
        if kind in ("progress", "milestone") and sender in self.members:
            self.members[sender].last_progress = str(body)[:200]
        self._notify()
        return payload

    def _track_question(self, payload: dict) -> None:
        if payload.get("kind") == "question":
            self.questions[str(payload.get("from"))] = int(payload.get("seq") or 0)
        elif payload.get("kind") == "answer" and self.questions.get(str(payload.get("to"))) == payload.get("reply_to"):
            self.questions.pop(str(payload.get("to")), None)

    def progress_due(self, handle: str, steps: int) -> bool:
        """The periodic half of the engine: `every_steps:N` after N more
        steps, `every_s:T` after T more seconds. Marks the time when due."""
        member = self.members.get(handle)
        if member is None:
            return False
        name, n = parse_report_policy(member.report_policy)
        now = self._now()
        due = ((name == "every_steps" and steps - member.reported_step >= n)
               or (name == "every_s" and now - member.reported_at >= n))
        if due:
            member.reported_step, member.reported_at = steps, now
        return due

    # -- reports -------------------------------------------------------------------------

    async def file_report(self, handle: str, report: Report) -> None:
        member = self.members.get(handle)
        if member is not None:
            member.report = report
            member.steps = report.steps or member.steps
        self.refs.update(report.artifacts)
        self.refs.update(f.evidence_ref for f in report.findings if f.evidence_ref)
        await self._record(topics.CREW_REPORT, {"crew_id": self.crew_id, "handle": handle,
                                                "report": report.to_dict()})
        await self.set_status(handle, _status_of(report, cancelled=bool(member and member.cancel_reason)))
        self._notify()

    # -- blackboard ----------------------------------------------------------------------

    async def board_put(self, handle: str, key: str, value: str) -> str:
        """Last write wins; values over BOARD_VALUE_MAX are cut and say so."""
        value = str(value)
        if len(value) > BOARD_VALUE_MAX:
            value = value[:BOARD_VALUE_MAX - 1] + "…"
        self.board[key] = {"handle": handle, "key": key, "value": value}
        await self._record(BOARD, {"handle": handle, "key": key, "value": value})
        self._notify()
        return value

    # -- waiting -------------------------------------------------------------------------

    def _notify(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    async def wait_until(self, condition: Callable[[], bool], timeout_s: float) -> bool:
        """Suspend until `condition()` holds or `timeout_s` passes; wakes on
        every change to the crew (a report, a message, a status, a cancel),
        never by polling. True when the condition held."""
        deadline = self._now() + max(0.0, timeout_s)
        while not condition():
            left = deadline - self._now()
            if left <= 0:
                return False
            event = self._changed
            try:
                await asyncio.wait_for(event.wait(), timeout=left)
            except asyncio.TimeoutError:
                return condition()
        return True

    # -- the ledger ----------------------------------------------------------------------

    async def _record(self, type_: str, payload: dict) -> None:
        if self._append is not None:
            await self._append(type_, payload)

    @classmethod
    def fold(cls, crew_id: str, events, **limits) -> "Crew":
        """The crew as `crew:<crew_id>` says it was (the plan's
        "Durability"). Members keep their last status and report, the
        board its last writes, `seq` its high mark, and the root its last
        `await_agents` when it was still in it."""
        crew = cls(crew_id, **limits)
        for e in events:
            p = dict(e.payload or {})
            if e.type == topics.CREW_SPAWNED:
                ref = str(p.get("brief_ref") or "")
                crew.members[p["handle"]] = CrewMember(
                    handle=p["handle"], agent=str(p.get("agent") or ""), parent=str(p.get("parent") or ""),
                    depth=int(p.get("depth") or 1), budget=MemberBudget.from_dict(p.get("budget")),
                    report_policy=str(p.get("report_policy") or "end"),
                    isolation=str(p.get("isolation") or "fresh"), writer=bool(p.get("writer")),
                    via=str(p.get("via") or "spawn"), brief="" if p.get("brief_blob") else ref, brief_ref=ref,
                    brief_blob=bool(p.get("brief_blob")),
                    background=bool(p.get("background")), started_at=crew._now(),
                    requester=str(p.get("requester") or ""),
                    requester_channel=str(p.get("requester_channel") or ""),
                )
                if crew.bounded(crew.members[p["handle"]]) and crew.started is None:
                    # The wall-clock starts again from the restart: the
                    # process was down, and a member is not charged for that.
                    crew.started = crew._now()
                crew.inboxes.setdefault(p["handle"], Inbox())
            elif e.type == MEMBER_STATUS_CHANGED:
                handle = str(p.get("handle") or "")
                if handle in crew.members:
                    crew.members[handle].status = str(p.get("status") or "")
                elif handle == crew.root:
                    crew.root_await = _await_of(p) if p.get("status") == "waiting" else None
            elif e.type == topics.CREW_MESSAGE:
                crew.seq = max(crew.seq, int(p.get("seq") or 0))
                crew.refs.update(p.get("refs") or ())
                crew._track_question(p)
                sender = str(p.get("from") or "")
                if p.get("kind") in ("progress", "milestone") and sender in crew.members:
                    crew.members[sender].last_progress = str(p.get("body") or "")[:200]
            elif e.type == topics.CREW_REPORT:
                handle = str(p.get("handle") or "")
                report = Report.from_dict(p.get("report") or {})
                crew.refs.update(report.artifacts)
                if handle in crew.members:
                    member = crew.members[handle]
                    member.report = report
                    member.cost_usd = report.cost_usd
                    member.tokens = report.tokens
                    if crew.bounded(member):
                        crew.spent_usd += report.cost_usd
                        crew.spent_tokens += report.tokens
                    if not is_terminal(member.status):
                        # A filed report is the end, even when the process
                        # stopped before the status event that follows it:
                        # a restart must not run the member a second time.
                        member.status = _status_of(report, cancelled=bool(member.cancel_reason))
            elif e.type == topics.CREW_CANCEL:
                for member in ([crew.members[p["handle"]]] if p.get("handle") in crew.members else []) + (
                        crew.descendants(p.get("handle", "")) if p.get("cascade", True) else []):
                    if not is_terminal(member.status):
                        member.cancel_reason = str(p.get("reason") or "cancelled")
            elif e.type == BOARD:
                crew.board[str(p.get("key"))] = {"handle": p.get("handle"), "key": p.get("key"),
                                                 "value": p.get("value")}
        return crew


def _status_of(report: Report, *, cancelled: bool) -> str:
    """The member status a filed report leaves behind."""
    if cancelled and report.status != "ok":
        return "cancelled"
    return {"ok": "done", "partial": "done", "failed": "failed", "blocked": "blocked",
            "cancelled": "cancelled"}.get(report.status, "failed")


def _await_of(payload: dict) -> dict | None:
    try:
        data = json.loads(str(payload.get("reason") or ""))
    except ValueError:
        return None
    return data.get("await") if isinstance(data, dict) and isinstance(data.get("await"), dict) else None


# -- Report building ---------------------------------------------------------------------

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?P<claim>.+?)\s*$")
_REF_IN = re.compile(r"\[(?:ref|evidence)\s*:\s*(?P<ref>[^\]\s]+)\s*\]", re.IGNORECASE)
_FENCED = re.compile(r"```(?:json)?\s*\n(?P<body>\{.*?\})\s*\n```", re.DOTALL)


def parse_report_text(text: str) -> tuple[str, list[Finding], list[str]] | None:
    """`(summary, findings, artifacts)` from a member's final answer, or
    None when it has neither shape: a JSON object with a `summary`
    (bare or fenced), or the delegate brief's shape -- the answer, then
    the facts behind it as `- ` bullets."""
    text = (text or "").strip()
    if not text:
        return None
    candidate = text
    fenced = _FENCED.search(text)
    if fenced:
        candidate = fenced.group("body")
    if candidate.startswith("{"):
        try:
            data = json.loads(candidate)
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("summary"), str):
            findings = []
            for f in data.get("findings") or ():
                if isinstance(f, dict) and str(f.get("claim") or "").strip():
                    findings.append(Finding(str(f["claim"]).strip()[:CLAIM_MAX], str(f.get("evidence_ref") or "")))
                elif isinstance(f, str) and f.strip():
                    findings.append(Finding(f.strip()[:CLAIM_MAX]))
            artifacts = [str(a) for a in data.get("artifacts") or () if str(a).strip()]
            return data["summary"].strip(), findings, artifacts
    summary_lines, findings = [], []
    for line in text.splitlines():
        bullet = _BULLET.match(line)
        if bullet:
            claim = bullet.group("claim")
            ref = _REF_IN.search(claim)
            findings.append(Finding(_REF_IN.sub("", claim).strip()[:CLAIM_MAX], ref.group("ref") if ref else ""))
        elif line.strip() and not findings:
            summary_lines.append(line.strip())
    if not findings:
        return None
    return " ".join(summary_lines), findings, []


async def build_report(text: str, *, status: str, steps: int = 0, tokens: int = 0, cost_usd: float = 0.0,
                       wall_s: float = 0.0, questions_unanswered=(), put_blob=None) -> Report:
    """The typed `Report` for a member's final answer (the plan's "Report
    building"). A parsed answer keeps its summary and findings; one that
    does not parse is summarised by its first SUMMARY_MAX characters. Either
    way, a summary that had to be cut has the whole text behind a blob
    ref in `artifacts`, so nothing is lost and nothing long is inline."""
    text = (text or "").strip()
    parsed = parse_report_text(text)
    summary, findings, artifacts = parsed if parsed is not None else (text, [], [])
    findings = [f for f in findings if f.claim][:FINDINGS_MAX]
    overflow = parsed is None and len(text) > SUMMARY_MAX
    if len(summary) > SUMMARY_MAX or overflow or (parsed is not None and len(findings) < len(parsed[1])):
        if put_blob is not None:
            try:
                artifacts = [await put_blob(text.encode("utf-8"))] + list(artifacts)
            except Exception:  # noqa: BLE001 -- a lost blob must not lose the report
                pass
        summary = summary[:SUMMARY_MAX - 1] + "…" if len(summary) > SUMMARY_MAX else summary
    return Report(status=status, summary=summary, findings=tuple(findings), artifacts=tuple(artifacts),
                  steps=int(steps), tokens=int(tokens), cost_usd=round(float(cost_usd), 6),
                  wall_s=round(float(wall_s), 3), questions_unanswered=tuple(str(q) for q in questions_unanswered))


def render_report(member: CrewMember) -> str:
    """One member's report as the parent reads it: a conclusion and refs."""
    r = member.report
    if r is None:
        return f"{member.handle} ({member.agent}, {member.status}): no report yet" + (
            f"; last progress: {member.last_progress}" if member.last_progress else "")
    lines = [f"{member.handle} ({member.agent}) {r.status}, {r.steps} steps, ${r.cost_usd:.3f}: {r.summary}"]
    lines += [f"  - {f.claim}" + (f" [ref: {f.evidence_ref}]" if f.evidence_ref else "") for f in r.findings]
    if r.artifacts:
        lines.append(f"  artifacts (read_ref): {', '.join(r.artifacts)}")
    if r.questions_unanswered:
        lines.append(f"  went ahead without an answer to: {'; '.join(r.questions_unanswered)}")
    return "\n".join(lines)


def status_table(members: list[CrewMember]) -> str:
    if not members:
        return "no crew members"
    rows = ["handle | agent | status | last progress | steps | cost"]
    for m in members:
        steps = m.report.steps if m.report else m.steps
        cost = m.report.cost_usd if m.report else m.cost_usd
        rows.append(f"{m.handle} | {m.agent} | {m.status} | {(m.last_progress or '-')[:80]} | {steps} | ${cost:.3f}")
    return "\n".join(rows)


__all__ = [
    "BRIEF_INLINE_MAX", "CREW_BUDGET", "Crew", "CrewMember", "CrewRefused", "Inbox", "build_report",
    "parse_report_text", "render_inbox", "render_report", "status_table",
]
