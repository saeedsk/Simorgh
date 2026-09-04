"""Proactive improvement-area discovery: turns signals already sitting in
this codebase's own memory (recurring failure patterns, individual
takeaways from reflect_on_outcome) into persisted, patchable Task objects
-- the "find improvement area" half of the creator's ask for an
autonomous agent that doesn't just react when told to.

Deliberately reuses existing signals rather than inventing a new
detector: docs/SOUL.md's "Continuous reflection" (ReflectionAgent) and
"Self-patching source code" sections already establish how Sim notices
something went wrong; this module is the missing link that turns
"noticed" into "a real, trackable, resumable unit of work" via
src/orchestrator/tasks.py, rather than a takeaway that gets printed once
and never acted on unless a human happens to type `patch` about it.
"""

from __future__ import annotations

from src.orchestrator.reflection import AGENT_SOURCE_FILES, ReflectionAgent, TAKEAWAY_KIND
from src.orchestrator.tasks import PATCH_TASK, Task, TaskStore

# Anything shorter than this in an existing task description isn't a
# meaningful enough signal to dedupe against -- avoids two genuinely
# unrelated one-word rationales looking like duplicates of each other.
_DEDUPE_MIN_OVERLAP_CHARS = 24


def discover_improvements(
    task_store: TaskStore,
    reflection_agent: ReflectionAgent,
    memory_store,
    limit: int = 5,
) -> list[Task]:
    """One discovery pass: batched-pattern proposals (ReflectionAgent's
    existing `reflect()`) plus any recent per-turn takeaway
    (`reflect_on_outcome`'s durable kind="takeaway" records) that isn't
    already covered by an unfinished task, each turned into a PATCH_TASK
    targeting the concrete file the pattern points at. Returns only the
    newly-created tasks (already added to `task_store`); `limit` bounds
    how many are created in one pass so a noisy run of failures doesn't
    flood the backlog all at once.
    """
    # Dedupe against EVERY known task, not just unfinished ones -- a
    # takeaway record can sit in the log indefinitely (only consolidation
    # prunes it), so without this, an issue already patched and marked
    # DONE would keep resurfacing as a "new" task forever.
    existing_descriptions = [t.description for t in task_store.all()]
    created: list[Task] = []

    for proposal in reflection_agent.reflect():
        if len(created) >= limit:
            break
        subject = AGENT_SOURCE_FILES.get(proposal.subject)
        if subject is None:
            continue
        if _already_covered(proposal.rationale, existing_descriptions):
            continue
        task = task_store.add(
            proposal.rationale, PATCH_TASK, subject=subject, discovered_via="reflection"
        )
        created.append(task)
        existing_descriptions.append(task.description)

    for record in memory_store.query(kind=TAKEAWAY_KIND, limit=50):
        if len(created) >= limit:
            break
        subject = AGENT_SOURCE_FILES.get(record.metadata.get("agent"))
        if subject is None:
            continue
        if _already_covered(record.content, existing_descriptions):
            continue
        task = task_store.add(record.content, PATCH_TASK, subject=subject, discovered_via="scan")
        created.append(task)
        existing_descriptions.append(task.description)

    return created


def _already_covered(candidate: str, existing_descriptions: list[str]) -> bool:
    """True if `candidate` looks like the same issue as something already
    tracked -- a plain substring check in either direction, not fuzzy
    matching, since these strings are machine-generated from a fixed set
    of templates (ReflectionAgent's own rationale text, or a takeaway's
    note), not free-form prose where near-duplicates would need something
    smarter.
    """
    if len(candidate) < _DEDUPE_MIN_OVERLAP_CHARS:
        return candidate in existing_descriptions
    return any(candidate in existing or existing in candidate for existing in existing_descriptions)
