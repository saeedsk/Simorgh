"""Research tasks: the "investigate before you build" half of Sim's work
harness (src/orchestrator/tasks.py, projects.py). Every other pipeline in
this codebase (propose_skill, propose_self_patch) goes straight from an
idea to a drafted code change; this is the missing middle step for an
idea that's ambitious or uncertain enough to be worth thinking through
first -- gather context, weigh it, and only spawn a real PATCH_TASK if
the investigation actually concludes something concrete and worth doing.

Modeled directly on how Claude Code's own subagents work (researched
before building this -- see docs/EVOLUTION.md for the citations): a
subagent explores in its own context window with real tools, and only
its final summary reaches the caller, keeping the noisy back-and-forth
of "read this, check that" out of everything else. `RunResearchAgent`'s
READ/LIST tool loop is that same shape, reusing the exact
parse_marker/safe_read_file/safe_list_dir machinery SelfPatchAgent and
SkillResearchAgent already share -- a research task can actually open
real files to check "does this already exist" or "how does the current
code handle this" before concluding, instead of reasoning blind from
just its own topic string. Deliberately never given DRAFT/RUN/WRITE:
this pipeline produces a written finding, never code -- it never
touches AuditGate, the sandbox, or the isolated test suite, because it
never writes anything to src/ itself.

The finding is durable (kind=RESEARCH_FINDING_KIND on the shared
MemoryStore) so a later task, or the creator directly, can read what
was concluded without re-deriving it -- the same "don't rediscover
what's already known" principle AuditGate's own adaptive-immunity
memory already relies on.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.cognition.provider import CognitionRouter
from src.cognition.tool_protocol import (
    first_line_argument,
    parse_marker,
    preview,
    safe_list_dir,
    safe_read_file,
)
from src.memory.long_term import MemoryStore
from src.orchestrator.audit import PROTECTED_SUBJECTS
from src.orchestrator.tasks import PATCH_TASK, Task, TaskStore

RESEARCH_FINDING_KIND = "research_finding"

# Same reasoning as SelfPatchAgent's own DEFAULT_MAX_TOOL_STEPS (self_patch.py):
# a research task needs real room to look around before concluding, not
# just enough for one lookup.
DEFAULT_MAX_TOOL_STEPS = 6

_RESEARCH_PROMPT = """You are Sim, investigating a question about your own
architecture or a topic worth understanding before acting on it --
this is research, not a request to write code.

Question / topic: {description}

You have two tools, used one at a time, to look around before you
conclude. To use one, make your ENTIRE response exactly one of:
READ: <repo-relative path>
  -- read a file from this codebase for context. Read-only.
LIST: <repo-relative path, or empty for the top level>
  -- list a directory's contents, if you're not sure a path exists.

When you're ready, write your finding: a short, honest conclusion --
what you'd conclude, what's uncertain, and whether this is actually
worth turning into a concrete code change. If -- and only if -- you
conclude there's a specific, well-scoped change worth making, end your
answer with exactly one line in this format:

FOLLOW-UP: <repo-relative path under src/> :: <one-line description>

Omit that line entirely if nothing concrete follows from this, if the
idea is already covered by existing code (check with READ/LIST before
assuming), or if it's still too vague to turn into one targeted patch.
Do not pad the finding to justify a follow-up that isn't warranted --
"not worth pursuing further" is a complete, useful finding on its own."""

_CONTINUE_HINT = (
    "\nContinue: use READ: <path> or LIST: <path> again, or write your finding now to finish."
)

_FINAL_TURN_HINT = (
    "\n\nThis is your last step -- no more tool calls will be honored. Write your "
    "finding now, using whatever you've already learned above (even if incomplete); "
    "do not write a READ:/LIST: marker, it will be used as your literal finding verbatim."
)

_FOLLOWUP_LINE = re.compile(r"^\s*FOLLOW-UP:\s*(\S+)\s*::\s*(.+)$", re.IGNORECASE | re.MULTILINE)


class ResearchAgent:
    """Drafts a research finding via the same bounded READ/LIST tool-loop
    shape SelfPatchAgent/SkillResearchAgent already use, seeded with
    `task.description` as the question to investigate.
    """

    def __init__(
        self,
        cognition: CognitionRouter,
        repo_root: Path | None = None,
        max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS,
        activity_log: object | None = None,
    ) -> None:
        self._cognition = cognition
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._max_tool_steps = max(1, max_tool_steps)
        self._activity_log = activity_log

    def run(self, task: Task, store: MemoryStore, task_store: TaskStore) -> str:
        """Runs one research task to completion, recording the finding and
        (only if the response names one) creating a follow-up PATCH_TASK.
        Returns a result string in the same "[VERB] ..." shape every other
        propose_*/apply_* result uses. Deterministic-fallback-safe: with
        no real provider reachable at all, returns a plain, honest string
        rather than a fabricated finding.
        """
        prompt = _RESEARCH_PROMPT.format(description=task.description)
        provider_name = "deterministic_fallback"
        final_text = ""

        for step in range(self._max_tool_steps):
            is_last_step = step == self._max_tool_steps - 1
            step_prompt = prompt + _FINAL_TURN_HINT if is_last_step else prompt
            response = self._cognition.complete(step_prompt)
            provider_name = response.provider_name
            final_text = response.text

            if provider_name == "deterministic_fallback":
                break

            kind, payload = parse_marker(response.text, ("READ", "LIST"))
            if kind == "read" and not is_last_step:
                prompt += self._read_tool_turn(payload)
                continue
            if kind == "list" and not is_last_step:
                prompt += self._list_tool_turn(payload)
                continue
            final_text = payload if kind is None else response.text
            break

        if provider_name == "deterministic_fallback" or not final_text.strip():
            return "[research] no real reviewer available -- nothing to record"

        finding = final_text.strip()
        store.remember(
            RESEARCH_FINDING_KIND,
            finding,
            task_id=task.id,
            topic=task.description,
            provider_name=provider_name,
        )

        child_note = ""
        follow_up = _FOLLOWUP_LINE.search(finding)
        if follow_up is not None:
            path, description = follow_up.group(1).strip(), follow_up.group(2).strip()
            if path.startswith("src/") and not any(p in path for p in PROTECTED_SUBJECTS):
                child = task_store.add(
                    description,
                    PATCH_TASK,
                    subject=path,
                    discovered_via="research",
                    parent_id=task.id,
                )
                child_note = f" -- spawned follow-up task {child.id} for {path}"

        return f"[RESEARCHED] {task.description}{child_note}"

    def _read_tool_turn(self, raw_path: str) -> str:
        path = first_line_argument(raw_path)
        print(f"[research] reading {preview(path)!r} for context...")
        content = safe_read_file(self._repo_root, path)
        succeeded = not content.startswith("[refused:")
        if self._activity_log is not None:
            self._activity_log.record_tool_call(
                "research", "READ", preview(path), f"{len(content)} chars", succeeded
            )
        return f"\n\n[READ {path!r} result]\n{content}\n{_CONTINUE_HINT}"

    def _list_tool_turn(self, raw_path: str) -> str:
        path = first_line_argument(raw_path)
        print(f"[research] listing {preview(path)!r}...")
        content = safe_list_dir(self._repo_root, path)
        succeeded = not content.startswith("[refused:")
        if self._activity_log is not None:
            self._activity_log.record_tool_call(
                "research", "LIST", preview(path), f"{len(content)} chars", succeeded
            )
        return f"\n\n[LIST {path!r} result]\n{content}\n{_CONTINUE_HINT}"


def run_research_task(
    cognition: CognitionRouter,
    task: Task,
    store: MemoryStore,
    task_store: TaskStore,
    repo_root: Path | None = None,
    activity_log: object | None = None,
) -> str:
    """Convenience wrapper -- constructs a one-shot ResearchAgent and runs
    it. main.py uses this directly rather than holding a persistent
    ResearchAgent instance, matching how propose_skill/propose_self_patch
    are called (a fresh agent per call is cheap; the tool loop's own state
    doesn't need to survive between tasks).
    """
    agent = ResearchAgent(cognition, repo_root=repo_root, activity_log=activity_log)
    return agent.run(task, store, task_store)
