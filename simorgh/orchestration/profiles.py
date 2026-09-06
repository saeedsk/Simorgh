"""Per-kind Profiles (16 section 5). v1 kept its own per-agent step
ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`);
these are the same numbers, generalized to one table.
"""

from __future__ import annotations

from .api import Profile

CHAT = Profile(
    name="chat", tools=("read_file", "list_dir", "web_fetch", "run_python_sandboxed"),
    read_only=False, max_steps=6, max_revisions=0, scaffold="chat", verify=False,
)
PATCH = Profile(
    name="patch", tools=("read_file", "list_dir", "draft_candidate"),
    read_only=False, max_steps=6, max_revisions=2, scaffold="patch",
)
RESEARCH = Profile(
    name="research", tools=("read_file", "list_dir", "web_fetch"),
    read_only=True, max_steps=6, max_revisions=0, scaffold="research", verify=True,
)
PLAN = Profile(
    name="plan", tools=("read_file", "list_dir", "web_fetch"),
    read_only=True, max_steps=8, max_revisions=0, scaffold="plan", verify=True,
)
SKILL = Profile(
    name="skill", tools=("read_file", "list_dir", "draft_candidate"),
    read_only=False, max_steps=5, max_revisions=2, scaffold="skill",
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
