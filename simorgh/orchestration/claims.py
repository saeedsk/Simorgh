"""Check what a final answer CLAIMS against what the session DID.

The existing guard (`_transcript_echo`) catches a reply that fabricates
in our own syntax -- `[tool_call ...]`, `[result]` -- because that
syntax came from a stand-in we put in the transcript ourselves. It is
worth keeping and it is narrow. A model that writes plain prose passes
it completely:

    "I've added the docstring and committed the change as a3f19c2."

Nothing in that sentence is bracketed, and on 2026-09-08 a session
produced exactly it with no `git_commit` step in its log at all. The
task was recorded completed, and the cleanup then deleted the real,
tested patch: silent loss on top of a false success.

The check is deliberately asymmetric. Every rule looks for a *specific
first-person past-tense claim* about an *action this session's profile
could actually have taken*, and fires only when no matching step
succeeded. That shape matters:

- Only the profile's own tools are checked. A research session saying
  "the tests pass" is reporting what it read, not claiming it ran them,
  and it has no `run_tests` to have run.
- Only the past tense counts. "I will commit this" and "you should run
  the tests" are not claims about what happened.
- A step that ran and FAILED still counts as having happened. This
  looks for invention, not for success; a model saying it committed
  when the commit was refused is wrong in a way verification already
  handles, and double-punishing it here would cost an attempt.

False negatives are fine. A false positive throws away real work, so
every rule here is one a careful reader would agree with.
"""

from __future__ import annotations

import re
from typing import Iterable

# (why it matters, the tools that would substantiate it, the phrasings
# that make the claim). The patterns are first-person and past-tense on
# purpose -- see the module docstring.
_RULES: tuple[tuple[str, tuple[str, ...], tuple[re.Pattern, ...]], ...] = (
    (
        "says it committed, and no commit was made",
        ("git_commit",),
        (
            re.compile(r"\b(?:i|we)(?:'ve| have)?\s+(?:then\s+)?committed\b", re.I),
            re.compile(r"\bcommitted\s+(?:it|the|this|these|my|those)\b", re.I),
            # "...was committed by someone" is an attribution, not a claim.
            re.compile(r"\bthe\s+(?:change|edit|patch|fix|work)\s+(?:is|was|has been)\s+committed\b(?!\s+by\b)", re.I),
            re.compile(r"\bcommit(?:ted)?\s+(?:hash|sha)\b", re.I),
        ),
    ),
    (
        "says it ran the tests, and no test run happened",
        ("run_tests",),
        (
            re.compile(r"\b(?:i|we)(?:'ve| have)?\s+(?:then\s+)?ran\s+the\s+(?:tests?|suite)\b", re.I),
            re.compile(r"\b(?:i|we)(?:'ve| have)?\s+(?:then\s+)?run\s+the\s+(?:tests?|suite)\b", re.I),
            re.compile(r"\b(?:tests?|suite)\s+(?:all\s+)?(?:pass|passed|passes)\b", re.I),
            re.compile(r"\ball\s+tests?\s+(?:are\s+)?green\b", re.I),
        ),
    ),
    (
        "says it changed a file, and no edit was applied",
        ("apply_source_patch", "apply_skill"),
        (
            re.compile(r"\b(?:i|we)(?:'ve| have)?\s+(?:then\s+)?(?:added|updated|edited|modified|changed|written|wrote|created|implemented|fixed)\b", re.I),
            # No passive form here on purpose. "the docstring was added"
            # is just as often a description of somebody else's commit
            # from 2024 as a claim about this session, and there is no
            # way to tell them apart from the sentence. A missed
            # fabrication costs nothing; a false positive throws away a
            # real attempt's work.
        ),
    ),
)


def _tools_used(steps: Iterable) -> set[str]:
    """Every tool this session actually invoked, successful or not."""
    return {step.tool for step in steps if getattr(step, "tool", None)}


def unsupported_claims(text: str, steps: Iterable, offered_tools: Iterable[str]) -> list[str]:
    """Claims in `text` that the step log does not support.

    `offered_tools` scopes the check to what this session could have
    done -- a profile without `git_commit` cannot be accused of
    inventing one.
    """
    if not (text or "").strip():
        return []
    used, offered = _tools_used(steps), set(offered_tools or ())
    found: list[str] = []
    for why, tools, patterns in _RULES:
        if not offered.intersection(tools) or used.intersection(tools):
            continue
        if any(pattern.search(text) for pattern in patterns):
            found.append(why)
    return found


__all__ = ["unsupported_claims"]
