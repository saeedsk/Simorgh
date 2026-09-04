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

# Scope for apply_source_patch below -- existing source anywhere under
# src/, not just new skill files. Deliberately still excludes everything
# outside src/ (docs/, tests/, the repo root) -- a self-patch changes
# Simorgh's own logic, not its test suite or its constitution.
SELF_PATCH_SCOPE_PREFIX = "src/"
APPLIED_PATCH_KIND = "applied_source_patch"


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


def apply_source_patch(
    proposal: ModificationProposal,
    store: MemoryStore,
    test_summary: str,
    repo_root: Path | None = None,
) -> Path:
    """Write `proposal.code` to `proposal.subject` under `repo_root`, for
    the self-patch pipeline (src/orchestrator/self_patch.py) -- existing
    source files anywhere under SELF_PATCH_SCOPE_PREFIX, not just new
    skill files (see apply_proposal above for that narrower path).
    Independently re-checks scope and path traversal, exactly like
    apply_proposal, even though AuditGate.review() already blocked
    protected subjects before a proposal ever reaches here -- two
    boundaries, not one, same principle as apply_proposal's own docstring.

    `test_summary` is the result of running this repository's entire test
    suite against the patch in an isolated copy (see
    self_patch.run_isolated_test_suite) -- recorded alongside the change
    so the evidence that authorized this write has a permanent record,
    not just a console line that scrolled away. Raises ApplyRefused,
    writing nothing, if the subject falls outside scope.
    """
    root = (repo_root or Path.cwd()).resolve()
    subject = proposal.subject.replace("\\", "/")

    if not subject.startswith(SELF_PATCH_SCOPE_PREFIX):
        raise ApplyRefused(
            f"refusing to apply {proposal.subject!r}: outside the authorized "
            f"{SELF_PATCH_SCOPE_PREFIX!r} scope"
        )
    if ".." in Path(subject).parts:
        raise ApplyRefused(f"refusing to apply {proposal.subject!r}: path traversal")

    target = (root / subject).resolve()
    scope_root = (root / SELF_PATCH_SCOPE_PREFIX).resolve()
    if scope_root not in target.parents:
        raise ApplyRefused(
            f"refusing to apply {proposal.subject!r}: resolves outside {SELF_PATCH_SCOPE_PREFIX!r}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    already_existed = target.exists()
    target.write_text(proposal.code)

    store.remember(
        APPLIED_PATCH_KIND,
        proposal.subject,
        code=proposal.code,
        rationale=proposal.rationale,
        overwrote_existing=already_existed,
        test_summary=test_summary,
    )
    return target
