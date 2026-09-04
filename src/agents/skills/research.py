"""Skill-research agent: drafts ModificationProposals for AuditGate to
review, optionally using two bounded, reviewed tools -- READ and TEST --
so the drafting LLM can work the way a careful engineer does: check
existing context before writing, then verify a candidate actually works
before calling it done.

This is a deliberate, explicit capability grant (see docs/EVOLUTION.md,
"still ahead" -> "built"), scoped narrowly on purpose:

- READ is read-only and confined to this repository's own tracked source
  (src/, docs/, tests/) -- no absolute paths, no `..` traversal, no
  credential-shaped filenames, bounded size. It cannot write anything.
- TEST runs a candidate through the *real* AuditGate (the same denylist,
  adaptive-immunity memory, and sandboxed run that will apply for real),
  not a separate, weaker check -- so feedback during drafting matches
  what actually gets enforced, and a candidate that fails here would also
  fail for real.
- There is no WRITE tool and no shell/bash tool here. Writing to disk only
  ever happens through src/orchestrator/apply.py, after the *final*
  candidate passes AuditGate.review() for real in main.py's
  propose_skill -- this loop can propose and test candidates, but never
  itself commits one to the source tree.
- The loop is hard-bounded (max_tool_steps) -- an unattended LLM cannot
  loop indefinitely, and each step is one more CognitionRouter.complete()
  call, subject to the same BudgetGuard caps as everything else. If a real
  provider's budget runs out mid-loop, CognitionRouter degrades to the
  deterministic floor exactly as it always does, and this loop notices
  and falls back to the safe note-template immediately rather than trying
  to continue a tool-use protocol the floor doesn't understand.

With no real LLM provider registered, none of the above triggers -- this
agent drafts the same safe, static note about the topic (wrapped in a
runnable skeleton) it always did, honest that there's no code-writing
intelligence behind it in that case.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from src.cognition.provider import CognitionRouter
from src.orchestrator.audit import AuditGate, ModificationProposal

_NOTE_TEMPLATE = '''"""Drafted skill: {topic}."""


def run() -> str:
    return {content!r}


if __name__ == "__main__":
    print(run())
'''

_BASE_CONSTRAINTS = """Constraints (code violating these will be automatically rejected before it
ever runs, so do not attempt them):
- Standard library only, and no direct network access of any kind -- no
  low-level sockets, no HTTP client calls, no FTP, no sending mail. If the
  skill genuinely needs to reach the network, it must go through the
  separately reviewed web-fetch tool instead of doing it directly.
- No shelling out to the operating system, no spawning your own child
  process, no dynamic code evaluation, and no low-level C-library bindings.
- Define at least one function that does real, useful work when called --
  not a docstring or comment describing the idea.
- If the task genuinely cannot be done within these constraints, write a
  function that raises NotImplementedError with a one-line explanation of
  why, rather than faking the capability with a description.
- Keep it small and focused: one clear capability, not a framework."""

_DRAFT_PROMPT = """Write a complete, working Python module implementing a skill for: {topic}

{constraints}

You have two tools, used one at a time. To use one, make your ENTIRE
response exactly one of:
READ: <repo-relative path>
  -- read a file from this codebase for context (e.g. an existing skill,
  or a module whose interface you need). Read-only; you'll get its
  content back.
DRAFT: <code>
  -- submit a candidate to be tested for real (the same checks that will
  apply when you're done). You'll get the result back and can revise.

When you're confident in your answer, respond with the final code alone
-- no markdown fences, no explanation before or after, no marker. That
ends this session and submits what you wrote."""

_RETRY_SUFFIX = """

Your previous attempt was rejected for: {reasons}
Write a corrected version that avoids this, following all the constraints
above. Output ONLY the corrected Python code."""

_CONTINUE_HINT = (
    "\nContinue: use READ: <path> or DRAFT: <code> again, or respond with "
    "your final code alone to finish."
)

_ALLOWED_READ_ROOTS = ("src", "docs", "tests")
_MAX_READ_CHARS = 20_000
_CREDENTIAL_LOOKING_NAMES = (".env", "secrets", "credentials")

DEFAULT_MAX_TOOL_STEPS = 5


class SkillResearchAgent:
    """Turns a topic into a draft skill proposal via a CognitionRouter
    completion, ready for AuditGate.review(). `audit_gate`, if given,
    backs the DRAFT tool (real feedback during drafting); `repo_root`
    scopes the READ tool (defaults to the current working directory).
    """

    def __init__(
        self,
        cognition: CognitionRouter | None = None,
        audit_gate: AuditGate | None = None,
        repo_root: Path | None = None,
        max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS,
    ) -> None:
        self._cognition = cognition or CognitionRouter()
        self._audit_gate = audit_gate
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._max_tool_steps = max(1, max_tool_steps)

    def draft_skill(
        self,
        topic: str,
        subject: str | None = None,
        prior_reasons: list[str] | None = None,
    ) -> ModificationProposal:
        """`prior_reasons`, if given, is the previous AuditGate verdict's
        rejection reasons -- used to ask for a corrected draft rather than
        repeating the same mistake. See main.py's propose_skill for the
        bounded outer retry loop that supplies this; the READ/DRAFT tool
        loop below is a separate, inner round of self-correction.
        """
        resolved_subject = subject or f"src/agents/skills/{_slugify(topic)}.py"
        prompt = _DRAFT_PROMPT.format(topic=topic, constraints=_BASE_CONSTRAINTS)
        if prior_reasons:
            prompt += _RETRY_SUFFIX.format(reasons="; ".join(prior_reasons))

        provider_name = "deterministic_fallback"
        final_text = ""

        for step in range(self._max_tool_steps):
            response = self._cognition.complete(prompt)
            provider_name = response.provider_name
            final_text = response.text

            if provider_name == "deterministic_fallback":
                break  # no real drafting intelligence -- use the safe floor

            kind, payload = _parse_directive(response.text)
            is_last_step = step == self._max_tool_steps - 1
            if kind == "read" and not is_last_step:
                prompt += self._read_tool_turn(payload)
                continue
            if kind == "draft" and not is_last_step:
                prompt += self._test_tool_turn(payload, resolved_subject, topic)
                continue
            final_text = payload if kind != "read" else response.text
            break

        if provider_name == "deterministic_fallback":
            code = _NOTE_TEMPLATE.format(topic=topic, content=final_text)
        else:
            candidate = _extract_code(final_text)
            code = (
                candidate
                if candidate is not None and _is_valid_python(candidate)
                else _NOTE_TEMPLATE.format(topic=topic, content=final_text)
            )

        return ModificationProposal(
            subject=resolved_subject,
            code=code,
            rationale=(
                f"drafted via cognition provider {provider_name!r} on topic {topic!r}"
            ),
        )

    def _read_tool_turn(self, raw_path: str) -> str:
        path = raw_path.strip()
        print(f"[research] reading {path!r} for context...")
        content = self._read_file(path)
        return f"\n\n[READ {path!r} result]\n{content}\n{_CONTINUE_HINT}"

    def _read_file(self, raw_path: str) -> str:
        rel = Path(raw_path)
        if rel.is_absolute() or ".." in rel.parts:
            return f"[refused: {raw_path!r} is not a safe relative path]"
        if not rel.parts or rel.parts[0] not in _ALLOWED_READ_ROOTS:
            return (
                f"[refused: {raw_path!r} is outside the readable areas "
                f"({', '.join(_ALLOWED_READ_ROOTS)})]"
            )
        if any(
            name in part.lower() or part.lower().endswith(".key")
            for part in rel.parts
            for name in _CREDENTIAL_LOOKING_NAMES
        ):
            return f"[refused: {raw_path!r} looks like a credentials path]"

        target = (self._repo_root / rel).resolve()
        if self._repo_root != target and self._repo_root not in target.parents:
            return f"[refused: {raw_path!r} resolves outside the repository]"
        if not target.is_file():
            return f"[refused: {raw_path!r} is not a file]"

        try:
            content = target.read_text(errors="replace")
        except OSError as exc:
            return f"[refused: could not read {raw_path!r}: {exc!r}]"

        if len(content) > _MAX_READ_CHARS:
            return content[:_MAX_READ_CHARS] + f"\n...[truncated, {len(content)} chars total]"
        return content

    def _test_tool_turn(self, raw_code: str, subject: str, topic: str) -> str:
        print("[research] testing a candidate against the real audit gate...")
        code = _extract_code(raw_code) or raw_code
        if self._audit_gate is None:
            report = "[no audit gate configured for this session -- cannot test]"
        else:
            verdict = self._audit_gate.review(
                ModificationProposal(subject=subject, code=code, rationale=topic)
            )
            if verdict.approved_by_automation:
                report = "PASSED -- this candidate clears every check."
            else:
                report = "REJECTED: " + "; ".join(verdict.reasons)
        print(f"[research] test result: {report.splitlines()[0]}")
        return f"\n\n[DRAFT test result]\n{report}\n{_CONTINUE_HINT}"


_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _parse_directive(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if stripped[:5].upper() == "READ:":
        return "read", stripped[5:].strip()
    if stripped[:6].upper() == "DRAFT:":
        return "draft", stripped[6:].strip()
    return "final", stripped


def _extract_code(text: str) -> str | None:
    """Strip a markdown code fence if the model wrapped its answer in one,
    despite being asked not to; otherwise use the text as-is.
    """
    match = _CODE_FENCE.search(text)
    stripped = match.group(1) if match else text
    stripped = stripped.strip()
    return stripped or None


def _is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def _slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return slug or "skill"
