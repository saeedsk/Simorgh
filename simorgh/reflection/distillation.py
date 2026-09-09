"""Turning a solved problem into a skill, without being asked.

Sim can already write skills, and does when a human asks. What it never
did was notice that it had just *worked something out* -- a chain of
tool calls that got real data, checked it, and produced an answer --
and that the same chain will be needed again next week. The 95120 task
is the example: search listings, filter them, build a page, verify it.
Solved twice on 2026-09-09, from scratch both times.

This decides when a finished task is worth distilling. It is
deliberately conservative, because the failure mode of being eager is
a skills directory full of near-duplicates nobody trusts:

- The task has to have **succeeded**, and be the kind whose product is
  work rather than conversation.
- It has to have used **several distinct tools**, at least one of them
  a tool that reaches outside this repo. A three-step read/edit/commit
  is what `patch` already does; there is no skill in it.
- It must not be a **repeat** of a skill that already exists.

The decision is a pure function of the task's own record, so it is
testable without a Kernel, and the caller (`reflection/service.py`)
only has to say yes to what it returns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Tools that mean the task reached beyond this repository -- fetched
# data, ran a real browser, used a granted capability. A task built
# only from read/search/edit/commit is ordinary work, not a technique.
REACHING_TOOLS = frozenset({
    "search_listings", "web_fetch", "web_search", "geocode", "render_page", "browse_page",
    "run_container", "run_script", "find_package", "install_package",
})
# Task kinds whose product is work worth repeating.
DISTILLABLE_KINDS = frozenset({"patch", "research"})
_MIN_DISTINCT_TOOLS = 3
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "with", "that", "this", "from", "into", "using",
    "make", "build", "create", "write", "add", "get", "find", "show", "please", "some",
})


@dataclass(frozen=True)
class Candidate:
    slug: str
    description: str
    tools: tuple[str, ...]


def _reaching(tools: set[str]) -> set[str]:
    return {t for t in tools if t in REACHING_TOOLS or t.startswith(("x_", "mcp_"))}


def slug_for(description: str, existing: set[str] = frozenset()) -> str:
    """A short, readable module name from the task's own words.

    Identifiers -- a ZIP, a version, a year -- are kept even when they
    come late in the sentence, because they are usually the most
    distinguishing thing in it. Taking the first four words alone named
    the 95120 task `page_real_sale_listings`, which describes half the
    tasks anyone would ever ask for. A collision gets a numeric suffix
    rather than silently overwriting a skill that already works.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", (description or "").lower())
             if w not in _STOPWORDS and len(w) > 2]
    identifiers = [w for w in words if any(c.isdigit() for c in w)]
    plain = [w for w in words if w not in identifiers]
    chosen = plain[:3] + identifiers[:1] if identifiers else plain[:4]
    base = "_".join(chosen) or "distilled_skill"
    if base not in existing:
        return base
    for n in range(2, 100):
        if f"{base}_{n}" not in existing:
            return f"{base}_{n}"
    return f"{base}_x"


def candidate_for(*, kind: str, succeeded: bool, description: str, tools: list[str] | set[str],
                  existing_skills: set[str] = frozenset()) -> Candidate | None:
    """The skill this task is worth turning into, or None.

    None is the common answer and should be: most tasks are ordinary
    work.
    """
    if not succeeded or kind not in DISTILLABLE_KINDS:
        return None
    used = {t for t in (tools or []) if t}
    if len(used) < _MIN_DISTINCT_TOOLS:
        return None
    reaching = _reaching(used)
    if not reaching:
        return None
    slug = slug_for(description, existing_skills)
    ordered = tuple(sorted(used))
    detail = (
        f"Write a skill `{slug}(...)` that repeats what this task worked out, so it does not have "
        f"to be worked out again.\n\nThe task was: {' '.join((description or '').split())[:400]}\n\n"
        f"It was solved using these tools: {', '.join(ordered)}. The skill should take the parts "
        "that would change next time as arguments (a location, a query, a path) and return the "
        "result rather than printing it. Do not hard-code anything specific to this one run."
    )
    return Candidate(slug=slug, description=detail, tools=ordered)
