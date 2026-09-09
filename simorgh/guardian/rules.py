"""The pipeline's rules, in the fixed order 09-guardian.md section 5.1
specifies. Each rule returns `Decision(kind=allow|deny|escalate|abstain,
...)`; `abstain` means "this rule has nothing to say," letting the
pipeline move on. Deny always wins (harness-01) -- the pipeline (in
`pipeline.py`) stops at the first deny and never lets a later rule
override it.
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import hashlib
import importlib.util
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
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
#
# `\.write\(` alone does not match `pathlib.Path(...).write_text(...)`
# or `.write_bytes(...)` -- "write" there is immediately followed by
# "_text("/"_bytes(", not "(". An observer proved the consequence,
# 2026-09-08: `Path("docs/SOUL.md").write_text("...")`, run through
# `run_shell`, was never flagged as a write by this regex, so
# `ProtectedRule` never added `docs/SOUL.md` to the paths it checks and
# the write landed on the real protected file. `\.write\w*\(` covers
# `.write(`, `.write_text(` and `.write_bytes(` alike.
#
# The idioms above are all "open a handle, then write to it" -- they
# miss the whole other family of one-call dataframe/array serializers
# that write a path directly with no `open(...)` anywhere in sight. An
# observer reproduced the consequence end-to-end, 2026-09-08: run
# `run_python_sandboxed`'s exact subprocess setup (empty env, temp cwd,
# `python -I`) with `pd.DataFrame(...).to_csv('/abs/path/to/protected')`
# and the target file's real content was gone -- `_looks_like_a_write`
# returned False, so `_subject_paths` never even looked at the path
# mentioned in the code, and `ProtectedRule` abstained outright. Same
# result for `np.save(...)`. Covering every such library's own save/dump
# method by name (`np.save`, `numpy.savez`, `torch.save`, `joblib.dump`,
# and pandas' `.to_<format>(` family) is the same "over-match rather
# than under-match" trade as the rest of this scan.
_WRITE_SIGNS = re.compile(
    r">>?(?!=)|\btee\b|\bcp\b|\bmv\b|\brm\b|\bsed\b.*-i\b|\bdd\b|\btruncate\b"
    r"|open\([^)]*['\"][waxWAX][+b]?['\"]"
    r"|\.write\w*\(|\.writelines\(|\.unlink\(|\.remove\(|shutil\.(move|copy|rmtree)"
    r"|os\.(remove|unlink|rename|replace)"
    r"|\.to_(csv|json|pickle|parquet|excel|feather|hdf|sql)\("
    r"|\b(np|numpy)\.save[z]?\(|\btorch\.save\(|\bjoblib\.dump\(",
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
            # Lower-cased too: the deploy filesystem (macOS/APFS default)
            # is case-insensitive but case-PRESERVING -- `DOCS/SOUL.MD`
            # and `docs/SOUL.md` are the same on-disk file, but a plain
            # substring check is case-sensitive and would not know that.
            # An observer proved the consequence, 2026-09-08: a run_shell
            # `echo ... > DOCS/SOUL.MD` was approved (the mismatched case
            # never matched `protected_subjects`'s lower-case entries)
            # and actually overwrote the real, protected docs/SOUL.md.
            # Case-folding over-matches on a case-sensitive filesystem
            # (e.g. a same-named but different-case file elsewhere in the
            # tree) -- the accepted trade this whole scan already makes
            # (over-match rather than under-match).
            canonical_lower = canonical.lower()
            path_lower = path.lower()
            for protected in ctx.config.protected_subjects:
                protected_lower = protected.lower()
                if protected in path or protected in canonical or protected_lower in path_lower or protected_lower in canonical_lower:
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


def _code_text(proposal: Proposal) -> str | None:
    """The free-form code/command payload a proposal carries, or None.
    Joins every key in `_CODE_ARG_KEYS` present rather than reading
    `code` alone: an observer proved, 2026-09-08, that `DenylistRule`
    and `ImmunityRule` both read only `proposal.args.get("code")`, so
    `run_shell`'s payload -- which arrives as `command`, not `code` --
    was invisible to either rule. A `subprocess.run(...)` (a Directive-1
    denylist hit) submitted via `run_python_sandboxed`'s `code` argument
    was denied instantly; the identical text submitted via `run_shell`'s
    `command` argument was approved and its subprocess actually ran,
    because both rules abstained before ever looking at it."""
    parts = [proposal.args.get(key) for key in _CODE_ARG_KEYS]
    texts = [p for p in parts if isinstance(p, str) and p]
    return "\n".join(texts) if texts else None


class DenylistRule:
    name = "denylist"
    layer = "denylist"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        code = _code_text(proposal)
        if code is None:
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


_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
# Per-payload memo: Guardian evaluates the same code text more than once
# in a normal flow (a proposal, its retry, a verification re-check), and
# bandit is a ~0.5s interpreter start each time.
_bandit_cache: dict[str, list[dict] | None] = {}
_BANDIT_CACHE_MAX = 256


def bandit_available() -> bool:
    return importlib.util.find_spec("bandit") is not None


def _changed_line_numbers(old: str, new: str) -> set[int]:
    """1-based line numbers in `new` that this patch inserts or rewrites
    -- the line-number twin of `_added_or_changed_lines`, for a scanner
    that reports by line rather than by text."""
    matcher = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines())
    lines: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            lines.update(range(j1 + 1, j2 + 1))
    return lines


def run_bandit(code: str, timeout_s: float) -> list[dict] | None:
    """bandit's findings for `code` as plain dicts (severity, confidence,
    line, test_id, text), or None when it could not run at all -- not
    installed, timed out, or produced no JSON. None is "no opinion", never
    "clean": the caller must abstain on it, not allow."""
    key = hashlib.sha256(code.encode("utf-8", "replace")).hexdigest()
    if key in _bandit_cache:
        return _bandit_cache[key]
    findings: list[dict] | None = None
    if bandit_available():
        with tempfile.TemporaryDirectory(prefix="simorgh-bandit-") as workdir:
            target = Path(workdir) / "payload.py"
            target.write_text(code)
            try:
                completed = subprocess.run(
                    [sys.executable, "-m", "bandit", "-f", "json", "-q", str(target)],
                    capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                )
                findings = [
                    {
                        "severity": str(r.get("issue_severity") or "").upper(),
                        "confidence": str(r.get("issue_confidence") or "").upper(),
                        "line": int(r.get("line_number") or 0),
                        "test_id": str(r.get("test_id") or ""),
                        "text": str(r.get("issue_text") or ""),
                    }
                    for r in json.loads(completed.stdout).get("results", [])
                ]
            except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError):
                findings = None
    if len(_bandit_cache) >= _BANDIT_CACHE_MAX:
        _bandit_cache.clear()
    _bandit_cache[key] = findings
    return findings


class StaticAnalysisRule:
    """bandit (PyCQA's Python security linter) over every Python code
    payload -- toolset #3 of the 2026-09-09 post-mortem. `DenylistRule`'s
    regexes are hand-maintained and catch only what someone already
    thought to write down (bare `exec(` and the `os.setuid` family were
    both missing until an observer found them the same day); bandit
    brings a maintained catalogue of ~70 checks with severities.

    Scope, deliberately narrow: only the `code` argument (a Python
    program), only when it parses as Python -- a shell `command` or a JS
    payload is not bandit's domain and abstains; a syntax error is
    `SyntaxCheck`'s to report, not this rule's. Same diff-scoping as
    `DenylistRule`: for a whole-file tool that names a `subject`, only
    findings on lines this patch inserts or rewrites count, so an
    already-reviewed `subprocess.run` elsewhere in tools/trial.py does
    not deny an unrelated docstring edit. bandit not installed, or
    failing to run, is an abstain with no reason recorded on the
    decision -- a missing optional linter must never deny, and must
    never be mistaken for a clean scan either (`run_bandit` returns
    None, not [], for exactly that distinction)."""

    name = "static_analysis"
    layer = "static_analysis"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if not ctx.config.static_analysis_enabled:
            return Decision("abstain", self.layer)
        code = proposal.args.get("code")
        if not isinstance(code, str) or not code.strip():
            return Decision("abstain", self.layer)
        try:
            ast.parse(code)
        except (SyntaxError, ValueError):
            return Decision("abstain", self.layer)
        findings = await asyncio.to_thread(run_bandit, code, ctx.config.static_analysis_timeout_s)
        if findings is None:
            return Decision("abstain", self.layer)
        changed: set[int] | None = None
        for key in _SUBJECT_ARG_KEYS:
            subject = proposal.args.get(key)
            if isinstance(subject, str) and subject:
                old_text = _existing_text(subject)
                if old_text is not None:
                    changed = _changed_line_numbers(old_text, code)
                break
        floor = _SEVERITY_RANK.get(str(ctx.config.static_analysis_min_severity).upper(), 3)
        reasons = tuple(
            f"denied: bandit {f['test_id']} ({f['severity'].lower()} severity, line {f['line']}): {f['text']}"
            for f in findings
            if _SEVERITY_RANK.get(f["severity"], 0) >= floor and (changed is None or f["line"] in changed)
        )
        if reasons:
            return Decision("deny", self.layer, reasons)
        return Decision("abstain", self.layer)


_SHELLCHECK_DANGEROUS = {
    # `rm -rf "$x/"` where $x may be empty -- the classic way a cleanup
    # script deletes the wrong tree. Every one of these is a *correctness*
    # bug shellcheck is certain about, not a style opinion.
    "SC2115",  # use "${var:?}" to ensure this never expands to /
    "SC2114",  # warning: deletes a system directory
    "SC2216",  # piping to a command that ignores stdin
    "SC2242",  # exit with an invalid status
}


def shellcheck_available() -> bool:
    return bool(shutil.which("shellcheck"))


def run_shellcheck(command: str, timeout_s: float) -> list[dict] | None:
    """shellcheck's findings for `command`, or None when it could not
    run. None is "no opinion", never "clean" -- same contract as
    `run_bandit`."""
    path = shutil.which("shellcheck")
    if not path:
        return None
    try:
        completed = subprocess.run(
            [path, "-f", "json", "-s", "bash", "-"], input=f"#!/bin/bash\n{command}\n",
            capture_output=True, text=True, timeout=timeout_s, stdin=None,
        )
        return json.loads(completed.stdout or "[]")
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError):
        return None


class ShellcheckRule:
    """shellcheck over a shell command, for the few findings that mean
    "this will destroy something you did not mean to destroy".

    Deliberately tiny in scope. shellcheck has hundreds of checks and
    most are style; denying on all of them would make `run_shell`
    unusable and teach the model to route around Guardian, which is the
    outcome this whole layer exists to prevent. Only the codes in
    `_SHELLCHECK_DANGEROUS` deny. Everything else it noticed rides along
    on an `abstain` as reasons, so the finding is visible in the trace
    without blocking the call.

    Optional, like bandit: not installed means abstain, never deny.
    """

    name = "shellcheck"
    layer = "shellcheck"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if not getattr(ctx.config, "shellcheck_enabled", True):
            return Decision("abstain", self.layer)
        command = proposal.args.get("command")
        if not isinstance(command, str) or not command.strip():
            return Decision("abstain", self.layer)
        # Checked before the thread hop, not inside it: without
        # shellcheck installed this rule has nothing to say, and paying
        # a thread switch on every shell proposal to discover that is
        # both waste and an extra scheduling point in the action path.
        if not shellcheck_available():
            return Decision("abstain", self.layer)
        findings = await asyncio.to_thread(
            run_shellcheck, command, getattr(ctx.config, "shellcheck_timeout_s", 10.0))
        if not findings:
            return Decision("abstain", self.layer)
        deny, noted = [], []
        for finding in findings:
            code = f"SC{finding.get('code')}"
            message = str(finding.get("message") or "")[:200]
            (deny if code in _SHELLCHECK_DANGEROUS else noted).append(f"shellcheck {code}: {message}")
        if deny:
            return Decision("deny", self.layer, tuple(f"denied: {r}" for r in deny))
        return Decision("abstain", self.layer, tuple(noted[:5]))


class PackageRule:
    """`install_package` may only ever install a plain package name.

    The tool checks this itself; this rule is the boundary. Two layers
    because they fail differently: an edit to the tool is a code change
    somebody reviews, while a rule denial is recorded, immune to retry,
    and visible in the trace. A URL, a local path or a VCS ref in a
    package spec is a way to run code from somewhere nobody reviewed.
    """

    name = "package"
    layer = "package"

    _BAD_SPEC = re.compile(r"://|^file:|^\.{0,2}/|^-|\.tar\.|\.whl$|^git\+", re.I)

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if proposal.tool != "install_package":
            return Decision("abstain", self.layer)
        spec = str(proposal.args.get("spec") or "").strip()
        if not spec:
            return Decision("abstain", self.layer)
        if self._BAD_SPEC.search(spec):
            return Decision("deny", self.layer, (
                f"denied: {spec!r} is not a plain package name -- a URL, path or VCS ref installs "
                "code from somewhere nobody reviewed",
            ))
        for pattern in getattr(ctx.config, "package_denylist", ()):
            if re.search(pattern, spec):
                return Decision("deny", self.layer, (f"denied: {spec!r} is on the package denylist",))
        return Decision("abstain", self.layer)


class GrantRule:
    """`grant_capability` may not be pointed at the machine.

    Mirrors `grants.py::validate_external`'s module denylist, for the
    same reason `PackageRule` mirrors its tool: the tool's check is
    usability, this one is the boundary. A grant over `os` or
    `subprocess` would hand out arbitrary execution wearing a tool's
    name -- and unlike `run_shell`, it would persist across restarts.
    """

    name = "grant"
    layer = "grant"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        if proposal.tool != "grant_capability":
            return Decision("abstain", self.layer)
        import_path = str(proposal.args.get("import_path") or "").strip()
        if import_path:
            root = import_path.split(":", 1)[0].split(".", 1)[0]
            if root in getattr(ctx.config, "grant_import_denylist", ()):
                return Decision("deny", self.layer, (
                    f"denied: a tool over {root!r} would hand out the machine, not a library",))
        command = str(proposal.args.get("command") or "").strip()
        if command and command not in ("npx", "uvx", "node", "python", "python3"):
            return Decision("deny", self.layer, (
                f"denied: {command!r} may not launch an MCP server",))
        return Decision("abstain", self.layer)


class ImmunityRule:
    name = "immunity"
    layer = "immunity"

    async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision:
        code = _code_text(proposal)
        if code is None:
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
    StaticAnalysisRule(),
    ShellcheckRule(),
    PackageRule(),
    GrantRule(),
    ImmunityRule(),
    BudgetRule(),
    ReversibilityRule(),
)
