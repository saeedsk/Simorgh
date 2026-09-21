"""The checkpoint critic (stage 7 item 6): is this still going to work?

Verification has always been something that happens at the end -- the
answer is in, was it true? A long task fails differently: it wanders, and
nothing notices until the budget is gone and the answer is wrong. The
critic asks a cheaper question at every progress note: given what has
happened so far, is this trajectory still going to meet the acceptance
criteria?

Three verdicts and a refusal:

    on_track              carry on
    drifting              it is going somewhere else; twice in a row re-plans
    blocked               it cannot get there from here
    insufficient_evidence the note does not say, and guessing is worse

The prompt is deliberately small and the tier is the cheap one: a critic
that costs as much as the work is a critic nobody can afford to run at
every note.
"""

from __future__ import annotations

import json
import re

VERDICTS = ("on_track", "drifting", "blocked", "insufficient_evidence")

PROMPT = (
    "You are checking, mid-task, whether work is still going where it should. Below are the "
    "goal, what counts as done, and what has happened so far.\n\n"
    "Reply with ONLY a JSON object: "
    '{"verdict": "on_track|drifting|blocked|insufficient_evidence", '
    '"unmet": ["criteria not met yet"], "next": "the one thing to do next", "why": "one sentence"}.\n\n'
    "on_track: the work is heading at the criteria, even if slowly. drifting: it is doing "
    "something else, or repeating itself. blocked: it cannot get there from here -- a refusal, "
    "a missing capability, a wrong assumption it keeps acting on. insufficient_evidence: what "
    "you were given does not say; use it rather than guessing. Judge the trajectory, not the "
    "wording, and do not invent progress that is not written down."
)


def prompt_for(*, goal: str, acceptance, trajectory: str) -> str:
    criteria = "\n".join(f"- {c}" for c in (acceptance or [])) or "- (none stated; judge against the goal)"
    return (f"{PROMPT}\n\nGoal:\n{goal}\n\nDone when:\n{criteria}\n\n"
            f"What has happened so far:\n{trajectory}")


def parse(text: str) -> dict:
    """The critic's answer, or `insufficient_evidence` when it did not
    answer in the shape it was asked for. A critic whose reply cannot be
    read has not judged anything, and reading prose as a verdict is how a
    checker becomes a rubber stamp."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {"verdict": "insufficient_evidence", "why": "the critic did not answer in JSON"}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {"verdict": "insufficient_evidence", "why": "the critic's JSON could not be read"}
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return {"verdict": "insufficient_evidence", "why": f"unknown verdict {verdict!r}"}
    out = {"verdict": verdict}
    unmet = [" ".join(str(u).split()) for u in (data.get("unmet") or []) if str(u).strip()]
    if unmet:
        out["unmet"] = unmet[:6]
    for key in ("next", "why"):
        value = " ".join(str(data.get(key) or "").split())
        if value:
            out[key] = value[:300]
    return out


#: Verdicts that change what happens next, and so are worth a second
#: opinion. `on_track` and `insufficient_evidence` both mean "carry
#: on", so confirming them buys nothing and costs a model call at
#: every progress note of every long task.
ACTIONABLE = ("drifting", "blocked")

#: How many samples an actionable verdict is decided by.
SAMPLES = 3


def wants_confirming(verdict: str) -> bool:
    """Whether this verdict is worth asking twice more about.

    The plan (stage 7 item 6) says "majority vote of three cheap
    samples" flatly, and three samples at every note of every long
    task is three times the cost for a question that is usually
    "yes, fine". So the vote is spent where it changes something:
    ending an attempt on one cheap sample is the call worth being
    sure about, and carrying on is the default anyway. Recorded as a
    decision in the plan file, 2026-09-20.
    """
    return verdict in ACTIONABLE


def majority(answers: list[dict]) -> dict:
    """The verdict most of the samples agree on, with that sample's
    reasoning. A tie falls back to the first answer, which is the one
    that raised the question.

    `insufficient_evidence` votes count: a critic that could not read
    the trajectory twice out of three times has not established
    drifting, and abandoning an attempt on that is exactly the
    rubber-stamp-in-reverse this module exists to avoid.
    """
    if not answers:
        return {"verdict": "insufficient_evidence", "why": "the critic was not asked"}
    counts: dict[str, int] = {}
    for answer in answers:
        verdict = str(answer.get("verdict") or "insufficient_evidence")
        counts[verdict] = counts.get(verdict, 0) + 1
    verdict, votes = max(counts.items(), key=lambda kv: kv[1])
    if votes * 2 <= len(answers):
        # Three samples, three different answers. A plurality of one
        # is the single sample this vote exists to stop trusting, and
        # that is just as true of an encouraging answer as a damning
        # one -- so no verdict without agreement, in either direction.
        return {"verdict": "insufficient_evidence",
                "why": f"the critics did not agree ({', '.join(sorted(counts))})",
                "votes": f"{votes}/{len(answers)}"}
    for answer in answers:
        if answer.get("verdict") == verdict:
            out = dict(answer)
            out["votes"] = f"{votes}/{len(answers)}"
            return out
    return {"verdict": verdict, "votes": f"{votes}/{len(answers)}"}


__all__ = ["ACTIONABLE", "PROMPT", "SAMPLES", "VERDICTS", "majority", "parse", "prompt_for",
           "wants_confirming"]
