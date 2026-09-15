"""The progress note: a task session's working memory between re-grounds.

A long session used to carry every tool call and result it ever made in
`session.messages`, and nothing removed them (orchestration README, "not
built: reground-every-N-steps"). Every few steps the model now writes a
short note -- the goal, what is done, what it learned, what comes next --
and the transcript is replaced by that note plus the last few steps.
The record of what happened stays on the task's ledger stream; the
model's context holds only what it needs to continue.
(docs/plans/long-run-context-design.md section 3.)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

NOTE_HEADER = "Progress note -- your own summary of the work so far. Continue from it; the steps it summarises are no longer shown."
_LIST_ITEMS = 12
_ITEM_CHARS = 300
_GOAL_CHARS = 600
_MESSAGE_CHARS = 1200
_TRANSCRIPT_CHARS = 14_000


@dataclass
class ProgressNote:
    goal: str = ""
    done: list[str] = field(default_factory=list)
    learned: list[str] = field(default_factory=list)
    next: str = ""
    open_questions: list[str] = field(default_factory=list)

    def render(self) -> str:
        def items(title: str, values: list[str]) -> str:
            return f"{title}:\n" + ("\n".join(f"- {v}" for v in values) if values else "- (none yet)")
        parts = [f"Goal: {self.goal}", items("Done", self.done), items("Learned", self.learned),
                 f"Next: {self.next or '(decide from the goal)'}"]
        if self.open_questions:
            parts.append(items("Open questions", self.open_questions))
        return "\n".join(parts)


def _clip(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _clip_list(values) -> list[str]:
    if isinstance(values, str):
        values = [values]
    out = [_clip(v, _ITEM_CHARS) for v in (values or []) if str(v or "").strip()]
    return out[-_LIST_ITEMS:]


def parse_note(text: str) -> ProgressNote | None:
    """The note from a model reply: a JSON object, possibly fenced or with
    prose around it. None when there is no usable note -- a note with no
    goal is not a note."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or not str(data.get("goal") or "").strip():
        return None
    return ProgressNote(
        goal=_clip(data.get("goal"), _GOAL_CHARS),
        done=_clip_list(data.get("done")),
        learned=_clip_list(data.get("learned")),
        next=_clip(data.get("next"), _ITEM_CHARS),
        open_questions=_clip_list(data.get("open_questions")),
    )


def render_transcript(messages: list[dict]) -> str:
    """The messages since the last re-ground, as plain lines for the
    note-writer: each clipped, the newest kept when over the cap."""
    lines = [f"[{m.get('role', '?')}] {_clip(m.get('content', ''), _MESSAGE_CHARS)}" for m in messages]
    text = "\n".join(lines)
    return text if len(text) <= _TRANSCRIPT_CHARS else "(older steps cut)\n" + text[-_TRANSCRIPT_CHARS:]


def reground_prompt(task: str, previous: str, messages: list[dict], *, steps_left: int) -> str:
    return (
        "You are pausing a long task to write your progress note. The raw steps below will be replaced by "
        "this note, so keep every fact you still need: paths, commands that worked or failed, numbers, "
        "decisions, and what is left to do.\n\n"
        f"The task:\n{task}\n\n"
        f"Your previous note:\n{previous or '(none -- this is the first)'}\n\n"
        f"Steps since then:\n{render_transcript(messages)}\n\n"
        f"Steps left in this attempt: {steps_left}.\n\n"
        "Reply with ONLY a JSON object, no prose, with these keys: "
        '"goal" (the task in one or two sentences), "done" (list of facts established and edits made), '
        '"learned" (list: what turned out true or false, dead ends to avoid), "next" (the immediate next '
        'action), "open_questions" (list, may be empty). At most 12 short items per list.'
    )


def compacted(messages: list[dict], note: ProgressNote, *, keep_recent_steps: int) -> list[dict]:
    """The transcript after a re-ground: the note, then the last few step
    exchanges, starting at an assistant turn so roles still alternate."""
    tail = messages[-(2 * max(0, keep_recent_steps)):] if keep_recent_steps > 0 else []
    while tail and tail[0].get("role") != "assistant":
        tail = tail[1:]
    return [{"role": "user", "content": f"{NOTE_HEADER}\n\n{note.render()}"}] + list(tail)


def due(steps_used: int, reground_at: int, every: int) -> bool:
    return every > 0 and steps_used - reground_at >= every


__all__ = ["NOTE_HEADER", "ProgressNote", "compacted", "due", "parse_note", "reground_prompt", "render_transcript"]
