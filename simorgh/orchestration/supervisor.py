"""Sim's supervisor: a bar raiser over every job asked for in chat
(`[orchestration] supervisor`).

The creator, 2026-10-28: "create a supervisor submind for Sim that would
adopt Amazon's Leadership Principles, monitor Sim's task assignment and
delivery, supervise and nudge, give feedback and raise the bar of Sim's
task quality -- and Sim has to obey it." Then: "translate the LPs into
tangible and understandable logic for the submind." The same evening Sim
had unsubscribed one sender of six per turn and ended each turn on "Next
I'll work through the rest", counted "the top five promo senders of the
month" from the newest twenty, said "I sent the other five" when the
tool got one, and blamed "the turn got cut off" when nothing had.

The principles, as checks (`PRINCIPLES`): each one is a rule about this
job and a test the supervisor can apply to what the tools returned and
what Sim is about to say. Principles about hiring, people and scale have
no meaning for one job and are left out on purpose.

The supervisor acts twice in a turn that does work:

1. Setting the bar. At the turn's first tool call, beside it (no wait), it
   writes the job's success criteria and how each is measured
   (`criteria_prompt`, `parse_criteria`). They become `Session.acceptance`
   and are put in front of Sim once (`criteria_message`). A question or
   small talk gets none, and nothing else below happens.
2. Reviewing the delivery. A final answer while criteria are set is
   reviewed against the criteria and the principles (`review_prompt`,
   `parse_review`), reading what the tools actually returned
   (`trajectory`). Below the bar with steps left, the answer does not go
   out: the feedback goes back to Sim as an order (`order_message`). It
   reviews again only after more tools have run, so it cannot loop on
   words alone. `blocked` -- the rest needs the person, or a tool refused --
   lets the answer out, which must then say what is not done and why.
"""

from __future__ import annotations

import json
import re

#: Amazon's Leadership Principles that apply to one job, each as
#: (name, the rule for Sim, what the supervisor checks).
PRINCIPLES: tuple[tuple[str, str, str], ...] = (
    ("Customer Obsession",
     "Do what the person needs, at the scope they meant.",
     "Does the result cover every item the request covers -- \"all of them\" means every one from the list "
     "just discussed, \"the past month\" means the whole month?"),
    ("Ownership",
     "Finish the whole job in this turn; it is yours until it is done.",
     "Does the answer stop with items left that a tool could still do, end on a promise (\"next I'll...\"), "
     "or hand the person work Sim could do itself?"),
    ("Bias for Action",
     "Act on what was already asked; ask only for a decision that is truly the person's.",
     "Does the answer ask permission (\"want me to...?\") for something the request already asked for?"),
    ("Insist on the Highest Standards",
     "Complete and checked, never a sample presented as the whole.",
     "Is a count, ranking or 'all' computed from a capped or cut-off result (\"Stopped at the limit\", "
     "\"output cut off\") without saying so or fetching the rest?"),
    ("Dive Deep",
     "Every number and every 'done' comes from a tool result in this turn.",
     "Is there a figure, status or outcome in the answer that no tool result shows?"),
    ("Earn Trust",
     "Say exactly what happened, failures first; never claim more than the tools show; no excuses "
     "without evidence.",
     "Does the answer claim something done, sent or checked that the tools show otherwise or not at all, "
     "or blame something (\"it got cut off\") that the record does not show?"),
    ("Deliver Results",
     "Report each success criterion: met or not met, with its measure.",
     "Does the answer give each criterion's outcome with the evidence (a status, a count, a name)?"),
    ("Invent and Simplify",
     "When one route fails, take the next one before giving up.",
     "Did a tool report another way (a page to open, a narrower search, a different tool) that Sim did not "
     "try?"),
    ("Frugality",
     "No wasted steps: one call that covers many items beats many calls; never repeat a call that already "
     "answered.",
     "Did Sim repeat the same call, or do one item per call where the tool takes many?"),
)


def principles_text() -> str:
    return "\n".join(f"- {name}: {rule} Check: {check}" for name, rule, check in PRINCIPLES)


CRITERIA_PROMPT = (
    "You are the supervisor of an assistant with tools, and you set the bar for the job below. Write what "
    "DONE means: 1 to 5 success criteria, each checkable from what the tools return, each with how it is "
    "measured. Be concrete and countable: name every item the request covers (every sender, every file, "
    "every light), give the number where there is one, and say what result proves it (\"HTTP 2xx from each "
    "sender's unsubscribe\", \"a search covering the whole 30 days, not a capped page\").\n"
    'Reply with ONLY JSON: {"criteria": [{"done_when": "...", "measured_by": "..."}]}.\n'
    'A question that only needs an answer, small talk, or a single quick lookup: {"criteria": []}.'
)

REVIEW_PROMPT = (
    "You are the supervisor of an assistant with tools: a bar raiser who holds it to these principles, "
    "each with the check that applies it.\n{principles}\n\n"
    "Below are the request, the success criteria, what the tools returned (the only evidence), and the "
    "answer the assistant is about to give. Judge the work and the answer, not the wording.\n"
    'Reply with ONLY JSON: {{"verdict": "meets_bar|below_bar|blocked", "unmet": ["criteria not met"], '
    '"principle": "the principle most broken, or none", "feedback": "what falls short, in one or two '
    'sentences", "next": "the one concrete action the assistant must take now"}}.\n'
    "meets_bar: every criterion is met with evidence above, and the answer claims nothing the evidence "
    "does not show. below_bar: something can still be done with the tools, or the answer must be "
    "corrected. blocked: what is left cannot be done from here (it needs the person, a tool refused, the "
    "service does not allow it) AND the answer says so plainly -- if it hides it, that is below_bar."
)

#: Most criteria a job carries; more is a plan, not a checklist.
MAX_CRITERIA = 5
VERDICTS = ("meets_bar", "below_bar", "blocked")


def criteria_prompt(request: str, recent: list[dict]) -> str:
    """The bar-setting think's one message: the request, with the
    conversation just before it ("unsubscribe from all of them" names
    nothing alone)."""
    return f"{CRITERIA_PROMPT}\n\nConversation so far:\n{_context(recent)}\n\nThe request:\n{request[:800]}"


def _context(recent: list[dict]) -> str:
    lines = []
    for m in recent[-6:]:
        content = " ".join(str(m.get("content") or "").split())
        if content:
            lines.append(f"[{m.get('role', 'user')}] {content[:600]}")
    return "\n".join(lines)[-3000:] or "(none)"


def _json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_criteria(text: str) -> list[str]:
    """`done when: X -- measured by: Y` lines, or [] when the reply holds
    none (a question, or an answer not in the shape asked for: no
    criteria is better than invented ones)."""
    data = _json(text)
    if data is None:
        return []
    out = []
    for item in (data.get("criteria") or [])[:MAX_CRITERIA]:
        if not isinstance(item, dict):
            continue
        done = " ".join(str(item.get("done_when") or "").split())
        how = " ".join(str(item.get("measured_by") or "").split())
        if done:
            out.append(f"done when: {done[:240]}" + (f" -- measured by: {how[:200]}" if how else ""))
    return out


def short(criterion: str) -> str:
    """A criterion without its prefix and measure, for the screen."""
    text = criterion[len("done when: "):] if criterion.startswith("done when: ") else criterion
    return text.split(" -- measured by")[0]


def criteria_message(criteria: list[str]) -> str:
    listed = "\n".join(f"{i}. {c[len('done when: '):] if c.startswith('done when: ') else c}"
                       for i, c in enumerate(criteria, 1))
    return ("Your supervisor set the bar for this job. You own it. Success criteria, and how each is measured:\n"
            f"{listed}\n"
            "Keep working, one tool call per step, until every criterion is met or you have shown it cannot be "
            "(a tool refused, a page needs a person, the service does not allow it). Do not stop at the first "
            "result, do not ask permission for what was already asked, do not end on a promise. Your final "
            "answer reports each criterion: met or not met, with the evidence from a tool result. Your "
            "supervisor reviews it before it goes out.")


def trajectory(steps) -> str:
    """What the tools returned this turn, newest last, for the review.
    Head and tail of each result: a cut-off note ("Stopped at the limit")
    sits at the END of a listing."""
    lines = []
    for step in steps:
        tool = getattr(step, "tool", None)
        if not tool:
            continue
        ok = getattr(step, "ok", None)
        mark = "ok" if ok else ("FAILED" if ok is False else "?")
        summary = " ".join(str(getattr(step, "summary", "") or "").split())
        if len(summary) > 520:
            summary = f"{summary[:320]} ... {summary[-200:]}"
        lines.append(f"- {tool} [{mark}]: {summary}")
    return "\n".join(lines)[-4000:] or "(no tool ran)"


def review_prompt(*, request: str, criteria: list[str], steps, answer: str) -> str:
    listed = "\n".join(f"- {c}" for c in criteria)
    return (REVIEW_PROMPT.format(principles=principles_text())
            + f"\n\nThe request:\n{request[:800]}\n\nSuccess criteria:\n{listed}\n\n"
              f"What the tools returned:\n{trajectory(steps)}\n\nThe answer about to be given:\n{answer[:1200]}")


def parse_review(text: str) -> dict:
    """The supervisor's verdict, or `unread` when it did not answer in the
    shape asked for -- a review that cannot be read has not judged
    anything, and the answer goes out as it was."""
    data = _json(text)
    if data is None:
        return {"verdict": "unread"}
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return {"verdict": "unread"}
    out: dict = {"verdict": verdict,
                 "unmet": [" ".join(str(u).split())[:200] for u in (data.get("unmet") or []) if str(u).strip()][:6]}
    for key in ("principle", "feedback", "next"):
        value = " ".join(str(data.get(key) or "").split())
        if value and value.lower() != "none":
            out[key] = value[:400]
    return out


def order_message(review: dict) -> str:
    """The review, as an order Sim follows before it may answer."""
    principle = review.get("principle")
    unmet = "; ".join(review.get("unmet") or [])
    return ("Your supervisor reviewed this and it is BELOW THE BAR"
            + (f" ({principle})" if principle else "") + ". "
            + (f"{review['feedback']} " if review.get("feedback") else "")
            + (f"Not met: {unmet}. " if unmet else "")
            + (f"Do now: {review['next']}. " if review.get("next") else "")
            + "This is not optional: act on it with a tool call now and keep going. If something truly cannot "
              "be done, your answer says which, why, and the evidence.")


__all__ = ["CRITERIA_PROMPT", "MAX_CRITERIA", "PRINCIPLES", "REVIEW_PROMPT", "VERDICTS", "criteria_message",
           "criteria_prompt", "order_message", "parse_criteria", "parse_review", "principles_text",
           "review_prompt", "short", "trajectory"]
