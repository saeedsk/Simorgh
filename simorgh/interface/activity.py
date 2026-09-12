"""What Sim is doing, right now, in front of you.

The creator, 2026-09-07, after a day of finding serious bugs by reading
raw ledger files: "these thing were happening behind the scene and I was
not aware of them, i want full visibility ... these thing should tell me
what they are doing, what is in queue and what is the topic of research
or skill."

They could not see it because the narration in `service.py` deliberately
filters to tasks *this REPL is waiting on* -- a chat turn, or something
`improve`/`plan`/`research` just fired off -- and stays silent for
everything else. Every autonomous task, which is nearly all of them, ran
invisibly. That was the right call when the alternative was an
unstructured wall of text. It is the wrong call as the only option.

This module keeps the small amount of state that makes the difference
between a line that says something and a line that does not: what each
task actually *is*. `task.started` carries an id and a worker; the topic
lives in `task.created`, which nobody was holding on to. So a start could
only ever print an id.

Two surfaces, from one book:

- **The feed**: a line when work starts, one per step, one when it ends.
  Origin, kind, and the actual topic, so "research" is never just
  "research".
- **The footer**: one live line under the prompt -- what is running, for
  how long, and how much is waiting behind it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Kept small on purpose: this is a live view, not a history. The Ledger
# is the history.
_MAX_TRACKED = 500
# Room the fixed parts of a line need, so the topic gets the rest.
# `topic_width` is a function of the real terminal (`render.terminal_width`)
# rather than a constant for an 80-column screen.
_LINE_OVERHEAD = 34
_MIN_TOPIC = 24


def topic_width(overhead: int = _LINE_OVERHEAD) -> int:
    """Columns a line's variable part may use on this terminal."""
    from .render import terminal_width

    return max(_MIN_TOPIC, terminal_width() - overhead)


@dataclass
class TaskRecord:
    task_id: str
    kind: str = "?"
    origin: str = "?"
    description: str = ""
    subject: str | None = None
    status: str = "created"
    started_at: float | None = None
    steps: int = 0
    # What the task is doing *right now*, for the bottom panel: the
    # phase of the step in flight and the verb for it ("Reading",
    # "Patching"; a gather phase breathes a word instead -- `panel.py`).
    phase: str = ""
    verb: str = ""
    # The call in flight, for the live block above the prompt: its tool
    # and what it is on ("run_shell", "python -m pytest tests/…").
    tool: str = ""
    detail: str = ""
    inflight_since: float | None = None
    # When the last event for this task landed, so a finished step can
    # say how long it took: the step record itself carries no timing.
    last_event_at: float | None = None

    @property
    def topic(self) -> str:
        """What this task is *about*, in one line. The subject leads when
        there is one -- `research src/memory/__init__.py` says more than
        the first few words of the question do."""
        text = " ".join((self.description or "").split())
        if self.subject and self.subject not in text:
            text = f"{self.subject} -- {text}" if text else self.subject
        return text or "(no description)"

    def short_topic(self, width: int | None = None) -> str:
        width = topic_width() if width is None else width
        text = self.topic
        return text if len(text) <= width else text[: width - 1] + "…"


@dataclass
class TaskBook:
    """Every task Sim knows about this session, and what it is doing."""

    tasks: dict[str, TaskRecord] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)

    def on_created(self, payload: dict) -> TaskRecord:
        task_id = payload.get("task_id", "")
        record = TaskRecord(
            task_id=task_id,
            kind=payload.get("kind", "?"),
            origin=payload.get("origin", "?"),
            description=payload.get("description", ""),
            subject=payload.get("subject"),
        )
        self.tasks[task_id] = record
        self._order.append(task_id)
        self._trim()
        return record

    def seed(self, tasks: list[dict]) -> int:
        """Adopt the tasks that already existed before this session.

        Without this the book only knows tasks it watched being created,
        which on a restart is none of them -- so the first thing the
        creator saw was a feed of `? · ? · (no description)` for a
        hundred real tasks whose topics were sitting in Planning the
        whole time. Live-caught the first time the feed was run against
        the real ledger, 2026-09-07.
        """
        adopted = 0
        for payload in tasks:
            task_id = payload.get("task_id")
            if not task_id or task_id in self.tasks:
                continue
            record = self.on_created(payload)
            record.status = payload.get("status", "created")
            adopted += 1
        return adopted

    def get(self, task_id: str) -> TaskRecord:
        """Never `None`: a task this session did not see created (one
        carried over from a previous run) still gets a row, so the feed
        degrades to "an id and what it is doing" rather than silence."""
        record = self.tasks.get(task_id)
        if record is None:
            record = TaskRecord(task_id=task_id)
            self.tasks[task_id] = record
            self._order.append(task_id)
            self._trim()
        return record

    def on_started(self, task_id: str, *, now: float) -> TaskRecord:
        record = self.get(task_id)
        record.status = "running"
        record.started_at = now
        record.last_event_at = now
        return record

    def on_step(self, task_id: str, *, now: float | None = None, phase: str = "", verb: str = "",
                in_flight: bool = False, tool: str = "", detail: str = "") -> TaskRecord:
        """A step event. An in-flight one (no outcome yet) only updates
        what the task is doing; a finished one counts."""
        record = self.get(task_id)
        if in_flight:
            record.phase, record.verb = phase, verb
            record.tool, record.detail = tool or "", " ".join((detail or "").split())
            record.inflight_since = now
            return record
        record.steps += 1
        record.phase, record.verb = "", ""
        record.tool, record.detail, record.inflight_since = "", "", None
        if now is not None:
            record.last_event_at = now
        return record

    def step_took(self, task_id: str, *, now: float) -> float | None:
        record = self.tasks.get(task_id)
        if record is None or record.last_event_at is None:
            return None
        return max(0.0, now - record.last_event_at)

    def on_finished(self, task_id: str, status: str) -> TaskRecord:
        record = self.get(task_id)
        record.status = status
        return record

    def running(self) -> list[TaskRecord]:
        return [t for t in self.tasks.values() if t.status == "running"]

    def queued(self) -> list[TaskRecord]:
        return [t for t in self.tasks.values() if t.status in ("created", "available")]

    def _trim(self) -> None:
        while len(self._order) > _MAX_TRACKED:
            self.tasks.pop(self._order.pop(0), None)


# -- rendering ---------------------------------------------------------------
_KIND_ICON = {
    "research": "🔍", "patch": "🔧", "skill": "🎓", "project": "🗂", "chat": "💬",
}
_END_ICON = {"completed": "✅", "failed": "❌", "blocked": "⏸", "paused": "⏸"}


def _fit_line(line: str, width: int | None = None) -> str:
    """Cut a whole rendered line to the terminal, measured in display
    columns. Guessing each line's fixed overhead was wrong at every
    width (observer, 2026-09-08); measuring the finished line is not."""
    from .render import fit, terminal_width

    return fit(line, terminal_width() if width is None else width)


def started_line(record: TaskRecord, *, unicode: bool = True) -> str:
    """The line that was missing entirely: work beginning, and what it is.

    `origin` is on it because "Sim decided to do this" and "you asked for
    this" are different events and were indistinguishable before.
    """
    icon = (_KIND_ICON.get(record.kind, "•") + " ") if unicode else ""
    return _fit_line(f"{icon}{record.kind} · {record.origin} · {record.short_topic()}  [{record.task_id[:8]}]")


def step_line(record: TaskRecord, *, tool: str | None, summary: str, ok: bool | None,
              unicode: bool = True) -> str:
    mark = "  " + ("→" if unicode else "-")
    outcome = "" if ok is None else ("  ok" if ok else "  failed")
    what = f"{tool}: {summary}" if tool else summary
    what = " ".join(what.split())
    width = topic_width(overhead=len(mark) + len(outcome) + 2)
    if len(what) > width:
        what = what[: width - 1] + "…"
    return _fit_line(f"{mark} {what}{outcome}")


def finished_line(record: TaskRecord, *, elapsed: float | None, detail: str = "",
                  unicode: bool = True) -> str:
    icon = (_END_ICON.get(record.status, "•") + " ") if unicode else ""
    took = f" in {elapsed:.0f}s" if elapsed is not None else ""
    # The outcome carries two variable pieces -- the topic and the
    # result -- so they share what the terminal has rather than each
    # taking a full line's worth and overrunning together.
    head = f"{icon}{record.status}{took}: "
    room = max(_MIN_TOPIC, topic_width(overhead=len(head) + 12))
    share = room // 2 if detail else room
    line = f"{head}{record.short_topic(share)}  [{record.task_id[:8]}]"
    if detail:
        line += f" -- {' '.join(detail.split())[:room - share]}"
    return _fit_line(line)


def footer(book: TaskBook, *, now: float, extra: str = "") -> str:
    """One live line under the prompt: what is running, and what waits.

    Answers "what is in queue" without anyone having to type `tasks`.
    """
    running = book.running()
    queued = len(book.queued())
    if not running:
        base = f"idle · {queued} queued" if queued else "idle"
        return f"{base}  {extra}".rstrip()
    first = running[0]
    elapsed = now - first.started_at if first.started_at else 0.0
    more = f" (+{len(running) - 1} more)" if len(running) > 1 else ""
    parts = [f"{first.kind} · {first.short_topic(topic_width(overhead=46))} · {elapsed:.0f}s{more}"]
    if queued:
        parts.append(f"{queued} queued")
    if extra:
        parts.append(extra)
    return _fit_line("  ·  ".join(parts))


__all__ = [
    "TaskBook", "TaskRecord", "finished_line", "footer", "started_line", "step_line",
]
