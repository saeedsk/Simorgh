"""Applies an audited ModificationProposal to disk -- the one place in
this codebase allowed to write Simorgh's own drafted code into its real
source tree.

Per the creator's explicit, logged decision (docs/SOUL.md,
"Self-Improvement Philosophy"), a proposal that passes AuditGate.review()
now applies automatically -- no separate human "approve" step. That
autonomy is narrowly scoped, not a blanket removal of oversight:

- Only ever writes under SKILLS_DIR_PREFIX (new skill files), enforced
  here at write time, independently of the caller -- not just trusted
  because AuditGate's own protected-subject check already blocks
  soul.py/SOUL.md/audit.py from reaching this point. Two independent
  boundaries, not one.
- Only ever called after AuditGate.review() reports
  approved_by_automation=True -- the static denylist, adaptive-immunity
  memory, and sandboxed run all still ran; only the separate human-
  approval gate *on top of* those was removed, for this narrow class.
- Every apply is logged (kind="applied_skill"), forming the versioned
  lineage docs/SOUL.md already commits to. Nothing here is silent.
- Writes land as normal, uncommitted changes in the working tree --
  nothing here runs `git commit` or `git push`. The creator's own
  `git diff`/`git status` review, and the decision to commit, remain
  entirely theirs.
"""

from __future__ import annotations

from pathlib import Path

from src.memory.long_term import MemoryStore
from src.orchestrator.audit import ModificationProposal

SKILLS_DIR_PREFIX = "src/agents/skills/"
APPLIED_KIND = "applied_skill"


class ApplyRefused(Exception):
    """Raised when a proposal's subject falls outside the narrow,
    authorized apply scope. This should never happen for a proposal that
    passed AuditGate (which already blocks protected/off-scope subjects),
    but this boundary is enforced independently, not just trusted.
    """


def apply_proposal(
    proposal: ModificationProposal,
    store: MemoryStore,
    repo_root: Path | None = None,
) -> Path:
    """Write `proposal.code` to `proposal.subject` under `repo_root`
    (default: the current working directory) and log the merge. Raises
    ApplyRefused, writing nothing, if the subject isn't a plain path
    strictly inside SKILLS_DIR_PREFIX.
    """
    root = (repo_root or Path.cwd()).resolve()
    subject = proposal.subject.replace("\\", "/")

    if not subject.startswith(SKILLS_DIR_PREFIX):
        raise ApplyRefused(
            f"refusing to apply {proposal.subject!r}: outside the authorized "
            f"{SKILLS_DIR_PREFIX!r} scope"
        )
    if ".." in Path(subject).parts:
        raise ApplyRefused(f"refusing to apply {proposal.subject!r}: path traversal")

    target = (root / subject).resolve()
    scope_root = (root / SKILLS_DIR_PREFIX).resolve()
    if scope_root not in target.parents:
        raise ApplyRefused(
            f"refusing to apply {proposal.subject!r}: resolves outside {SKILLS_DIR_PREFIX!r}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    already_existed = target.exists()
    target.write_text(proposal.code)

    store.remember(
        APPLIED_KIND,
        proposal.subject,
        code=proposal.code,
        rationale=proposal.rationale,
        overwrote_existing=already_existed,
    )
    return target
