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
{evidence}
Write up to {max_items} short, specific, binary (yes/no-answerable)
questions that would each catch a real gap if the change missed the
point -- not vague ("is this good?") but concrete ("does the new code
handle the empty-list case the task described?"). Ask only about what
the task itself asked for, and only what the evidence above can answer.
Work the task did not ask for -- tests, documentation, extra handling --
may be [optional], never [required]. Mark each question [required] (a
"no" means the change fails) or [optional] (a "no" is useful feedback
but not disqualifying).

Respond with ONLY a numbered list, one question per line:
1. [required] <question>
2. [optional] <question>
..."""

# A research task produces an ANSWER, not a change, and asking about it
# in the language of a change breaks it. The generator, told "a change
# was made", naturally writes questions like "does any file use r\"\"\" as
# its first-line docstring?" -- whose correct answer, and the entire
# point of the task, is "no". `verdict.combine` then fails on any
# required "no", RESEARCH has `max_revisions=0` so there is no second
# chance, and `decomposer.py` makes the research step a dependency of
# every patch step in a project. One inverted question therefore left
# three sibling tasks pending forever with no error anywhere, and the
# project died at step one (observer, 2026-09-08).
_RESEARCH_CHECKLIST_PROMPT = """A question was investigated and answered:

Question: {description}

The answer given:
{result}
{evidence}
Write up to {max_items} short, specific, binary (yes/no-answerable)
questions that would each catch a real failure of this ANSWER -- that it
does not address the question asked, that it states something the
evidence above contradicts, or that it claims a finding no step
supports.

Do not ask whether the codebase has some property: a finding of "no
such thing exists" is a perfectly good answer to a research question,
and a question whose honest answer is "no" would fail the task for
being right. Ask about the answer, never about the world it describes.

Mark each question [required] (a "no" means the answer fails) or
[optional] (a "no" is useful feedback but not disqualifying).

Respond with ONLY a numbered list, one question per line:
1. [required] <question>
2. [optional] <question>
..."""


_ANSWER_PROMPT = """Task: {description}

Result reported by the pipeline that made it:
{result}
{evidence}
Question: {question}

Judge from the evidence and the result above. Answer with exactly one
word first -- YES, NO, or UNKNOWN if neither shows it either way -- then,
on a new line, one short sentence of evidence."""

_STEP_LIMIT = 12


def _evidence(subject: dict) -> str:
    """The tool calls the session actually made, for the reviewer. Both
    prompts used to show only the task and the final answer's prose, so
    a correct patch with a green suite and a commit could fail on a
    question the answer's wording did not happen to cover (2026-09-07)."""
    steps = subject.get("steps") or []
    if not steps:
        return ""
    lines = []
    for step in steps[-_STEP_LIMIT:]:
        tool = step.get("tool") or step.get("phase") or "step"
        mark = {True: "ok", False: "FAILED"}.get(step.get("ok"), "")
        summary = " ".join(str(step.get("summary") or "").split())
        lines.append(f"- {tool}: {summary[:400]}  {mark}".rstrip())
    return "\nWhat was actually done, in order:\n" + "\n".join(lines) + "\n"


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
    template = (_RESEARCH_CHECKLIST_PROMPT if req.subject.get("kind") == "research" else _CHECKLIST_PROMPT)
    reply: ThinkReply = await think(
        purpose="review",
        prompt=template.format(
            description=req.subject.get("description", ""), result=req.subject.get("result", ""), max_items=max_items,
            evidence=_evidence(req.subject),
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
                description=req.subject.get("description", ""), result=req.subject.get("result", ""), question=item.question,
                evidence=_evidence(req.subject),
            ),
        )
        answer = None if (reply.floor or not reply.ok) else parse_verdict(reply.text)
        answered.append(AnsweredItem(question=item.question, required=item.required, answer=answer, evidence=reply.text.strip()))
    return answered
