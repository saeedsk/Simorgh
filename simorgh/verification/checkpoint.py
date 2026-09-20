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


__all__ = ["PROMPT", "VERDICTS", "parse", "prompt_for"]
