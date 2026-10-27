"""Does the block hold the right fact? (stage 15 item 4)

Deterministic, like the household probes (`evals/scenario.py`): no model
judges anything. Each system hands back its context as lines -- one fact a
line -- and a line that begins with `PAST` is something that *used to*
hold (a superseded native fact, a Graphiti edge with `invalid_at`). The
rules are in `corpus.py`'s docstring; this is their arithmetic.
"""

from __future__ import annotations

import re

from .corpus import Question

#: The prefix of a line that held once and no longer does.
PAST = "[past] "


def norm(text: str) -> str:
    """Casefolded, letters and digits only: "0612 448 190" == "0612-448-190"."""
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def check(question: Question, lines: list[str]) -> tuple[bool, str]:
    """(passed, why not) for one question against one block."""
    flat = [norm(line) for line in lines]
    current = [norm(line) for line in lines if not line.startswith(PAST)]
    for group in question.expect:
        wanted = [norm(s) for s in group]
        if not any(all(w in line for w in wanted) for line in flat):
            return False, f"missing {' + '.join(group)}"
    for value in question.stale:
        if any(norm(value) in line for line in current):
            return False, f"stale value {value!r} given as current"
    for group in question.forbid:
        banned = [norm(s) for s in group]
        if any(all(b in line for b in banned) for line in flat):
            return False, f"leaked {' + '.join(group)}"
    return True, ""


__all__ = ["PAST", "check", "norm"]
