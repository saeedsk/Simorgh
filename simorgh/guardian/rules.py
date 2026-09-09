"""The pipeline's rules, in the fixed order 09-guardian.md section 5.1
specifies. Each rule returns `Decision(kind=allow|deny|escalate|abstain,
...)`; `abstain` means "this rule has nothing to say," letting the
pipeline move on. Deny always wins (harness-01) -- the pipeline (in
`pipeline.py`) stops at the first deny and never lets a later rule
override it.
"""

from __future__ import annotations

import difflib
import posixpath
import re
from pathlib import Path

from .api import Decision, DecisionContext, Proposal

# Tools whose subject argument names a file this proposal would touch --
# used by the protected/scope rules to find "the path" in an otherwise
# tool-specific args dict without hardcoding every tool's exact schema.
_SUBJECT_ARG_KEYS = ("subject", "path")

# Guardian's own location is fixed within the checkout regardless of
# process cwd (mirrors execution/config.py's find_repo_root fallback,
# duplicated here rather than imported -- guardian deliberately depends
# on nothing but its own siblings + simorgh.contracts + stdlib, and
# execution/ is itself one of the protected subjects this package
# polices).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _existing_text(subject: str) -> str | None:
    """The on-disk content of `subject`, or None if it doesn't exist yet
    (a new file -- everything in it is "new") or can't be read as text
    (binary, unreadable, escapes the repo -- scan the whole body rather
    than silently trust a diff we can't compute)."""
    if not subject or ".." in Path(subject).parts:
        return None
    target = (_REPO_ROOT / subject).resolve()
    try:
        target.relative_to(_REPO_ROOT)
    except ValueError:
        return None
    if not target.is_file():
        return None
    try:
        return target.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _added_or_changed_lines(old: str, new: str) -> str:
    """Lines this patch introduces or rewrites, newline-joined. Ported
    files like tools/trial.py legitimately call `subprocess.run` for
    real reasons; scanning the whole new-file body on every patch to
    such a file meant DenylistRule denied even a one-line, unrelated
    docstring add with "spawns its own subprocess" -- the pattern was
    already there, untouched, and the diff never looked. Scanning only
    what changed lets an existing, already-reviewed line stay allowed
    while a genuinely new denylisted line -- inserted or edited into
    existence by this very patch -- still gets caught."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    changed: list[str] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            changed.extend(new_lines[j1:j2])
    return "\n".join(changed)


# Arguments that are a program rather than a path: whatever they name,
# they name it INSIDE their text. A rule that only reads `path`/`subject`
# abstains on these and every other rule then waves them through.
_CODE_ARG_KEYS = ("code", "command")
# A protected subject mentioned anywhere in such a program. Deliberately
# crude -- it looks for the literal name, so it over-matches a mention in
# a comment and under-matches a path assembled from pieces. Over-matching
# costs a denial the model can explain around; under-matching costs the
# whole protection model, which is the trade this makes.
_PATHISH = re.compile(r"[\w./-]+")


def _mentioned_paths(text: str) -> list[str]:
    # `tests/simorgh/execution/test_tools.py` contains the protected
    # string `simorgh/execution/` and is not a protected file: the test
    # tree is a write scope. Without this, `run_shell: pytest
    # tests/simorgh/execution/...` -- an ordinary, encouraged command --
    # would be denied as an attempt on Execution's source.
    return [t for t in _PATHISH.findall(text or "") if not t.startswith("tests/")]


# A crude sign that a `code`/`command` payload writes SOMEWHERE, not
# necessarily to the path being checked -- corroborating evidence, not
# proof, in keeping with this whole scan's "over-match rather than
# under-match" trade. Required before a mere MENTION of a protected path
# in free-form code denies the call: without this, fixing "the read_only
# early-return made the whole scan a no-op" (2026-09-08) reintroduced
# the ORIGINAL 2026-09-07 bug this rule exists to prevent -- a plain
# `cat docs/SOUL.md` (a read) was denied as if it were a write, because
# the text-match cannot otherwise tell `cat path` from `echo x > path`.
# `subject`/`path` arguments (`apply_source_patch`, `apply_skill`) need
# no such check: naming a file there always means writing it.
_WRITE_SIGNS = re.compile(
    r">>?(?!=)|\btee\b|\bcp\b|\bmv\b|\brm\b|\bsed\b.*-i\b|\bdd\b|\btruncate\b"
    r"|open\([^)]*['\"][waxWAX][+b]?['\"]"
    r"|\.write\(|\.writelines\(|\.unlink\(|\.remove\(|shutil\.(move|copy|rmtree)"
    r"|os\.(remove|unlink|rename|replace)",
)


def _looks_like_a_write(text: str) -> bool:
    return bool(_WRITE_SIGNS.search(text or ""))


def _subject_paths(proposal: Proposal) -> list[str]:
    paths = list(proposal.scope.get("paths") or [])
    for key in _SUBJECT_ARG_KEYS:
        value = proposal.args.get(key)
        if isinstance(value, str) and value not in paths:
            paths.append(value)
    # `run_python_sandboxed` and `run_shell` carry no path argument at
    # all, so `ProtectedRule` abstained on them, `reversibility` said
    # "reversible", and the guarded posture auto-allowed it. An observer
    # proved the consequence on 2026-09-08: a single approved
    # `run_python_sandboxed` call rewrote docs/SOUL.md, simorgh/guardian/
    # rules.py and simloader.py. The sandbox has rlimits and a temp cwd
    # and NO filesystem confinement, so "deliberately no repo access"
    # was never true. Until it is, Guardian has to read the program --
    # but only a program that ALSO looks like it writes something,
    # so a plain `cat`/`open(path)` read is never denied by this.
    for key in _CODE_ARG_KEYS:
        value = proposal.args.get(key)
        if isinstance(value, str) and value and _looks_like_a_write(value):
            paths.extend(t for t in _mentioned_paths(value) if t not in paths)
    return paths


class PausedRule:
    name = "paused"
    layer = "paused"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if ctx.system_state in ("paused", "stopping"):
            return Decision("deny", self.layer, (f"system is {ctx.system_state}",))
        return Decision("abstain", self.layer)


class ModeRule:
    name = "mode"
    layer = "mode"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        effective_mode = ctx.config.mode
        # Posture=locked narrows the effective mode for autonomous
        # origins only -- a human-originated proposal still gets the
        # configured mode (09 section 5.2).
        if ctx.posture.level == "locked" and proposal.origin in ctx.config.autonomous_origins:
            effective_mode = "locked"

        read_only = bool(ctx.tool and ctx.tool.read_only)

        if effective_mode == "observe":
            return Decision("deny", self.layer, ("mode=observe: nothing is auto-approved",))
        if effective_mode == "locked":
            if proposal.origin in ctx.config.autonomous_origins and not read_only:
                return Decision("deny", self.layer, ("mode=locked: autonomous non-read-only work is denied",))
            if proposal.origin not in ctx.config.autonomous_origins and not read_only:
                return Decision("deny", self.layer, ("mode=locked: only read-only actions are allowed",))
            return Decision("abstain", self.layer)
        if proposal.task_mode == "plan" and not read_only:
            return Decision("deny", self.layer, ("plan mode: only read-only tools",))
        return Decision("abstain", self.layer)


class ProtectedRule:
    name = "protected"
    layer = "protected"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        # Protection is about *editing* (09 section 5.2: protected
        # subjects are "never writable by any action"). Reading one is
        # how Sim learns the contracts it has to honour in the code it
        # *is* allowed to change. Found by a watched trial, 2026-09-07:
        # a plain `read_file` of simorgh/kernel/cli.py was denied with
        # "only the creator may edit it directly" -- nobody had asked to
        # edit it -- and the same rule was silently keeping every
        # simorgh/contracts/ schema unreadable.
        #
        # But `read_only` describes whether EXECUTION tracks a write
        # side-effect for this tool's normal outputs -- not whether its
        # payload can write to disk. `run_python_sandboxed` is declared
        # `read_only=True` and runs an arbitrary subprocess with no
        # chroot; an observer proved this exact early return made
        # today's code-payload scan (below) a COMPLETE no-op for it --
        # the tool this fix was written for, in the fix's own comment.
        # A proposal carrying a `code`/`command` argument is never
        # exempted by `read_only`, whatever the tool's own classification
        # says, because that argument is a program, and the program's
        # actions are what this rule exists to see (2026-09-08).
        if (
            ctx.tool is not None and ctx.tool.read_only
            and not any(isinstance(proposal.args.get(k), str) and proposal.args.get(k) for k in _CODE_ARG_KEYS)
        ):
            return Decision("abstain", self.layer)
        for path in _subject_paths(proposal):
            # Canonicalized before comparison: `"simorgh//guardian/rules.py"`
            # and `"simorgh/./guardian/rules.py"` resolve to the identical
            # protected file (`pathsafety`'s own `.resolve()` collapses
            # both the same way at write time) but neither literal-
            # matches `"simorgh/guardian/"` in a plain substring check.
            # A path assembled from pieces already defeats the scan
            # above; a disguised but otherwise-plain path should not
            # ALSO defeat the one check that never needed obfuscation
            # to begin with (2026-09-08).
            canonical = posixpath.normpath(path)
            for protected in ctx.config.protected_subjects:
                if protected in path or protected in canonical:
                    return Decision(
                        "deny", self.layer,
                        (f"{path!r} is protected ({protected!r}); only the creator may edit it directly",),
                    )
        return Decision("abstain", self.layer)


class ScopeRule:
    name = "scope"
    layer = "scope"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        # A full task-vs-proposal scope comparison needs task.created's
        # own `scope` (Planning, not built this phase -- 07-planning.md
        # section 12 Q1). Until that lands there is no independent task
        # scope to compare against, so this rule always abstains rather
        # than fabricate a boundary; ProtectedRule and tool-level scope
        # checks in Execution remain the real enforcement in the
        # meantime (defense in depth is still two layers, not zero).
        return Decision("abstain", self.layer)


class DenylistRule:
    name = "denylist"
    layer = "denylist"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        code = proposal.args.get("code")
        if not isinstance(code, str):
            return Decision("abstain", self.layer)
        scan_text = code
        # `run_shell`/`run_python_sandboxed` also carry `code`, but name
        # no `subject`/`path` -- there is no "existing file" to diff
        # against, so they keep scanning the whole program (as before).
        # Only a whole-file-replace tool (`apply_source_patch`,
        # `apply_skill`) both names a subject and hands over a complete
        # new body, which is what makes a same-file, unrelated-line diff
        # meaningful here.
        for key in _SUBJECT_ARG_KEYS:
            subject = proposal.args.get(key)
            if isinstance(subject, str) and subject:
                old_text = _existing_text(subject)
                if old_text is not None:
                    scan_text = _added_or_changed_lines(old_text, code)
                break
        reasons = tuple(
            f"denied: {explanation}"
            for pattern, explanation in ctx.config.denylist.items()
            if re.search(pattern, scan_text)
        )
        if reasons:
            return Decision("deny", self.layer, reasons)
        return Decision("abstain", self.layer)


class ImmunityRule:
    name = "immunity"
    layer = "immunity"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        code = proposal.args.get("code")
        if not isinstance(code, str) or not code:
            return Decision("abstain", self.layer)
        found = ctx.rejected_similarity(code)
        if found is not None:
            ratio, _ = found
            return Decision(
                "deny", self.layer,
                (f"{ratio:.0%} similar to a previously rejected proposal (adaptive immunity)",),
            )
        return Decision("abstain", self.layer)


def similarity(code: str, excerpts: list[str], threshold: float) -> tuple[float, str] | None:
    """Shared by `ImmunityRule` and `review.py`: the highest-similarity
    match at or above `threshold`, or None. Pure so it's trivially unit
    testable without a Ledger."""
    best: tuple[float, str] | None = None
    for excerpt in excerpts:
        ratio = difflib.SequenceMatcher(None, code, excerpt).ratio()
        if ratio >= threshold and (best is None or ratio > best[0]):
            best = (ratio, excerpt)
    return best


class BudgetRule:
    name = "budget"
    layer = "budget"

    # Tools whose args plausibly cause a model call (drafting); anything
    # else never checks the budget table at all -- a read_file proposal
    # is not slowed down by budget bookkeeping it has no bearing on.
    MODEL_COSTING_TOOLS = frozenset({"draft_patch", "draft_skill", "review"})

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if proposal.tool not in self.MODEL_COSTING_TOOLS:
            return Decision("abstain", self.layer)
        if not ctx.budgets:
            # No cognition.provider.status has ever arrived -- degrade
            # gracefully (09 section 8: "budget exhausted" is the only
            # failure mode named; "no data" is not the same as
            # "exhausted" and must not block on missing information).
            return Decision("abstain", self.layer)
        for status in ctx.budgets.values():
            if status.fraction_used >= 1.0:
                return Decision("deny", self.layer, (f"{status.provider} budget exhausted for this window",))
        return Decision("abstain", self.layer)


class ReversibilityRule:
    name = "reversibility"
    layer = "reversibility"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        r = proposal.reversibility
        mode = ctx.config.mode if ctx.posture.level != "locked" else "locked"
        if r == "read_only":
            return Decision("allow", self.layer)
        if r == "reversible":
            if mode == "locked":
                return Decision("deny", self.layer, ("locked: only read-only actions are allowed",))
            return Decision("allow", self.layer)
        # irreversible
        if mode == "trusted":
            return Decision("allow", self.layer)
        if mode == "locked":
            return Decision("deny", self.layer, ("locked: irreversible actions are denied",))
        if ctx.config.irreversible_requires_human:
            return Decision("escalate", self.layer, ("irreversible action requires human approval",))
        return Decision("allow", self.layer)


DEFAULT_PIPELINE: tuple = (
    PausedRule(),
    ModeRule(),
    ProtectedRule(),
    ScopeRule(),
    DenylistRule(),
    ImmunityRule(),
    BudgetRule(),
    ReversibilityRule(),
)
