"""Finding the answer inside a prose reply.

The prompt scaffold asks for a `FINAL ANSWER:` line, so that marker is
a protocol between the prompt and everything that reads a reply --
the benchmark scorer, the worker's narration, and (since 2026-09-20)
Planning's no-progress guard.

It lives in contracts because three packages need it and none of them
may import the others. It was in `benchmark/scoring.py` alone, which
is why Planning compared whole prose instead: on the creator's GAIA
run that evening one case answered `FINAL ANSWER: 2` six times with
completely different reasoning around it each time, the guard saw six
different strings, and the task retried until the ten-minute case
timeout killed it.
"""

from __future__ import annotations

FINAL_ANSWER_PREFIX = "FINAL ANSWER:"


def final_answer(text: str) -> str:
    """The answer out of a prose reply.

    The last `FINAL ANSWER:` line wins -- a model that restates the
    format instruction before answering would otherwise have its own
    example read as the answer. With no such line, the last non-empty
    line is used: a right answer stated plainly should not score zero
    because of a missing prefix, though the prompt does ask for one.
    """
    # Runs of spaces collapsed per line before the marker is looked
    # for, so a model that writes "FINAL  ANSWER:" is read the same as
    # one that writes it properly. Newlines are kept, because the last
    # LINE carrying the marker is what wins.
    lines = [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        upper = line.upper()
        if FINAL_ANSWER_PREFIX in upper:
            index = upper.rindex(FINAL_ANSWER_PREFIX) + len(FINAL_ANSWER_PREFIX)
            return line[index:].strip().strip("*` ")
    return lines[-1].strip().strip("*` ") if lines else ""


__all__ = ["FINAL_ANSWER_PREFIX", "final_answer"]
