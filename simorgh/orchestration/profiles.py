"""Per-kind Profiles (16 section 5). v1 kept its own per-agent step
ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`);
these are the same numbers, generalized to one table.
"""

from __future__ import annotations

from .api import Profile

CHAT = Profile(
    name="chat",
    # `self_map` first: a self-knowledge question ("where does your code
    # live", "what subsystems make you up") has a direct, correct answer
    # through it (world.env.query's capability_map facet) -- without it
    # the model fell back to list_dir and could wander into src/, the
    # retired v1 tree left readable for reference (observer, 2026-09-08).
    tools=("self_map", "read_file", "list_dir", "search_code", "web_search", "web_fetch",
           "render_page", "search_listings", "geocode", "run_python_sandboxed", "run_js_sandboxed",
           "propose_mcp_server"),
    read_only=False, max_steps=6, max_revisions=0, scaffold="chat", verify=False,
)
# The creator, 2026-09-07: "gives sim more freedom in autonomously
# working and evolving without too much gate". Until then the patch/
# skill profiles could only `draft_candidate` -- and the draft->verify->
# apply loop that was supposed to land a draft was never built, so Sim
# literally could not change its own code. The model may now apply and
# commit directly; Guardian still sees every call (ProtectedRule keeps
# guardian/kernel/contracts/execution/SOUL.md/simorgh.toml off-limits,
# DenylistRule still rejects raw sockets/subprocesses in drafted code),
# and `run_tests` is there so it can check itself before committing.
PATCH = Profile(
    name="patch",
    # `run_shell` is offered here and only registered by Execution when
    # `[execution] shell = true`; an unregistered tool is simply refused,
    # so the offer costs nothing when it is off.
    tools=("read_file", "list_dir", "search_code", "run_tests", "apply_source_patch",
           "git_commit", "git_revert", "git_discard", "run_shell", "render_page"),
    # 8 left no room: read, apply, run_tests, git_commit is already four
    # tool calls before a single wrong turn, and the last step is spent
    # on the forced final answer. Live-caught 2026-09-07.
    read_only=False, max_steps=20, max_revisions=2, scaffold="patch", max_output_tokens=16_000,
)
RESEARCH = Profile(
    # `run_shell` is here because "go and find out X" is exactly the
    # kind that needs it, and it had no way to count, sort or aggregate
    # anything -- a trial burned its whole budget substituting list_dir
    # (observer, 2026-09-08). Guardian gates it the same as anywhere.
    name="research",
    tools=("self_map", "read_file", "list_dir", "search_code", "web_search", "web_fetch",
           "search_listings", "geocode", "run_tests", "run_shell"),
    # 6 predates web_search/web_fetch. A question with a repo half and a
    # web half needs search + fetch + two repo steps + an answer, and
    # died on step 6 every time (observer, 2026-09-08).
    read_only=False, max_steps=14, max_revisions=0, scaffold="research", verify=True,
)
PLAN = Profile(
    name="plan", tools=("read_file", "list_dir", "search_code", "web_search", "web_fetch"),
    # `verify=False`: a plan session's product is a plan, and the task
    # verifier asks "was the change implemented?" -- to which the honest
    # answer is always no. With `max_revisions=0` that `fail` blocked the
    # session before its plan text was ever handed to Planning, so no
    # child task could exist. Found by a watched trial 2026-09-07. The
    # plan itself is reviewed downstream (`plan.proposed` -> Verification's
    # plan review), which is the right gate for it.
    read_only=True, max_steps=8, max_revisions=0, scaffold="plan", verify=False,
)
SKILL = Profile(
    name="skill",
    # `run_python_sandboxed` because `run_tests` on a brand-new skill
    # reports "no tests cover this target" -- so Sim never executed the
    # skill it had just written, and verification correctly called it
    # asserted-not-verified (observer, 2026-09-08).
    tools=("read_file", "list_dir", "search_code", "run_tests", "run_python_sandboxed",
           "apply_skill", "git_commit", "git_discard"),
    read_only=False, max_steps=20, max_revisions=2, scaffold="skill", max_output_tokens=16_000,
)

BY_KIND: dict[str, Profile] = {
    "chat": CHAT,
    "patch": PATCH,
    "research": RESEARCH,
    "project": PLAN,  # mode=plan sessions use the plan profile regardless of task kind
    "skill": SKILL,
}


def for_task(kind: str, mode: str) -> Profile:
    if mode == "plan":
        return PLAN
    return BY_KIND.get(kind, CHAT)
