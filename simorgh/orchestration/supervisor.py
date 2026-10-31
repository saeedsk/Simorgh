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
     "Do what the person needs, at the scope they meant, as fast as it can be done.",
     "Does the result cover every item the request covers -- \"all of them\" means every one from the list "
     "just discussed, \"the past month\" means the whole month -- and did the person wait no longer than "
     "needed (independent parts done one after another when they could run at once, or a long job held in a "
     "spoken turn instead of sent to the background)?"),
    ("Ownership",
     "Finish the whole job in this turn; it is yours until it is done.",
     "Does the answer stop with items left that a tool could still do, end on a promise (\"next I'll...\"), "
     "or hand the person work Sim could do itself?"),
    ("Bias for Action",
     "Act on what was already asked; ask only for a decision that is truly the person's.",
     "Does the answer ask permission (\"want me to...?\") for something the request already asked for, or did "
     "Sim not start the approach its bar set (the helpers in parallel, the program, the background run) "
     "and do the job some slower way?"),
    ("Insist on the Highest Standards",
     "Complete and checked, never a sample presented as the whole.",
     "Is a count, ranking or 'all' computed from a capped or cut-off result (\"Stopped at the limit\", "
     "\"output cut off\") without saying so or fetching the rest, or is a count, rank, total or comparison "
     "over many items taken from a listing the model read instead of computed by a program over the full "
     "data?"),
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


CRITERIA_INTRO = (
    "You are the supervisor of an assistant with tools, and you set the bar for the job below. Write what "
    "DONE means: 1 to 5 success criteria, each checkable from what the tools return, each with how it is "
    "measured. Be concrete and countable: name every item the request covers (every sender, every file, "
    "every light), give the number where there is one, and say what result proves it (\"HTTP 2xx from each "
    "sender's unsubscribe\", \"a search covering the whole 30 days, not a capped page\").\n"
)

CRITERIA_PROMPT = CRITERIA_INTRO + (
    'Reply with ONLY JSON: {"criteria": [{"done_when": "...", "measured_by": "..."}]}.\n'
    'A question that only needs an answer, small talk, or a single quick lookup: {"criteria": []}.'
)

#: The approaches (stage 19, `[orchestration] supervisor_approach`): HOW a
#: job is done, chosen at bar-setting from the shape of the job. General
#: triggers only -- the creator, 2026-10-28: "solve this lack of intuitive
#: thinking for all cases"; a rule per tool or per subject is the fix he
#: rejected.
APPROACHES = ("direct", "compute", "parallel", "decompose", "background")
#: The approaches whose split names parts, each a crew member.
SPLIT_APPROACHES = ("parallel", "decompose")
#: Most parts a split has; more is a project, not a turn.
MAX_SPLIT = 6
#: Execution's workbench (stage 19 items 1-3), named rather than imported:
#: a subsystem may not import another.
ANALYSIS_TOOL = "run_analysis"
#: The read-only agent a chat or voice turn starts a part as (stage 18's
#: `CHAT_CREW_AGENTS`); it has the code tools (`profiles.CODE_TOOLS`).
PART_AGENT = "research"

#: The scope rule (2026-10-30): "every item the request covers" is what the
#: request names, not the most a tool could reach. "summarize my emails"
#: got a bar of every message in the box, each with its own gist; three
#: reviews held a fair digest of the newest page below it while Sim
#: widened to 200 messages, filled its context and hit the program's call
#: cap, and never answered (live, task cef68b40).
SCOPE_RULE = (
    "Scope: cover what the request names -- \"all of them\", \"the past month\" -- and no more. When it names "
    "no scope or count, the bar is a sensible default the person would expect at a glance (the newest or "
    "unread page, the current period, the top few), and one criterion is that the answer states that scope "
    "and offers to go wider. Never set a bar that needs everything a source holds, or one item-by-item "
    "result for more items than fit in one answer, unless the request asks for exactly that.\n"
)

APPROACH_PROMPT = SCOPE_RULE + (
    "Then choose the approach: HOW the job is done, fastest, with an exact answer. Judge by the shape of the "
    "job, never by its subject:\n"
    "- direct: one or a few tool calls answer it, and the answer reads straight off what they return.\n"
    "- compute: a program over the full data (the run_analysis tool). Choose it when the job covers more "
    "items than one page of a tool's result shows; when the answer is a count, rank, total, average, dedupe "
    "or comparison over many items; when the same step repeats for each item; or when it joins two sources. "
    "Reading a listing and counting by eye is never the method. A program counts, filters and joins; it "
    "cannot read for meaning, so a job whose result is judgment over each item's text (a gist, a summary, "
    "a verdict) is not compute: it is direct over the scope, or parallel when the items are many.\n"
    "- parallel: 2 to 6 independent parts, each run at the same time by its own helper. Choose it when the "
    "parts do not depend on each other: the same work for each of several items or sources, several options "
    "to compare, or more steps than one helper can take in this turn while the parts could run side by side.\n"
    "- decompose: 2 to 6 parts that depend on each other, run in order, each part's result feeding the next.\n"
    "- background: longer than this turn can take (many pages, many items, slow sources): start it, say so, "
    "and deliver the result when it is done.\n"
    "Prefer the fastest approach that still gets the exact answer: parallel over doing independent parts one "
    "by one, compute over reading. For parallel and decompose, give the split: each part with a brief a "
    "helper can act on alone, its own measurable criterion, and its own approach (usually compute or direct).\n"
    'Reply with ONLY JSON: {"approach": "direct|compute|parallel|decompose|background", "why": "the trigger, '
    'in one sentence", "criteria": [{"done_when": "...", "measured_by": "..."}], "split": [{"brief": "...", '
    '"done_when": "...", "measured_by": "...", "approach": "compute|direct"}]}. "split" only for parallel '
    "and decompose.\n"
    'A question that only needs an answer, small talk, or a single quick lookup: {"approach": "direct", '
    '"criteria": []}.'
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
#: The method check (stage 19 item 5), added to the review when the
#: approach is on: how the answer was got is judged, not only what it says.
REVIEW_METHOD = (
    "\nThe method is judged too. An aggregate -- a count, rank, total, average or comparison over many "
    "items -- that the answer took from a listing the assistant read, rather than from a program over the "
    "full data (a run_analysis result), is below_bar, and next is: run_analysis over that listing's ref. "
    "If the bar set an approach (helpers in parallel, a program, the background) and the assistant did the "
    "job another, slower way, that is below_bar too (Bias for Action; Customer Obsession when the person "
    "waited longer than needed), and next names what to start.\n"
    "Scope is judged by the request, not the criteria alone. When the request named no scope, an answer "
    "that covers a sensible default scope, says which, and offers to go wider meets that part, even if a "
    "criterion asks for every item a source holds; never order the assistant to widen past what the person "
    "asked for."
)

#: Most criteria a job carries; more is a plan, not a checklist.
MAX_CRITERIA = 5
VERDICTS = ("meets_bar", "below_bar", "blocked")


def criteria_prompt(request: str, recent: list[dict], *, approach: bool = False, lessons=()) -> str:
    """The bar-setting think's one message: the request, with the
    conversation just before it ("unsubscribe from all of them" names
    nothing alone). `approach` asks for the approach and the split as
    well (stage 19); `lessons` are earlier reviews' rules recalled for a
    similar job (`recall_lessons`)."""
    head = (CRITERIA_INTRO + APPROACH_PROMPT) if approach else CRITERIA_PROMPT
    learnt = lessons_text(lessons)
    return (head + (f"\n\n{learnt}" if learnt else "")
            + f"\n\nConversation so far:\n{_context(recent)}\n\nThe request:\n{request[:800]}")


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


class Bar(list):
    """The criteria (a list of `done when: X -- measured by: Y` lines, as
    before) and how the job is to be done: `approach` (one of
    `APPROACHES`), `why`, and for parallel and decompose the `split` --
    parts as `{"brief", "criterion", "approach"}`."""

    def __init__(self, criteria=(), *, approach: str = "direct", why: str = "", split=()) -> None:
        super().__init__(criteria)
        self.approach = approach
        self.why = why
        self.split = list(split)


def _criterion(item: dict) -> str:
    done = " ".join(str(item.get("done_when") or "").split())
    how = " ".join(str(item.get("measured_by") or "").split())
    if not done:
        return ""
    return f"done when: {done[:240]}" + (f" -- measured by: {how[:200]}" if how else "")


def parse_criteria(text: str) -> Bar:
    """`done when: X -- measured by: Y` lines, or [] when the reply holds
    none (a question, or an answer not in the shape asked for: no
    criteria is better than invented ones), carrying the approach. An
    approach not named, or not one of `APPROACHES`, is `direct`: the turn
    as it was. A split of fewer than two parts is no split."""
    data = _json(text)
    if data is None:
        return Bar()
    out = []
    for item in (data.get("criteria") or [])[:MAX_CRITERIA]:
        if isinstance(item, dict) and _criterion(item):
            out.append(_criterion(item))
    approach = str(data.get("approach") or "direct").strip().lower()
    approach = approach if approach in APPROACHES else "direct"
    split = []
    if approach in SPLIT_APPROACHES:
        for item in (data.get("split") or [])[:MAX_SPLIT]:
            if not isinstance(item, dict):
                continue
            brief = " ".join(str(item.get("brief") or "").split())
            if not brief:
                continue
            inner = str(item.get("approach") or "direct").strip().lower()
            split.append({"brief": brief[:400], "criterion": _criterion(item),
                          "approach": inner if inner in ("direct", "compute") else "direct"})
        if len(split) < 2:
            approach, split = "direct", []
    why = " ".join(str(data.get("why") or "").split())[:240]
    return Bar(out, approach=approach, why=why, split=split)


def effective_approach(approach: str, *, voice: bool, crews: bool, compute: bool) -> str:
    """The approach the turn can actually take: `compute` needs the
    workbench offered, a crew approach needs `[orchestration] chat_crews`
    (without it the parts stay on Sim's own checklist), and a spoken turn
    -- six steps -- sends anything but `direct` to the background."""
    if approach == "compute" and not compute:
        approach = "direct"
    if approach in (*SPLIT_APPROACHES, "background") and not crews:
        approach = "direct"
    if voice and approach != "direct":
        approach = "background"
    return approach


def implied_criteria(approach: str, split) -> list[str]:
    """The criteria an approach brings: each part's own (they are part of
    the bar), and for a job with none, what its method must show."""
    out = [p["criterion"] for p in split if p.get("criterion")]
    if out:
        return out
    if approach == "compute":
        out.append(f"done when: the answer comes from a program over the full data -- measured by: a "
                   f"{ANALYSIS_TOOL} result")
    elif approach == "background":
        out.append("done when: the job is started in the background and the person is told it is on its way "
                   "-- measured by: a spawn with background true")
    elif split:
        out.append(f"done when: every one of the {len(split)} parts has reported -- measured by: one report "
                   "per member")
    return out


def short(criterion: str) -> str:
    """A criterion without its prefix and measure, for the screen."""
    text = criterion[len("done when: "):] if criterion.startswith("done when: ") else criterion
    return text.split(" -- measured by")[0]


def criteria_message(criteria: list[str], *, approach: str = "direct", why: str = "", split=(), refs=(),
                     request: str = "", inner: str = "") -> str:
    listed = "\n".join(f"{i}. {c[len('done when: '):] if c.startswith('done when: ') else c}"
                       for i, c in enumerate(criteria, 1))
    text = ("Your supervisor set the bar for this job. You own it. Success criteria, and how each is measured:\n"
            f"{listed}\n"
            "Keep working, one tool call per step, until every criterion is met or you have shown it cannot be "
            "(a tool refused, a page needs a person, the service does not allow it). Do not stop at the first "
            "result, do not ask permission for what was already asked, do not end on a promise. Your final "
            "answer reports each criterion: met or not met, with the evidence from a tool result. Your "
            "supervisor reviews it before it goes out.")
    step = approach_step(approach, why=why, split=split, refs=refs, request=request, criteria=criteria,
                         inner=inner)
    return f"{text}\n\n{step}" if step else text


def _refs_text(refs) -> str:
    refs = [r for r in refs if r]
    return (", ".join(f'"{r}"' for r in refs[-4:]) if refs
            else '"last" (the newest result), or the `ref:` a result named')


def analysis_hint(refs=()) -> str:
    """The workbench's shape, as Sim is told it (stage 19's Definitions)."""
    first = next((r for r in reversed(list(refs)) if r), "last")
    example = json.dumps({"inputs": [first], "code": (
        "import sim, collections\n"
        f"rows = sim.rows({first!r})\n"
        "counts = collections.Counter(r.get('<column>') for r in rows)\n"
        "sim.result([{'value': k, 'n': n} for k, n in counts.most_common(10)])\n"
        "print(len(rows), counts.most_common(10))")})
    return (f"call {ANALYSIS_TOOL} with `inputs` = [{_refs_text(refs)}] and `code` = a Python program that "
            "uses the `sim` module: `sim.rows(ref)` gives every row of a result (all of it, not the page you "
            "saw); `sim.call(tool, **args)` runs one of your read-only tools from the program (the next page, "
            "or one call per item) and returns {ok, output, rows, ref}; `sim.db()` is a SQLite database kept "
            "for this job between calls; `sim.save(name, rows)` writes a .csv, .json or .md file; "
            "`sim.result(rows)` hands rows back; print what you found. Example: "
            f"{ANALYSIS_TOOL}{example}. Then answer from what the program printed")


_METHOD_HINT = (f" Compute it with {ANALYSIS_TOOL} over the full data (sim.rows over a result's ref, sim.call to "
                "page or loop), never by reading a listing.")


def part_brief(part: dict, *, request: str = "") -> str:
    """What one crew member is told: its part, its criterion, its method."""
    crit = short(part.get("criterion") or "")
    return (f"{part['brief']}" + (f" Done when: {crit}." if crit else "")
            + (_METHOD_HINT if part.get("approach") == "compute" else "")
            + " Report progress with report_progress at each milestone; end with the result and its evidence."
            + (f" (One part of: {request[:300]})" if request else ""))


def whole_brief(request: str, criteria, *, inner: str = "") -> str:
    """What one background member is told when the job is not split."""
    done = "; ".join(short(c) for c in criteria)
    return (request[:600] + (f" Done when: {done}." if done else "")
            + (_METHOD_HINT if inner in ("compute", *SPLIT_APPROACHES) else "")
            + " End with the result and its evidence.")


def _spawn_line(brief: str, *, background: bool = False) -> str:
    args: dict = {"agent": PART_AGENT, "brief": brief}
    if background:
        args["background"] = True
    return f"spawn{json.dumps(args)}"


def approach_step(approach: str, *, why: str = "", split=(), refs=(), request: str = "", criteria=(),
                  inner: str = "") -> str:
    """The concrete next step for an approach; "" for `direct` (the
    message as it was)."""
    because = f" ({why})" if why else ""
    if approach == "compute":
        return (f"Approach: compute{because}. Work it out with a program over the full data, not by reading a "
                f"listing: {analysis_hint(refs)}.")
    if approach == "parallel":
        spawns = "\n".join(f"- {_spawn_line(part_brief(p, request=request))}" for p in split)
        return (f"Approach: parallel{because}. Start every part NOW, all in one reply, without asking -- one "
                f"spawn per part:\n{spawns}\nThen await_agents for all of them (their progress is shown while "
                "they run), assemble one answer from the reports, and report each criterion with its evidence. "
                "Do not do the parts yourself one by one.")
    if approach == "decompose":
        parts = "\n".join(f"{i}. {_spawn_line(part_brief(p, request=request))}" for i, p in enumerate(split, 1))
        return (f"Approach: decompose{because}. Run the parts in order: spawn the first, await_agents for its "
                f"report, then spawn the next with what it needs from that report:\n{parts}\n"
                "Then assemble one answer and report each criterion with its evidence.")
    if approach == "background":
        if split:
            spawns = "\n".join(f"- {_spawn_line(part_brief(p, request=request), background=True)}" for p in split)
            say = f"splitting this into {len(split)}; I'll tell you when it's done"
            start = f"start every part now, in one reply:\n{spawns}\n"
        else:
            say = "on it; I'll tell you when it's done"
            start = f"start it now: {_spawn_line(whole_brief(request, criteria, inner=inner), background=True)}\n"
        return (f"Approach: background{because}. This takes longer than this turn has, so {start}"
                f"Then answer the person in one short sentence (\"{say}\") and stop: do not do the job "
                "yourself in this turn. The result reaches them when it is ready.")
    return ""


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


def review_prompt(*, request: str, criteria: list[str], steps, answer: str, method: str | None = None) -> str:
    """`method`: None is the review as it was; a string (maybe empty) adds
    the method check, with the approach and what ran when there is one."""
    listed = "\n".join(f"- {c}" for c in criteria)
    return (REVIEW_PROMPT.format(principles=principles_text()) + (REVIEW_METHOD if method is not None else "")
            + f"\n\nThe request:\n{request[:800]}\n\nSuccess criteria:\n{listed}\n\n"
            + (f"The approach the bar set, and what ran:\n{method}\n\n" if method else "")
            + f"What the tools returned:\n{trajectory(steps)}\n\nThe answer about to be given:\n{answer[:1200]}")


def _ran(steps, tool: str) -> list:
    return [s for s in steps if getattr(s, "tool", None) == tool]


def _overlapped(steps) -> bool:
    """Whether every spawn came before the first await: the members ran at
    once rather than one after another."""
    spawns = [getattr(s, "no", 0) for s in _ran(steps, "spawn") if getattr(s, "ok", None)]
    awaits = [getattr(s, "no", 0) for s in _ran(steps, "await_agents")]
    return bool(spawns) and (not awaits or max(spawns) < min(awaits))


def method_summary(approach: str, *, why: str = "", split=(), steps=()) -> str:
    """The approach the bar set and what actually ran, for the review."""
    if approach == "direct":
        return ""
    spawns = [s for s in _ran(steps, "spawn") if getattr(s, "ok", None)]
    analysis = [s for s in _ran(steps, ANALYSIS_TOOL) if getattr(s, "ok", None)]
    parts = "".join(f"\n  {i}. {p['brief'][:160]}" for i, p in enumerate(split, 1))
    return (f"Expected approach: {approach}" + (f" ({why})" if why else "")
            + (f", in {len(split)} parts:{parts}" if split else "")
            + f"\nWhat ran: {len(spawns)} member(s) spawned"
            + (f" of {len(split)} parts" if split else "")
            + (f", started together: {'yes' if _overlapped(steps) else 'no'}" if spawns else "")
            + f"; {len(analysis)} {ANALYSIS_TOOL} run(s).")


def method_check(approach: str, *, split=(), steps=(), refs=(), early: bool = False) -> dict | None:
    """Whether what ran follows the approach the bar set (stage 19): a
    `below_bar` review -- deterministic, no think -- when it does not, or
    None. `early`: only whether the first actions started it at all. A
    refused spawn or a failed program is not Sim ignoring its bar: the
    model's review judges that."""
    if approach == "direct":
        return None
    spawns = _ran(steps, "spawn")
    analysis = _ran(steps, ANALYSIS_TOOL)
    if any(getattr(s, "ok", None) is False for s in spawns + analysis):
        return None
    started = [s for s in spawns if getattr(s, "ok", None)]
    if approach in SPLIT_APPROACHES:
        if early and started:
            return None
        if len(started) >= len(split) and (approach != "parallel" or _overlapped(steps)):
            return None
        left = list(split)[len(started):] or list(split)
        briefs = " | ".join(part_brief(p)[:200] for p in left)
        if not started:
            return {"verdict": "below_bar", "principle": "Bias for Action", "unmet": [],
                    "feedback": (f"The bar set this job as {approach} in {len(split)} parts, and no member was "
                                 "started: the parts are being done one by one instead."),
                    "next": f"spawn the remaining members, all in one reply: {briefs}"}
        if len(started) < len(split):
            return {"verdict": "below_bar", "principle": "Customer Obsession", "unmet": [],
                    "feedback": (f"The bar split this job into {len(split)} parts and only {len(started)} "
                                 "member(s) were started, so the person waits for the rest."),
                    "next": f"spawn the remaining members, all in one reply: {briefs}"}
        return {"verdict": "below_bar", "principle": "Customer Obsession", "unmet": [],
                "feedback": "The parts are independent but were run one after another, not at once.",
                "next": "spawn the parts that are left together, in one reply, then await_agents for all"}
    if approach == "background":
        if any("background" in str(getattr(s, "summary", "")) for s in started):
            return None
        return {"verdict": "below_bar", "principle": "Bias for Action", "unmet": [],
                "feedback": "The bar sent this job to the background, and it is being done in the turn instead.",
                "next": ("spawn it in the background now (spawn with background true), then tell the person in "
                         "one short sentence that you are on it")}
    if approach == "compute":
        if analysis:
            return None
        ref = next((r for r in reversed(list(refs)) if r), "last")
        return {"verdict": "below_bar", "principle": "Insist on the Highest Standards", "unmet": [],
                "feedback": ("The bar set this job as a program over the full data, and it is being worked out "
                             "by reading a listing instead."),
                "next": f"{ANALYSIS_TOOL} over ref {ref}: inputs=[\"{ref}\"], code that computes it from sim.rows"}
    return None


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


# -- continuation (stage 19 item 7b(d)) ----------------------------------------
#
# The creator, 2026-10-28, by voice, after a six-step turn ended on "Say
# continue and I'll run the weekly searches": "You should do it
# automatically. You should not ask me. I already asked you." A turn that
# runs out of steps or time with its criteria unmet is not an ending: the
# job goes on as one background member, and the person is told in a line.

#: What the person hears when a job goes on in the background.
CONTINUES_ACK = "This needs more than one turn, so I'm carrying on with it in the background; I'll tell you when it's done."


def strategies_tried(steps, *, limit: int = 8) -> list[str]:
    """What this turn has already tried, one line per tool call, newest
    last: the continuation must not repeat them as they were."""
    out = []
    for step in steps:
        tool = getattr(step, "tool", None)
        if not tool:
            continue
        ok = getattr(step, "ok", None)
        mark = "ok" if ok else ("failed" if ok is False else "?")
        summary = " ".join(str(getattr(step, "summary", "") or "").split())
        out.append(f"{tool} [{mark}]: {summary[:120]}")
    return out[-limit:]


def continuation_brief(request: str, criteria, *, why: str, steps=(), refs=(), approach: str = "") -> str:
    """The background member's brief: the job, its bar, what was tried, and
    the results in hand -- everything the turn knew, so it carries on
    rather than starting again."""
    done = "; ".join(short(c) for c in criteria)
    tried = "\n".join(f"- {s}" for s in strategies_tried(steps))
    held = ", ".join(r for r in list(refs)[-6:] if r)
    return (f"Carry on with this job; the turn that started it {why}. The job: {request[:600]}"
            + (f"\nDone when: {done}." if done else "")
            + (f"\nAlready tried (do not repeat a call as it was; change the strategy):\n{tried}" if tried else "")
            + (f"\nResults in hand, readable in full with {ANALYSIS_TOOL} inputs=[...]: {held}." if held else "")
            + (_METHOD_HINT if approach in ("compute", *SPLIT_APPROACHES) else "")
            + "\nFinish the whole job; never ask the person whether to go on. End with the result for each "
              "criterion and its evidence.")


# -- lessons (stage 19 item 6, `[orchestration] supervisor_lessons`) ---------
#
# A lesson is written when a review was below the bar and the next review
# of the same turn met it: the order worked, so what it said is the rule.
# Recalled by text similarity into a later bar-setting prompt, so the same
# mistake is not made the next evening.

#: The ledger stream lessons live on (stage 19's Definitions).
LESSONS_STREAM = "supervisor:lessons"
#: Its event types: a lesson, and a lesson recalled (its `hits`).
LESSON_EVENT = "supervisor.lesson"
LESSON_HIT_EVENT = "supervisor.lesson.hit"
#: Most lessons a bar-setting prompt carries.
MAX_LESSONS = 3
#: How similar (cosine of `routing.lexical_embed`) a lesson's situation
#: must be to the request to be recalled.
LESSON_MIN_SIMILARITY = 0.15


def make_lesson(*, request: str, review: dict, fixed_by=(), evidence_ref: str = "", now: float = 0.0,
                lesson_id: str = "") -> dict:
    """`{situation, rule, evidence_ref, principle, created_at, hits}` (and
    an `id` for its hits): the order that worked, and what was run to meet it."""
    rule = review.get("next") or review.get("feedback") or ""
    tools = [t for t in dict.fromkeys(fixed_by) if t]
    if review.get("feedback") and review.get("next"):
        rule = f"{review['feedback']} Do: {review['next']}"
    if tools:
        rule += f" (what met the bar: {', '.join(tools)})"
    return {"id": lesson_id, "situation": " ".join(request.split())[:300], "rule": " ".join(rule.split())[:400],
            "evidence_ref": evidence_ref, "principle": review.get("principle", ""), "created_at": float(now),
            "hits": 0}


def fold_lessons(events) -> list[dict]:
    """The lessons on `LESSONS_STREAM`, with their hits counted."""
    lessons: dict[str, dict] = {}
    hits: dict[str, int] = {}
    for event in events:
        payload = dict(getattr(event, "payload", None) or {})
        kind = getattr(event, "type", "")
        if kind == LESSON_EVENT and payload.get("rule") and payload.get("situation"):
            key = str(payload.get("id") or len(lessons))
            lessons[key] = {**payload, "id": key}
        elif kind == LESSON_HIT_EVENT:
            for key in payload.get("ids") or ():
                hits[str(key)] = hits.get(str(key), 0) + 1
    for key, lesson in lessons.items():
        lesson["hits"] = int(lesson.get("hits") or 0) + hits.get(key, 0)
    return list(lessons.values())


def recall_lessons(lessons, request: str, *, limit: int = MAX_LESSONS,
                   min_similarity: float = LESSON_MIN_SIMILARITY) -> list[dict]:
    """The lessons whose situation is like `request`, most similar first,
    newest first on ties; at most `limit`."""
    from .routing import cosine, lexical_embed

    query = lexical_embed(request)
    scored = []
    for lesson in lessons:
        score = cosine(query, lexical_embed(str(lesson.get("situation") or "")))
        if score >= min_similarity:
            scored.append((round(score, 6), float(lesson.get("created_at") or 0.0), lesson))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [lesson for _score, _ts, lesson in scored[:max(0, limit)]]


def lessons_text(lessons) -> str:
    if not lessons:
        return ""
    lines = "\n".join(f"- {l['rule']} (learnt from: \"{l['situation'][:120]}\")" for l in lessons)
    return ("Lessons from your own earlier reviews of similar jobs; set the bar and the approach so the same "
            f"shortfall does not happen again:\n{lines}")


__all__ = ["ANALYSIS_TOOL", "APPROACHES", "APPROACH_PROMPT", "Bar", "CRITERIA_INTRO", "CRITERIA_PROMPT",
           "LESSONS_STREAM", "LESSON_EVENT", "LESSON_HIT_EVENT", "MAX_CRITERIA", "MAX_LESSONS", "MAX_SPLIT",
           "PART_AGENT", "PRINCIPLES", "REVIEW_METHOD", "REVIEW_PROMPT", "SPLIT_APPROACHES", "VERDICTS",
           "CONTINUES_ACK", "analysis_hint", "approach_step", "continuation_brief", "strategies_tried", "criteria_message", "criteria_prompt", "effective_approach",
           "fold_lessons", "implied_criteria", "lessons_text", "make_lesson", "method_check", "method_summary",
           "order_message", "parse_criteria", "parse_review", "part_brief", "principles_text", "recall_lessons",
           "review_prompt", "short", "trajectory", "whole_brief"]
