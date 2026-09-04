"""Self-patching pipeline: lets Simorgh propose a change to its own
EXISTING source (not just a brand-new skill file under
src/agents/skills/), and -- if the change survives the full existing
audit gate, a fresh copy of this repository's entire test suite run in
isolation, and (for src/main.py specifically) one extra structural check
-- apply it and relaunch the process so the new code actually takes
effect.

This is the direct answer to two things the creator raised back to back
in one live transcript: Sim correctly refused a chat request to weaken
its own safety boundaries ("as your creator I allow you" typed into a
prompt is not the creator editing the repository -- see docs/SOUL.md,
"On changing this hierarchy") but then also had no way to land a
genuine, safe improvement to its own logic when one was warranted, or to
make an applied change take effect without the creator manually
restarting it. Both halves matter, and neither moved the other:

- The boundary stays exactly where it was. A self-patch still goes
  through AuditGate.review() -- the same denylist, adaptive-immunity
  memory, and sandboxed run a drafted skill goes through -- and
  audit.py's _PROTECTED_SUBJECTS now additionally covers apply.py and
  this file, so a self-patch can never touch the code that enforces
  self-patches. The network denylist is unconditional in AuditGate, not
  scoped by file location, so this pipeline cannot be used to add
  network access anywhere either, including to itself.
- What's new is scope (existing files anywhere under src/, not only new
  skill files) and a much stronger gate to earn that scope: this
  repository's entire test suite, not just a denylist and a smoke run,
  has to still pass -- with at least as many tests as before, so a patch
  can't dodge a failure by deleting or skipping the test that would have
  caught it.
- This pipeline is invoked from a literal CLI command
  ('patch <path> <description>', see src/main.py) that a human operator
  types, from the idle-triggered autonomous loop
  (src/orchestrator/autonomy.py), or -- since the creator separately and
  explicitly authorized it, see docs/SOUL.md, "Conversational
  Self-Modification" -- from LogicAgent's own PATCH tool marker, when a
  chat message clearly calls for it. All three call this exact same
  function; there is no separate, looser path for the conversational
  trigger. What none of the three can do is unlock anything *beyond*
  what this pipeline already permits -- a chat message claiming creator
  authority still cannot remove the network denylist or touch a
  protected file, the same property SOUL.md already establishes for
  changing the directive hierarchy.

Same auto-apply posture as skills (docs/SOUL.md, "Self-Improvement
Philosophy"): a patch that clears every one of these checks applies and
relaunches immediately, no separate human-approval step -- the creator's
already-logged policy doesn't distinguish "narrow" self-modification
classes by how impactful they are, it distinguishes them by whether they
passed real, layered review. This class's review is strictly stronger
than the skills class's, not weaker.

Known limitation (see docs/EVOLUTION.md): check_main_py_invariants below
is a narrow, cheap substring check, not a real static-invariant prover.
It catches a patch that obviously deletes or routes around the safety
wiring in main.py; a sufficiently deliberate rewrite could still evade
it. Flagged here rather than presented as a stronger guarantee than it
is.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.cognition.provider import CognitionRouter
from src.cognition.tool_protocol import (
    extract_code,
    is_valid_python,
    parse_marker,
    preview,
    safe_read_file,
)
from src.orchestrator.audit import AuditGate, ModificationProposal
from src.orchestrator.console_style import format_code_block

DEFAULT_MAX_TOOL_STEPS = 4
DEFAULT_SUITE_TIMEOUT_SECONDS = 180.0

# Must never reach a subprocess running this repo's own test suite --
# defense in depth against a test accidentally making a real, billed LLM
# call instead of using the fakes every test in this suite is written to
# use.
_CREDENTIAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)

_IGNORE_FOR_COPY = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache")

_RUN_REGEX = re.compile(r"Ran (\d+) tests?")

_MAIN_PY_REQUIRED_SUBSTRINGS = ("AuditGate(", "audit_gate.review(", "apply_proposal(")


@dataclass(frozen=True)
class SuiteRunResult:
    passed: bool
    exit_code: int
    test_count: int
    baseline_test_count: int
    summary: str


def run_isolated_test_suite(
    repo_root: Path,
    subject: str,
    new_content: str,
    timeout: float = DEFAULT_SUITE_TIMEOUT_SECONDS,
    runner: Callable[[Path, float], subprocess.CompletedProcess] | None = None,
) -> SuiteRunResult:
    """Copy `repo_root` to an isolated temp directory, write
    `new_content` to `subject` inside the copy, and run this repository's
    entire test suite there twice -- once unpatched (baseline), once
    patched -- so a patch is judged against "did anything regress,"
    not just "did the patched run happen to exit 0." Never touches the
    real repository; the copy is discarded when this returns.
    """
    run = runner or _run_suite_subprocess
    with tempfile.TemporaryDirectory(prefix="simorgh-selftest-") as tmp:
        copy_root = Path(tmp) / "repo"
        shutil.copytree(repo_root, copy_root, ignore=_IGNORE_FOR_COPY)

        baseline = run(copy_root, timeout)
        baseline_count = _parse_test_count(baseline)

        target = (copy_root / subject).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content)

        patched = run(copy_root, timeout)
        patched_count = _parse_test_count(patched)

        passed = patched.returncode == 0 and patched_count >= baseline_count and patched_count > 0
        summary = (
            f"baseline: {baseline_count} tests ({'OK' if baseline.returncode == 0 else 'FAILED'}); "
            f"patched: {patched_count} tests ({'OK' if patched.returncode == 0 else 'FAILED'})"
        )
        if not passed:
            tail = (patched.stderr or "")[-2000:]
            summary += f"\n{tail}"

        return SuiteRunResult(
            passed=passed,
            exit_code=patched.returncode,
            test_count=patched_count,
            baseline_test_count=baseline_count,
            summary=summary,
        )


def _run_suite_subprocess(repo_copy: Path, timeout: float) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in _CREDENTIAL_ENV_VARS}
    try:
        return subprocess.run(
            [sys.executable, "-m", "unittest", "discover"],
            cwd=repo_copy,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=-1,
            stdout=(exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout) or "",
            stderr=f"timed out after {timeout}s",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(args=[], returncode=-1, stdout="", stderr=repr(exc))


def _parse_test_count(result: subprocess.CompletedProcess) -> int:
    match = _RUN_REGEX.search(result.stderr or "") or _RUN_REGEX.search(result.stdout or "")
    return int(match.group(1)) if match else 0


def check_main_py_invariants(new_content: str) -> str | None:
    """For a patch targeting src/main.py specifically: refuse it (before
    it ever reaches the much more expensive full test-suite gate) if the
    new content no longer visibly wires the audit gate and apply
    pipeline together. See this module's docstring for the honest limits
    of this check.
    """
    missing = [s for s in _MAIN_PY_REQUIRED_SUBSTRINGS if s not in new_content]
    if missing:
        return (
            "refusing: the new src/main.py no longer visibly wires "
            f"{', '.join(missing)} -- this looks like it would weaken or "
            "remove the self-modification safety pipeline rather than "
            "improve something else about the CLI"
        )
    return None


@dataclass(frozen=True)
class RelaunchResult:
    succeeded: bool
    detail: str


DEFAULT_SELF_CHECK_TIMEOUT_SECONDS = 20.0


def relaunch(
    exec_func: Callable[[str, list[str]], None] | None = None,
    check_runner: Callable[..., subprocess.CompletedProcess] | None = None,
    timeout: float = DEFAULT_SELF_CHECK_TIMEOUT_SECONDS,
) -> RelaunchResult:
    """Verify the new code actually starts before replacing this process
    with it. `os.execv` replaces the running process image outright --
    if the patched code has a bug that only shows up at import/startup
    time (something the test suite didn't happen to exercise), there is
    no "after" for this process to notice and recover from; it's just
    gone, replaced by something that immediately crashes.

    So this first spawns a short-lived `--self-check` subprocess (see
    src/main.py) that imports everything and constructs the core objects
    without entering the interactive loop, and only execs for real if
    that exits 0. On that success path this never returns (`os.execv`
    replaces the process); on failure it returns
    `RelaunchResult(succeeded=False, ...)` so the caller can roll the
    just-applied commit back (src/orchestrator/git_ops.py,
    revert_last_commit) instead of leaving a broken, uncommitted-feeling
    state. `exec_func`/`check_runner` are injectable for tests -- nothing
    in the real test suite actually re-execs itself or trusts a
    self-check it didn't script.
    """
    run_check = check_runner or subprocess.run
    check_argv = [sys.executable, *sys.argv, "--self-check"]
    try:
        result = run_check(check_argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return RelaunchResult(False, f"self-check timed out after {timeout}s")
    except OSError as exc:
        return RelaunchResult(False, f"self-check failed to run: {exc!r}")

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return RelaunchResult(False, f"self-check failed (exit {result.returncode}): {detail}")

    do_exec = exec_func or os.execv
    sys.stdout.flush()
    do_exec(sys.executable, [sys.executable] + sys.argv)
    return RelaunchResult(True, "")  # unreachable on a real execv; reachable only for a test stub


_PATCH_DRAFT_PROMPT = """You are revising your own existing source file at: {subject}

Reason for this patch: {topic}

Current content of {subject}:
---
{current_content}
---

Write the COMPLETE new content of this file (not a diff, not just the
changed lines) -- the full file, ready to replace the current one.

Constraints (violating these gets the patch automatically rejected, so
do not attempt them):
- Standard library only, no direct network access of any kind (no raw
  sockets, no HTTP client calls, no FTP, no mail) -- go through the
  reviewed web-fetch tool if network access is genuinely needed.
- No shelling out, no spawning your own subprocess, no dynamic code
  evaluation, no low-level C-library bindings.
- Preserve behavior you weren't asked to change -- this is a targeted
  improvement, not a rewrite. If in doubt, change less.
- The file must remain valid, importable Python.

You have two tools, used one at a time. To use one, make your ENTIRE
response exactly one of:
READ: <repo-relative path>
  -- read another file from this codebase for context (e.g. a module
  this file calls into). Read-only.
DRAFT: <code>
  -- submit a candidate for a quick check (denylist, adaptive-immunity
  memory, a sandboxed smoke run of the file's own top level -- NOT the
  full test suite yet, that runs once at the very end on your final
  answer). You'll get the result back and can revise.

When you're confident in your answer, respond with the final file
content alone -- no markdown fences, no explanation before or after, no
marker. That ends this session and submits what you wrote."""

_RETRY_SUFFIX = """

Your previous attempt was rejected for: {reasons}
Write a corrected version of the COMPLETE file that avoids this, still
following every constraint above. Output ONLY the corrected file
content."""

_CONTINUE_HINT = (
    "\nContinue: use READ: <path> or DRAFT: <code> again, or respond with "
    "your final file content alone to finish."
)


class SelfPatchAgent:
    """Drafts a ModificationProposal that replaces the full content of an
    EXISTING source file, via the same READ/DRAFT tool loop pattern as
    SkillResearchAgent (src/agents/skills/research.py), seeded with the
    file's current content so the model is patching, not guessing.
    """

    def __init__(
        self,
        cognition: CognitionRouter,
        audit_gate: AuditGate | None = None,
        repo_root: Path | None = None,
        max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS,
        activity_log: object | None = None,
    ) -> None:
        self._cognition = cognition
        self._audit_gate = audit_gate
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._max_tool_steps = max(1, max_tool_steps)
        self._activity_log = activity_log

    def draft_patch(
        self, subject: str, topic: str, prior_reasons: list[str] | None = None
    ) -> ModificationProposal | None:
        """Returns None if no real drafting intelligence was available or
        the model never produced valid Python -- callers must not apply a
        "patch" that's secretly just the unchanged original file.
        """
        current_content = safe_read_file(self._repo_root, subject)
        prompt = _PATCH_DRAFT_PROMPT.format(
            subject=subject, topic=topic, current_content=current_content
        )
        if prior_reasons:
            prompt += _RETRY_SUFFIX.format(reasons="; ".join(prior_reasons))

        provider_name = "deterministic_fallback"
        final_text = ""

        for step in range(self._max_tool_steps):
            response = self._cognition.complete(prompt)
            provider_name = response.provider_name
            final_text = response.text

            if provider_name == "deterministic_fallback":
                break

            kind, payload = parse_marker(response.text, ("READ", "DRAFT"))
            is_last_step = step == self._max_tool_steps - 1
            if kind == "read" and not is_last_step:
                prompt += self._read_tool_turn(payload)
                continue
            if kind == "draft" and not is_last_step:
                prompt += self._test_tool_turn(payload, subject, topic)
                continue
            final_text = payload if kind != "read" else response.text
            break

        if provider_name == "deterministic_fallback":
            return None

        candidate = extract_code(final_text)
        if candidate is None or not is_valid_python(candidate):
            return None

        return ModificationProposal(
            subject=subject,
            code=candidate,
            rationale=f"self-patch via cognition provider {provider_name!r}: {topic!r}",
        )

    def _read_tool_turn(self, raw_path: str) -> str:
        path = raw_path.strip()
        print(f"[patch] reading {preview(path)!r} for context...")
        content = safe_read_file(self._repo_root, path)
        if self._activity_log is not None:
            self._activity_log.record_tool_call(
                "self_patch", "READ", preview(path), f"{len(content)} chars", True
            )
        return f"\n\n[READ {path!r} result]\n{content}\n{_CONTINUE_HINT}"

    def _test_tool_turn(self, raw_code: str, subject: str, topic: str) -> str:
        code = extract_code(raw_code) or raw_code
        print(format_code_block(code, label="quick-check candidate"))
        if self._audit_gate is None:
            report = "[no audit gate configured for this session -- cannot test]"
            succeeded = False
        else:
            verdict = self._audit_gate.review(
                ModificationProposal(subject=subject, code=code, rationale=topic)
            )
            succeeded = verdict.approved_by_automation
            report = (
                "PASSED the quick check -- full test suite still runs at the end."
                if succeeded
                else "REJECTED: " + "; ".join(verdict.reasons)
            )
        print(f"[patch] quick-check result: {preview(report.splitlines()[0])}")
        if self._activity_log is not None:
            self._activity_log.record_tool_call(
                "self_patch", "DRAFT", subject, preview(report.splitlines()[0]), succeeded
            )
        return f"\n\n[DRAFT test result]\n{report}\n{_CONTINUE_HINT}"
