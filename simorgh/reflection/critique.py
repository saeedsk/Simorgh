"""Self-critique deltas (spec section 5.3): one bounded `cognition.think`
call per terminal task, parsed leniently as JSON; a floor template when
no provider answers or the reply doesn't parse -- never a fabricated
critique (principle 4.5, the guaranteed floor)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class Critique:
    what_changed: str
    confidence: float | None
    open_questions: list[str]
    lesson: str | None
    floor: bool


def floor_critique(mechanical_summary: str) -> Critique:
    return Critique(what_changed=mechanical_summary, confidence=None, open_questions=[], lesson=None, floor=True)


def parse_critique(text: str, *, mechanical_summary: str) -> Critique:
    """Leniently extract the first JSON object in `text`; any failure
    (no provider, unparseable reply, missing keys) returns the floor
    template rather than a partially-fabricated critique."""
    if not text or not text.strip():
        return floor_critique(mechanical_summary)
    match = _JSON_OBJ_RE.search(text)
    if match is None:
        return floor_critique(mechanical_summary)
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return floor_critique(mechanical_summary)
    if not isinstance(data, dict):
        return floor_critique(mechanical_summary)

    what_changed = data.get("what_changed") or mechanical_summary
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = None
    else:
        confidence = max(0.0, min(1.0, float(confidence)))
    open_questions = data.get("open_questions")
    if isinstance(open_questions, str):
        open_questions = [open_questions] if open_questions else []
    elif not isinstance(open_questions, list):
        open_questions = []
    lesson = data.get("lesson")
    if not isinstance(lesson, str):
        lesson = None

    return Critique(what_changed=str(what_changed), confidence=confidence, open_questions=[str(q) for q in open_questions], lesson=lesson, floor=False)
