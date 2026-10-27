"""The reliability layer around a session's proposals (stage 16 item 2,
docs/plan/stage-16-forge-guardrails.md).

Ported from forge (github.com/antoinezambelli/forge, MIT licence, by
Antoine Zambelli): `src/forge/guardrails/{response_validator,
error_tracker,step_enforcer,nudge}.py`, `src/forge/core/steps.py` and
`src/forge/prompts/nudges.py`, with ADR-010 (soft tool errors are not
counted), ADR-013 (a text reply is an answer when no tool is needed) and
ADR-016 (malformed arguments are corrected on the tool channel). The
logic is forge's; the names, budgets and the Guardian boundary are this
project's (the plan's Definitions).

Pure: no bus, no ledger, no clock. `session.py` calls these at the
proposal point and after each `action.result`, and owns the transcript
and the task stream.

What this never does is stand in for Guardian. `validate` refuses only
what Guardian would refuse as malformed -- a tool this session was not
offered, arguments that are not an object, or arguments that fail the
part of the tool's schema Guardian enforces (`schema_problems`, a subset
of `guardian/registry.py::enforced_schema`). Everything that survives is
still proposed and gated, and a Guardian denial stays a denial.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from simorgh.contracts import toolargs

#: Every nudge kind (the plan's Definitions; do not rename).
NUDGE_KINDS = ("unknown_tool", "bad_args", "retry", "step", "prerequisite")
#: The kinds that spend the retry budget. `step` and `prerequisite` have
#: their own counters (`Steps`).
RETRY_KINDS = frozenset({"unknown_tool", "bad_args", "retry"})
#: The kinds that ride the tool-result channel (forge's
#: `TOOL_CHANNEL_KINDS`): the model called a tool wrongly, so the
#: correction answers that call.
TOOL_CHANNEL_KINDS = frozenset({"unknown_tool", "bad_args"})

RETRIES_EXHAUSTED = "retries exhausted"
TOOL_ERRORS_EXHAUSTED = "tool errors exhausted"
STEPS_NOT_DONE = "required steps not done"
PREREQUISITES_NOT_DONE = "prerequisites not done"
#: A last-step call whose prerequisite has not run: there is no next think
#: to nudge, so the attempt ends (`Steps.check_last`).
PREREQUISITE_NOT_DONE = "prerequisite not done"
NO_RETRY_FIXES = "the same call was refused twice"


@dataclass(frozen=True)
class Nudge:
    """A message added to the transcript and sent with the next think.
    `role` is "tool" (the correction answers the call) or "user"."""

    role: str
    content: str
    kind: str
    tier: int = 0
    #: The call it answers, and what was wrong, in a few words (for the
    #: step record and `ablate = ["recovery"]`'s reason).
    tool: str = ""
    problem: str = ""


@dataclass(frozen=True)
class Ok:
    """The calls passed: propose them."""

    calls: tuple = ()


@dataclass(frozen=True)
class End:
    """A budget ran out: the session ends `outcome` with `reason`."""

    outcome: str  # "failed" | "blocked"
    reason: str


# -- nudge texts (forge's src/forge/prompts/nudges.py) ------------------------


def unknown_tool_text(tool: str, offered: Iterable[str]) -> str:
    return f"Tool '{tool}' does not exist. Available tools: {', '.join(offered)}. Call one of them."


def bad_args_text(tool: str, problem: str) -> str:
    return (f"Tool call to '{tool}' had malformed arguments: {problem}. "
            "Required: arguments must be a JSON object that matches the tool's schema. "
            "Re-emit the tool call with corrected arguments.")


def retry_text() -> str:
    # forge's wording says "you must respond with a tool call"; here a
    # text answer is allowed (ADR-013), so the nudge only fires on text
    # that looks like a call that did not come through.
    return ("Your previous response looked like a tool call but was not a valid one, so nothing ran. "
            "If you meant to call a tool, send the call again in the proper format. "
            "If you meant to answer, answer in plain text with no call in it.")


def step_text(terminal: str, pending: list[str], tier: int = 1) -> str:
    """forge's three wordings: polite, direct, then "STOP". `terminal`
    "" is a final answer in text."""
    tier = max(1, min(3, tier))
    steps = ", ".join(pending)
    what = f"call {terminal}" if terminal else "finish"
    if tier == 1:
        return (f"You cannot {what} yet. You must first complete these required steps: {steps}. "
                "Call one of them now.")
    if tier == 2:
        return f"You must call one of these tools now: {steps}. Pick one."
    return (f"STOP. You MUST call one of: {steps}. Do NOT {what}. "
            f"Your next response MUST be a tool call to one of: {steps}.")


def prerequisite_text(tool: str, missing: list[str]) -> str:
    return (f"You cannot call {tool} yet. You must first call: {', '.join(missing)}. "
            "Call the prerequisite tool now.")


# -- validation (forge's ResponseValidator) ------------------------------------

#: Guardian's widening (`guardian/registry.py::_WIDEN`): a scalar the
#: marker dialect wrote as text, and the other kinds it tolerates.
_WIDEN = {
    "string": ("number", "integer", "boolean", "null"),
    "number": ("string", "null"),
    "integer": ("string", "null"),
    "boolean": ("string", "null"),
    "array": ("string", "null"),
    "object": ("null",),
    "null": (),
}
_KIND = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _marker_guaranteed(tool: str) -> set[str] | None:
    """`guardian/registry.py::marker_guaranteed`: the argument names a
    marker line always supplies, or None when the tool has no marker
    shape and its schema's `required` stands in full."""
    if tool in toolargs.MARKER_NO_ARGS or tool in toolargs.MARKER_KEY_VALUES:
        return set()
    if tool in toolargs.MARKER_SPLIT_FIRST_LINE:
        first, second = toolargs.MARKER_SPLIT_FIRST_LINE[tool]
        return {first} if tool in toolargs.MARKER_JSON_REST else {first, second}
    if tool in toolargs.MARKER_ARG_KEY:
        return {toolargs.MARKER_ARG_KEY[tool]}
    return None


def schema_problems(tool: str, args: Any, schema: Mapping | None) -> list[str]:
    """Why `args` fail `tool`'s schema, checking only what Guardian
    enforces and only at the top level: an object; every required
    argument present (narrowed as Guardian narrows it for a marker
    tool); and no argument a different kind of value than declared,
    with Guardian's widening. Anything deeper is left to Guardian, so
    this can only ever refuse less than Guardian would."""
    if not isinstance(args, dict):
        return [f"arguments must be an object, got {type(args).__name__}"]
    if not isinstance(schema, Mapping):
        return []
    problems: list[str] = []
    required = schema.get("required")
    if isinstance(required, list):
        guaranteed = _marker_guaranteed(tool)
        for name in required:
            if (guaranteed is None or name in guaranteed) and name not in args:
                problems.append(f"'{name}' is required")
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for name, value in args.items():
            prop = properties.get(name)
            if not isinstance(prop, Mapping) or "type" not in prop or "anyOf" in prop or "oneOf" in prop:
                continue
            declared = prop["type"]
            names = [declared] if isinstance(declared, str) else list(declared or [])
            allowed = {n for d in names for n in (d, *_WIDEN.get(d, ()))}
            if allowed and not any(_KIND[n](value) for n in allowed if n in _KIND):
                problems.append(f"'{name}' must be {'|'.join(names)}, got {type(value).__name__}")
    return problems


def validate(calls: list[dict], offered: Iterable[str], schemas: Mapping[str, Mapping] | None = None,
             *, args_of: Callable[[dict], Any] | None = None) -> Ok | Nudge:
    """`Ok(calls)` or the first problem as a tool-channel nudge.

    Unknown tools first (forge: no point checking the arguments of a
    tool that does not exist), then argument shape. `args_of` gives the
    arguments as they will be proposed (a marker's `{"argument": ...}`
    mapped to the tool's own keys), so the check sees what Guardian
    will see."""
    offered = tuple(offered)
    for call in calls:
        tool = str(call.get("tool") or "")
        if tool not in offered:
            return Nudge("tool", unknown_tool_text(tool, offered), "unknown_tool",
                         tool=tool, problem=f"{tool} is not a tool of this session")
    for call in calls:
        tool = str(call.get("tool") or "")
        if call.get("error"):
            return Nudge("tool", bad_args_text(tool, str(call["error"])), "bad_args",
                         tool=tool, problem=f"a malformed {tool} call: {call['error']}")
        raw = call.get("args", {})
        if not isinstance(raw, dict):
            got = f"got {raw!r} (type: {type(raw).__name__})"
            return Nudge("tool", bad_args_text(tool, got), "bad_args", tool=tool,
                         problem=f"a malformed {tool} call: {got}")
        schema = (schemas or {}).get(tool)
        if schema:
            problems = schema_problems(tool, args_of(call) if args_of else raw, schema)
            if problems:
                return Nudge("tool", bad_args_text(tool, "; ".join(problems)), "bad_args", tool=tool,
                             problem=f"a malformed {tool} call: {'; '.join(problems)}")
    return Ok(tuple(calls))


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCED = re.compile(r"```(?:json)?\s*\n?(\{.*?\})\s*```", re.S)
_WHOLE_FENCE = re.compile(r"^```[\w-]*[ \t]*\n?(.*?)\n?[ \t]*```$", re.S)


def _only_a_call(body: str, offered: tuple) -> bool:
    """Whether `body`, without one code fence around all of it, is shaped
    like nothing but a call: it opens with `{`, `[`, `<` or an offered
    tool's name and closes with `}`, `)`, `]` or `>`. Any sentence before
    or after makes it an answer."""
    body = body.strip()
    fenced = _WHOLE_FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    if not body:
        return False
    opens = body[0] in "{[<" or any(body.startswith(name) for name in offered)
    return opens and body[-1] in "})]>"


def looks_like_call(text: str, offered: Iterable[str], *, whole: bool = False) -> bool:
    """Whether a text reply is a tool call that failed to come through
    (ADR-013's line): an offered tool's name followed by `(`, `{` or
    `[`, or a fenced JSON object whose `tool` or `name` key names an
    offered tool. Prose that merely mentions a tool is an answer, and so
    is JSON that is the answer itself (`{"name": "Ira", "age": 5}`):
    rescue would accept neither as a call either.

    `whole=True` is a conversation's rule, the same one Cognition's rescue
    keeps there (`rescue_tool_calls(whole=True)`): only a reply that is
    nothing but the call-shaped text counts. "Sure, I'd run ```{...}```"
    quotes a call inside an answer; nudging it would ask the model to run
    what it was only showing."""
    offered = tuple(n for n in offered if n)
    body = _THINK.sub("", text or "")
    if whole and not _only_a_call(body, offered):
        return False
    for name in offered:
        if re.search(rf"(?<![\w.]){re.escape(name)}[({{\[]", body):
            return True
    for block in _FENCED.findall(body):
        try:
            obj = json.loads(block)
        except ValueError:
            continue
        if isinstance(obj, dict) and any(obj.get(k) in offered for k in ("tool", "name")
                                         if isinstance(obj.get(k), str)):
            return True
    return False


# -- budgets (forge's ErrorTracker) -------------------------------------------


@dataclass
class ErrorBudget:
    """Consecutive retries and consecutive hard tool errors, per session.

    A retry is a nudge of a `RETRY_KINDS` kind; a clean proposal resets
    the count. A hard tool error is `error_kind == "failed"`; one or more
    in a step count once (forge counts a batch, not a call), and a step
    whose every result was ok resets the count. `transient` is soft (ADR-
    010): fed back, never counted. `refused` and `unconfigured` are fed
    back once; the same call refused again ends the session `blocked`,
    because no retry supplies a missing credential.

    `max_tool_errors = 0` turns the tool-error half off (`[orchestration]
    ablate = ["recovery"]` ends a session at the first failure instead)."""

    max_retries: int = 3
    max_tool_errors: int = 2
    retries: int = 0
    tool_errors: int = 0
    last_kind: str = ""
    _refused: set = field(default_factory=set)
    _step_hard: bool = False
    _step_ok: int = 0
    _step_other: int = 0

    def retry(self, kind: str) -> End | None:
        self.retries += 1
        self.last_kind = kind
        if self.retries > self.max_retries:
            return End("failed", f"{RETRIES_EXHAUSTED}: {kind}")
        return None

    def clean_proposal(self) -> None:
        self.retries = 0

    def result(self, ok: bool, kind: str = "", key: tuple = ()) -> End | None:
        """One tool result. Ends the session only for a repeated refusal;
        a hard error is counted at the step boundary (`end_step`)."""
        if ok:
            self._step_ok += 1
            return None
        self._step_other += 1
        if kind == "failed":
            self._step_hard = True
        elif kind in ("refused", "unconfigured") and key:
            if key in self._refused:
                return End("blocked", f"{NO_RETRY_FIXES} ({kind})")
            self._refused.add(key)
        return None

    def end_step(self) -> tuple[End | None, bool]:
        """Close the step: `(exhausted, clean)`. Safe to call twice; a
        step with no results is neither."""
        hard, clean = self._step_hard, self._step_ok > 0 and not self._step_other and not self._step_hard
        self._step_hard, self._step_ok, self._step_other = False, 0, 0
        if hard and self.max_tool_errors:
            self.tool_errors += 1
            if self.tool_errors > self.max_tool_errors:
                return End("failed", TOOL_ERRORS_EXHAUSTED), False
        if clean:
            self.tool_errors = 0
        return None, clean


# -- steps (forge's StepEnforcer and StepTracker) -----------------------------


def _prereq_tool(entry) -> str:
    return str(entry.get("tool") or "") if isinstance(entry, Mapping) else str(entry)


@dataclass
class Steps:
    """Required steps, terminal tools and prerequisites, from an agent's
    frontmatter, with the escalating nudges that enforce them.

    Kept on the session and not in the transcript, so compaction cannot
    erase it (forge's StepTracker, P0-1); `to_state`/`from_state` carry
    it across a crash.

    A required step counts once its tool has *succeeded*. A prerequisite
    counts once its tool has *run* -- ok, or a hard failure the tool
    itself reported -- because a test run that found a failure is still
    the test run the commit had to come after; whether the result is
    good enough is Verification's question, not this one's."""

    required: tuple[str, ...] = ()
    terminal: tuple[str, ...] = ()
    prerequisites: dict = field(default_factory=dict)
    max_premature: int = 3
    max_prereq: int = 2
    completed: list = field(default_factory=list)
    ran: dict = field(default_factory=dict)  # tool -> [ {match_arg: value} ]
    premature: int = 0
    prereq_violations: int = 0

    @property
    def active(self) -> bool:
        return bool(self.required or self.terminal or self.prerequisites)

    def pending(self) -> list[str]:
        return [s for s in self.required if s not in self.completed]

    def _match_keys(self, tool: str) -> list[str]:
        keys = []
        for entries in self.prerequisites.values():
            for entry in entries or ():
                if isinstance(entry, Mapping) and entry.get("tool") == tool and entry.get("match_arg"):
                    keys.append(str(entry["match_arg"]))
        return keys

    def tracks(self, tool: str) -> bool:
        return tool in self.required or any(
            _prereq_tool(e) == tool for entries in self.prerequisites.values() for e in entries or ())

    def record(self, tool: str, args: Any = None, *, ok: bool, ran: bool | None = None) -> None:
        if not self.tracks(tool):
            return
        if ok and tool not in self.completed:
            self.completed.append(tool)
        if ok or ran:
            args = args if isinstance(args, dict) else {}
            self.ran.setdefault(tool, []).append({k: args.get(k) for k in self._match_keys(tool) if k in args})

    def _missing(self, tool: str, args: Any) -> list[str]:
        missing: list[str] = []
        for entry in self.prerequisites.get(tool) or ():
            if isinstance(entry, Mapping):
                prereq, key = str(entry.get("tool") or ""), str(entry.get("match_arg") or "")
                if not isinstance(args, dict) or prereq not in self.ran:
                    missing.append(prereq)
                elif key and not any(done.get(key) == args.get(key) for done in self.ran[prereq]):
                    missing.append(prereq)
            elif str(entry) not in self.ran:
                missing.append(str(entry))
        return missing

    def check(self, calls: list[dict], *, args_of: Callable[[dict], Any] | None = None) -> Nudge | End | None:
        """A premature terminal call, then prerequisites, against the
        state before this batch. Any violation blocks the whole batch."""
        pending = self.pending()
        attempted = next((str(c.get("tool")) for c in calls if c.get("tool") in self.terminal), "")
        if attempted and pending:
            return self._premature(attempted, pending)
        for call in calls:
            tool = str(call.get("tool") or "")
            if not self.prerequisites.get(tool):
                continue
            missing = self._missing(tool, args_of(call) if args_of else call.get("args"))
            if missing:
                self.prereq_violations += 1
                if self.prereq_violations > self.max_prereq:
                    return End("blocked", f"{PREREQUISITES_NOT_DONE}: {tool} needs {', '.join(missing)}")
                return Nudge("user", prerequisite_text(tool, missing), "prerequisite", tool=tool,
                             problem=f"{tool} before {', '.join(missing)}")
        return None

    def check_last(self, call: dict, *, args_of: Callable[[dict], Any] | None = None) -> End | None:
        """The one call the LAST step would still run (a finishing or
        durable tool, `session.py`): its prerequisites hold there too.
        There is no next think to read a nudge, so an unmet one ends the
        attempt `blocked`, `prerequisite not done: <missing>`; nothing is
        counted, and the edits stay for the next attempt. Before this
        (stage 16 review, decided 2026-10-27) a last-step `git_commit`
        skipped its `run_tests`."""
        tool = str(call.get("tool") or "")
        if not self.prerequisites.get(tool):
            return None
        missing = self._missing(tool, args_of(call) if args_of else call.get("args"))
        return End("blocked", f"{PREREQUISITE_NOT_DONE}: {', '.join(missing)}") if missing else None

    def check_finish(self) -> Nudge | End | None:
        """A final answer in text while required steps are pending."""
        pending = self.pending()
        return self._premature("", pending) if pending else None

    def _premature(self, terminal: str, pending: list[str]) -> Nudge | End:
        self.premature += 1
        if self.premature > self.max_premature:
            return End("blocked", f"{STEPS_NOT_DONE}: {', '.join(pending)}")
        tier = min(self.premature, 3)
        return Nudge("user", step_text(terminal, pending, tier), "step", tier, tool=terminal,
                     problem=f"{terminal or 'finished'} before {', '.join(pending)}")

    def clean(self) -> None:
        """After a step whose every result was ok (forge resets both)."""
        self.premature = 0
        self.prereq_violations = 0

    def to_state(self) -> dict:
        return {"completed": list(self.completed), "ran": {k: list(v) for k, v in self.ran.items()},
                "premature": self.premature, "prereq_violations": self.prereq_violations}

    def load(self, state: Mapping | None) -> "Steps":
        if state:
            self.completed = [str(s) for s in state.get("completed") or ()]
            self.ran = {str(k): [dict(a) for a in v or ()] for k, v in (state.get("ran") or {}).items()}
            self.premature = int(state.get("premature") or 0)
            self.prereq_violations = int(state.get("prereq_violations") or 0)
        return self


def steps_for(profile, *, max_premature: int = 3, max_prereq: int = 2) -> Steps:
    """The `Steps` an agent's frontmatter asks for (`Profile.required_steps`,
    `terminal_tools`, `prerequisites`)."""
    return Steps(
        required=tuple(getattr(profile, "required_steps", ()) or ()),
        terminal=tuple(getattr(profile, "terminal_tools", ()) or ()),
        prerequisites={str(k): list(v or ()) for k, v in dict(getattr(profile, "prerequisites", {}) or {}).items()},
        max_premature=max_premature, max_prereq=max_prereq,
    )


# -- one session's guardrails -------------------------------------------------


@dataclass
class Guards:
    """What `session.py` holds per session: which guardrails are on, and
    their state.

    `validate_calls` False is `ablate = ["nudge"]`: no validation, no
    retry nudge. `count_results` False is `ablate = ["nudge"]` or
    `["recovery"]`: the tool-error budget and the refused-twice rule are
    off (under `recovery` the first failure ends the session anyway).
    `steps` None is `ablate = ["steps"]` or an agent with no step keys."""

    validate_calls: bool = True
    count_results: bool = True
    budget: ErrorBudget = field(default_factory=ErrorBudget)
    steps: Steps | None = None
    #: The tools the last think offered, which is what `validate` checks
    #: names against (the profile's, plus delegate / wait / use_skill /
    #: recall when they were added).
    offered: tuple = ()
    #: An ending a result asked for (the same call refused twice), taken
    #: at the next step boundary.
    ended: End | None = None
    #: A chat or voice session (scaffold `chat`): text is a retry only
    #: when it is nothing but a call (`looks_like_call(whole=True)`).
    conversation: bool = False

    def __post_init__(self) -> None:
        if not self.count_results:
            self.budget.max_tool_errors = 0

    def check_calls(self, calls: list[dict], schemas: Mapping | None = None,
                    *, args_of: Callable[[dict], Any] | None = None) -> Nudge | End | None:
        """At the proposal point: validation, then steps. None means
        propose them."""
        if self.validate_calls:
            verdict = validate(calls, self.offered, schemas, args_of=args_of)
            if isinstance(verdict, Nudge):
                return self.budget.retry(verdict.kind) or verdict
            self.budget.clean_proposal()
        if self.steps is not None:
            return self.steps.check(calls, args_of=args_of)
        return None

    def check_text(self, text: str) -> Nudge | End | None:
        """A text reply: a retry nudge only when it looks like a failed
        call (ADR-013). Any other text is an answer, and a clean one."""
        if not self.validate_calls:
            return None
        if looks_like_call(text, self.offered, whole=self.conversation):
            return self.budget.retry("retry") or Nudge("user", retry_text(), "retry",
                                                       problem="a reply that looked like a call did not come through")
        self.budget.clean_proposal()
        return None

    def check_last(self, call: dict, *, args_of: Callable[[dict], Any] | None = None) -> End | None:
        """The last step's one call: are its prerequisites done? Under
        `ablate = ["steps"]` nothing is checked, as before."""
        return self.steps.check_last(call, args_of=args_of) if self.steps is not None else None

    def check_finish(self) -> Nudge | End | None:
        """A final answer in text: are the required steps done?"""
        return self.steps.check_finish() if self.steps is not None else None

    def result(self, tool: str, args: Any, *, ok: bool, kind: str, key: tuple = ()) -> None:
        """One tool result, as `action.result` (or a denial) reported it."""
        if self.steps is not None:
            self.steps.record(tool, args, ok=ok, ran=ok or kind == "failed")
        # Counted either way, so a clean step still resets the step
        # counters; without `count_results` nothing here can end a session.
        ended = self.budget.result(ok, kind, key if self.count_results else ())
        if ended is not None and self.ended is None:
            self.ended = ended

    def end_step(self) -> End | None:
        """At a step boundary: an ending a result asked for, or the
        tool-error budget's. A clean step resets the step counters."""
        if self.ended is not None:
            ended, self.ended = self.ended, None
            return ended
        ended, clean = self.budget.end_step()
        if clean and self.steps is not None:
            self.steps.clean()
        return ended


__all__ = [
    "End", "ErrorBudget", "Guards", "NUDGE_KINDS", "Nudge", "Ok", "RETRY_KINDS", "Steps",
    "TOOL_CHANNEL_KINDS", "looks_like_call", "schema_problems", "steps_for", "validate",
]
