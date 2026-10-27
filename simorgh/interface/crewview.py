"""Crews, visible (stage 18 item 5).

A crew is the tree of agents under one root session (the plan's
Definitions, docs/plan/stage-18-agent-crews.md). Orchestration runs it;
this module only folds what it says about it -- the four `crew.*` topics
on the bus, or the same events on the `crew:<crew_id>` ledger stream --
into something a person can read, and draws that in the transcript's own
⏺/⎿ shape (`panel.py`).

One fold, three surfaces: the TUI (live, from the bus), the `crew`
console command and the dashboard's crew panel (both from the ledger).
Pure: nothing here touches a terminal, the bus or the ledger, so all of
it is testable without them.

The fold is generous on purpose. Member status is not a field of any one
topic; it follows from them: spawned is `starting`, anything the member
says is `running`, a question is `waiting`, an answer to it is `running`
again, the report's own status ends it, and a cancel ends it and, when it
cascades, every member under it. An event of a type this module does not
know is skipped rather than refused: the stream is append-only and a
newer writer may add kinds (`board`, for one) before this reader learns
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The four topics, by value. Written out rather than imported so this
#: pure module can fold a ledger stream in a process whose contracts do
#: not know the topics yet; `service.py` subscribes by the constants.
SPAWNED = "crew.spawned"
MESSAGE = "crew.message"
REPORT = "crew.report"
CANCEL = "crew.cancel"
TOPICS: tuple[str, ...] = (SPAWNED, MESSAGE, REPORT, CANCEL)

#: Where a crew is recorded (the plan's Definitions).
STREAM_PREFIX = "crew:"

#: Member statuses, from the plan's Definitions.
STATUSES: tuple[str, ...] = ("starting", "running", "waiting", "done", "failed", "blocked", "cancelled")
FINISHED: frozenset[str] = frozenset({"done", "failed", "blocked", "cancelled"})

#: A report's status -> the member's.
_REPORT_STATUS = {"ok": "done", "partial": "done", "failed": "failed", "blocked": "blocked",
                  "cancelled": "cancelled"}

#: Kept per crew for `crew <id>`; the ledger is the history.
MAX_MESSAGES = 200
#: Crews held in a live book before the oldest is dropped.
MAX_CREWS = 50
#: Members drawn under a running task in the live rows above the prompt.
MAX_LIVE_MEMBERS = 6

_MARK = {"starting": "○", "running": "…", "waiting": "?", "done": "✓", "failed": "✗",
         "blocked": "⏸", "cancelled": "⊘"}
_MARK_ASCII = {"starting": ".", "running": "..", "waiting": "?", "done": "ok", "failed": "FAILED",
               "blocked": "blocked", "cancelled": "cancelled"}
_AGENT_ICON = {"research": "🔍", "browser": "🌐", "patch": "🔧", "plan": "🗂", "chat": "💬",
               "voice_chat": "🔊", "verify": "🔎", "skill": "🎓"}


@dataclass
class Member:
    handle: str
    agent: str = "?"
    parent: str = ""
    depth: int = 1
    status: str = "starting"
    brief: str = ""
    brief_ref: str = ""
    report_policy: str = "end"
    budget: dict = field(default_factory=dict)
    #: The last thing it said, one line: progress, a milestone, a question.
    last: str = ""
    last_kind: str = ""
    steps: int = 0
    cost_usd: float = 0.0
    report: dict | None = None

    def topic(self) -> str:
        return " ".join((self.brief or "").split()) or self.brief_ref or "(no brief)"


@dataclass
class Crew:
    crew_id: str
    members: dict[str, Member] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    started_at: float | None = None
    updated_at: float | None = None

    # ------------------------------------------------------------ queries
    def children(self, parent: str) -> list[Member]:
        return [self.members[h] for h in self.order if self.members[h].parent == parent]

    def roots(self) -> list[Member]:
        """Members whose parent is not itself a member: the root session's
        own children (their parent is the crew's root, which is not a
        member), and any orphan whose parent was never seen."""
        return [self.members[h] for h in self.order if self.members[h].parent not in self.members]

    def walk(self) -> list[tuple[Member, int]]:
        """Every member with its depth in this tree, parents first."""
        out: list[tuple[Member, int]] = []
        seen: set[str] = set()

        def visit(member: Member, depth: int) -> None:
            if member.handle in seen:
                return
            seen.add(member.handle)
            out.append((member, depth))
            for child in self.children(member.handle):
                visit(child, depth + 1)

        for root in self.roots():
            visit(root, 1)
        return out

    def descendants(self, handle: str) -> list[str]:
        out: list[str] = []
        stack = [handle]
        while stack:
            current = stack.pop()
            for child in self.children(current):
                if child.handle not in out:
                    out.append(child.handle)
                    stack.append(child.handle)
        return out

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for member in self.members.values():
            out[member.status] = out.get(member.status, 0) + 1
        return out

    def cost_usd(self) -> float:
        return sum(m.cost_usd for m in self.members.values())

    def active(self) -> bool:
        return any(m.status not in FINISHED for m in self.members.values())

    def summary(self) -> dict:
        return {"crew_id": self.crew_id, "members": len(self.members), "counts": self.counts(),
                "cost_usd": round(self.cost_usd(), 6), "active": self.active(),
                "started_at": self.started_at, "updated_at": self.updated_at}

    def to_dict(self, *, messages: int = 50) -> dict:
        """For the dashboard: the tree in walk order, and the newest messages."""
        return {**self.summary(),
                "tree": [{"handle": m.handle, "agent": m.agent, "parent": m.parent, "depth": depth,
                          "status": m.status, "topic": m.topic(), "last": m.last, "last_kind": m.last_kind,
                          "steps": m.steps, "cost_usd": round(m.cost_usd, 6),
                          "report_policy": m.report_policy,
                          "summary": str((m.report or {}).get("summary") or "")}
                         for m, depth in self.walk()],
                "messages": self.messages[-messages:] if messages else []}

    # ------------------------------------------------------------ folding
    def _member(self, handle: str) -> Member:
        member = self.members.get(handle)
        if member is None:
            member = Member(handle=handle)
            self.members[handle] = member
            self.order.append(handle)
        return member

    def apply(self, type_: str, payload: dict, *, ts: float | None = None) -> Member | None:
        """Fold one event. Returns the member it changed, or None."""
        if ts is not None:
            self.started_at = ts if self.started_at is None else min(self.started_at, ts)
            self.updated_at = ts if self.updated_at is None else max(self.updated_at, ts)
        p = payload or {}
        if type_ == SPAWNED:
            handle = str(p.get("handle") or "")
            if not handle:
                return None
            member = self._member(handle)
            member.agent = str(p.get("agent") or member.agent)
            member.parent = str(p.get("parent") or "")
            parent = self.members.get(member.parent)
            member.depth = int(p.get("depth") or ((parent.depth + 1) if parent else 1))
            member.brief = str(p.get("brief") or member.brief)
            member.brief_ref = str(p.get("brief_ref") or member.brief_ref)
            member.report_policy = str(p.get("report_policy") or member.report_policy)
            member.budget = dict(p.get("budget") or {})
            if member.status not in FINISHED:
                member.status = "starting"
            return member
        if type_ == MESSAGE:
            text = message_text(p.get("body"))
            entry = {"seq": p.get("seq"), "from": str(p.get("from") or ""), "to": str(p.get("to") or ""),
                     "kind": str(p.get("kind") or ""), "text": text, "ts": ts}
            self.messages.append(entry)
            del self.messages[:-MAX_MESSAGES]
            sender = self.members.get(entry["from"])
            receiver = self.members.get(entry["to"])
            kind = entry["kind"]
            if sender is not None and kind in ("progress", "milestone", "question", "report", "note"):
                if sender.status not in FINISHED:
                    sender.status = "waiting" if kind == "question" else "running"
                sender.last, sender.last_kind = " ".join(text.split()), kind
                return sender
            if receiver is not None and kind == "answer":
                # The question it was waiting on is settled; the screen
                # should not go on saying it asks.
                if receiver.status == "waiting":
                    receiver.status = "running"
                receiver.last, receiver.last_kind = " ".join(text.split()), "answer"
                return receiver
            return sender or receiver
        if type_ == REPORT:
            handle = str(p.get("handle") or "")
            if not handle:
                return None
            member = self._member(handle)
            report = p.get("report") if isinstance(p.get("report"), dict) else {}
            member.report = report
            member.status = _REPORT_STATUS.get(str(report.get("status") or "ok"), "done")
            try:
                member.steps = max(member.steps, int(report.get("steps") or 0))
                member.cost_usd = max(member.cost_usd, float(report.get("cost_usd") or 0.0))
            except (TypeError, ValueError):
                pass
            summary = " ".join(str(report.get("summary") or "").split())
            if summary:
                member.last, member.last_kind = summary, "report"
            return member
        if type_ == CANCEL:
            handle = str(p.get("handle") or "")
            member = self.members.get(handle)
            if member is None:
                return None
            targets = [handle] + (self.descendants(handle) if p.get("cascade", True) else [])
            for target in targets:
                if self.members[target].status not in FINISHED:
                    self.members[target].status = "cancelled"
            reason = " ".join(str(p.get("reason") or "").split())
            if reason:
                member.last, member.last_kind = f"cancelled: {reason}", "cancel"
            return member
        # A status change written straight to the stream, if a writer adds one.
        handle = str(p.get("handle") or "")
        status = str(p.get("status") or "")
        if handle in self.members and status in STATUSES:
            self.members[handle].status = status
            return self.members[handle]
        return None

    def on_step(self, handle: str, payload: dict) -> Member | None:
        """A member's own `task.step` (its handle is its task id): the
        steps and cost the tree shows while it is still running."""
        member = self.members.get(handle)
        if member is None or payload.get("ok") is None:
            return None
        member.steps += 1
        try:
            member.cost_usd += float(payload.get("cost_usd") or 0.0)
        except (TypeError, ValueError):
            pass
        if member.status == "starting":
            member.status = "running"
        return member


def message_text(body) -> str:
    """A `crew.message` body as one line of text: a string as it is, an
    A2A-shaped `{parts: [{kind: text, text}]}` by its text parts, a dict
    with `text`, else its keys. Never the whole structure: messages
    carry conclusions and refs, and so does the screen."""
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        if isinstance(body.get("text"), str):
            return body["text"]
        parts = body.get("parts")
        if isinstance(parts, list):
            texts = [str(part.get("text") or "") for part in parts
                     if isinstance(part, dict) and part.get("kind", "text") == "text" and part.get("text")]
            if texts:
                return " ".join(texts)
        return ", ".join(f"{k}" for k in list(body)[:6])
    if isinstance(body, list):
        return " ".join(message_text(item) for item in body)
    return str(body)


def crew_id_of_stream(stream: str) -> str:
    return stream[len(STREAM_PREFIX):] if stream.startswith(STREAM_PREFIX) else stream


def fold(crew_id: str, events) -> Crew:
    """A crew from its ledger stream: anything with `.type`, `.payload`
    and optionally `.ts`, oldest first."""
    crew = Crew(crew_id=crew_id)
    for event in events:
        crew.apply(getattr(event, "type", ""), getattr(event, "payload", {}) or {}, ts=getattr(event, "ts", None))
    return crew


@dataclass
class CrewBook:
    """Every crew this session has seen go past on the bus."""

    crews: dict[str, Crew] = field(default_factory=dict)
    #: handle -> crew_id, for joining a member's own `task.step`.
    _member_of: dict[str, str] = field(default_factory=dict)

    def on_event(self, type_: str, payload: dict, *, ts: float | None = None) -> tuple[Crew, Member | None] | None:
        crew_id = str((payload or {}).get("crew_id") or "")
        if not crew_id:
            return None
        crew = self.crews.get(crew_id)
        if crew is None:
            crew = self.crews[crew_id] = Crew(crew_id=crew_id)
            while len(self.crews) > MAX_CREWS:
                dropped = self.crews.pop(next(iter(self.crews)))
                for handle in dropped.members:
                    self._member_of.pop(handle, None)
        member = crew.apply(type_, payload, ts=ts)
        if member is not None:
            self._member_of[member.handle] = crew_id
        return crew, member

    def on_step(self, task_id: str, payload: dict) -> tuple[Crew, Member] | None:
        crew_id = self._member_of.get(task_id)
        crew = self.crews.get(crew_id or "")
        if crew is None:
            return None
        member = crew.on_step(task_id, payload)
        return (crew, member) if member is not None else None

    def is_member(self, task_id: str) -> bool:
        return task_id in self._member_of

    def crew_of(self, task_id: str) -> Crew | None:
        """The crew `task_id` is the root of, or a member of."""
        if task_id in self.crews:
            return self.crews[task_id]
        return self.crews.get(self._member_of.get(task_id, ""))

    def find_handle(self, handle: str) -> Crew | None:
        crew = self.crews.get(self._member_of.get(handle, ""))
        if crew is not None:
            return crew
        # A prefix, as the screen shows them.
        hits = [c for c in self.crews.values() for h in c.members if h.startswith(handle)]
        return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------ drawing
def _took_cost(member: Member) -> str:
    parts = [member.status]
    if member.steps:
        parts.append(f"{member.steps} step{'s' if member.steps != 1 else ''}")
    if member.cost_usd:
        parts.append(f"${member.cost_usd:.2f}" if member.cost_usd >= 0.01 else f"${member.cost_usd:.3f}")
    return " · ".join(parts)


def member_line(member: Member, *, depth: int = 1, unicode: bool = True) -> str:
    """One member, as a branch of its parent's tree:
    `  ⏺ 🔍 research · price of dishwasher A   ✓ done · 4 steps · $0.01  [h1abc123]`.
    Fitted to the real terminal in display columns, the topic giving way first."""
    from .render import display_width, fit, terminal_width

    indent = "  " * max(1, depth)
    head = "⏺ " if unicode else "* "
    icon = (_AGENT_ICON.get(member.agent, "•") + " ") if unicode else ""
    mark = (_MARK if unicode else _MARK_ASCII).get(member.status, "")
    tail = f"{mark} {_took_cost(member)}  [{member.handle[:8]}]"
    lead = f"{indent}{head}{icon}{member.agent} · "
    width = terminal_width()
    room = width - display_width(lead) - display_width(tail) - 2
    topic = fit(" ".join(member.topic().split()), max(8, room))
    pad = max(2, width - display_width(lead) - display_width(topic) - display_width(tail))
    return fit(f"{lead}{topic}{' ' * pad}{tail}", width)


def member_note(member: Member, *, depth: int = 1, unicode: bool = True, text: str | None = None) -> str:
    """What hangs under a member: its last word, behind a `⎿`."""
    from .render import fit, terminal_width

    said = " ".join((member.last if text is None else text).split())
    if not said:
        return ""
    kind = member.last_kind if text is None else ""
    label = {"question": "asks: ", "milestone": "milestone: ", "answer": "told: "}.get(kind, "")
    corner = "⎿  " if unicode else "`- "
    return fit(f"{'  ' * max(1, depth)}  {corner}{label}{said}", terminal_width())


def crew_head(crew: Crew, *, unicode: bool = True) -> str:
    """The root line of a crew's own tree, for `crew <id>`."""
    from .render import fit, terminal_width

    counts = crew.counts()
    parts = [f"{len(crew.members)} member{'s' if len(crew.members) != 1 else ''}"]
    for status in STATUSES:
        if counts.get(status):
            parts.append(f"{counts[status]} {status}")
    cost = crew.cost_usd()
    if cost:
        parts.append(f"${cost:.2f}")
    head = "⏺" if unicode else "*"
    return fit(f"{head} crew {crew.crew_id[:12]} · {' · '.join(parts)}", terminal_width())


def crew_tree(crew: Crew, *, unicode: bool = True, notes: bool = True) -> list[str]:
    """The whole crew: its head, every member under its parent, and each
    member's last word hanging from it."""
    lines = [crew_head(crew, unicode=unicode)]
    for member, depth in crew.walk():
        lines.append(member_line(member, depth=depth, unicode=unicode))
        if notes:
            note = member_note(member, depth=depth, unicode=unicode)
            if note:
                lines.append(note)
    return lines


def message_lines(crew: Crew, *, limit: int = 20, unicode: bool = True) -> list[str]:
    """The newest messages, one line each: `from → to  kind  text`."""
    from .render import fit, terminal_width

    arrow = "→" if unicode else "->"
    out = []
    for entry in crew.messages[-limit:]:
        source = (entry.get("from") or "?")[:8]
        target = (entry.get("to") or "?")[:8]
        out.append(fit(f"  {source} {arrow} {target}  {entry.get('kind') or '?':<9} "
                       f"{' '.join(str(entry.get('text') or '').split())}", terminal_width()))
    return out


def crew_list(crews: list[Crew], *, unicode: bool = True) -> list[str]:
    """One line per crew, newest first."""
    return [crew_head(crew, unicode=unicode) for crew in crews]


def live_member_rows(crew: Crew, *, unicode: bool = True, limit: int = MAX_LIVE_MEMBERS) -> list[list[tuple[str, str]]]:
    """A running task's crew, for the live rows above the prompt:
    one row per member under the task's own row. Finished members drop
    out, so the block shrinks as the crew lands."""
    rows: list[list[tuple[str, str]]] = []
    live = [(m, d) for m, d in crew.walk() if m.status not in FINISHED]
    for member, depth in live[:limit]:
        rows.append([("class:sim.footer", member_line(member, depth=depth, unicode=unicode))])
    if len(live) > limit:
        rows.append([("class:sim.footer", f"  … and {len(live) - limit} more in the crew")])
    return rows


__all__ = [
    "CANCEL", "Crew", "CrewBook", "FINISHED", "MESSAGE", "MAX_LIVE_MEMBERS", "Member", "REPORT", "SPAWNED",
    "STATUSES", "STREAM_PREFIX", "TOPICS", "crew_head", "crew_id_of_stream", "crew_list", "crew_tree",
    "fold", "live_member_rows", "member_line", "member_note", "message_lines", "message_text",
]
