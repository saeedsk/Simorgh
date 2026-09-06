"""Checklist generation and per-item evaluation (docs/blueprint/subsystems/
10-verification.md section 5.1, "semantic review"). The review never sees
the generator's own conversation -- only the task description, the
reported result, and evidence -- so it isn't the same context
rationalizing its own prior output (harness-04, "Verification as a
separate, independently-prompted pass"). `verify_task_completion`'s v1
shape (one implicit item, "does this genuinely address the task") is the
degenerate case of this with `max_items=1` -- see the module docstring
in `service.py` for the compatibility note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .api import CheckContext, ThinkReply, VerifyRequest
from .parsing import parse_verdict

_ITEM_LINE = re.compile(r"^\s*\d+[.):]\s*(?:\[(required|optional)\]\s*)?(.+)$")

_CHECKLIST_PROMPT = """A change was made to address this task:

Task: {description}

Result reported by the pipeline that made it:
{result}

Write up to {max_items} short, specific, binary (yes/no-answerable)
questions that would each catch a real gap if the change missed the
point -- not vague ("is this good?") but concrete ("does the new code
handle the empty-list case the task described?"). Mark each question
[required] (a "no" means the change fails) or [optional] (a "no" is
useful feedback but not disqualifying).

Respond with ONLY a numbered list, one question per line:
1. [required] <question>
2. [optional] <question>
..."""

_ANSWER_PROMPT = """Task: {description}

Result reported by the pipeline that made it:
{result}

Question: {question}

Does the result satisfy this? Answer with exactly one word first -- YES
or NO -- then, on a new line, one short sentence of evidence."""


@dataclass(frozen=True)
class ChecklistItem:
    question: str
    required: bool


@dataclass(frozen=True)
class AnsweredItem:
    question: str
    required: bool
    answer: str | None  # "yes" | "no" | None (no verdict stated)
    evidence: str


async def generate_checklist(think, req: VerifyRequest, config, max_items: int | None = None) -> list[ChecklistItem]:
    max_items = max_items or config.checklist_max_items
    if req.checklist_hint:
        return [ChecklistItem(question=req.checklist_hint, required=True)]
    reply: ThinkReply = await think(
        purpose="review",
        prompt=_CHECKLIST_PROMPT.format(
            description=req.subject.get("description", ""), result=req.subject.get("result", ""), max_items=max_items
        ),
    )
    if reply.floor or not reply.ok or not reply.text.strip():
        return []
    items: list[ChecklistItem] = []
    for line in reply.text.splitlines():
        match = _ITEM_LINE.match(line)
        if not match:
            continue
        required = match.group(1) != "optional"
        items.append(ChecklistItem(question=match.group(2).strip(), required=required))
        if len(items) >= max_items:
            break
    return items


async def evaluate_checklist(think, req: VerifyRequest, items: list[ChecklistItem]) -> list[AnsweredItem]:
    answered: list[AnsweredItem] = []
    for item in items:
        reply: ThinkReply = await think(
            purpose="review",
            prompt=_ANSWER_PROMPT.format(
                description=req.subject.get("description", ""), result=req.subject.get("result", ""), question=item.question
            ),
        )
        answer = None if (reply.floor or not reply.ok) else parse_verdict(reply.text)
        answered.append(AnsweredItem(question=item.question, required=item.required, answer=answer, evidence=reply.text.strip()))
    return answered
