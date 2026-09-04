"""Skill-research agent: drafts ModificationProposals for AuditGate to
review.

With no real LLM provider registered, CognitionRouter falls back to
DeterministicFallbackProvider, so this agent drafts a safe, static note
about the topic (wrapped in a runnable skeleton) rather than a claim of
genuine autonomous code design -- there is no code-writing intelligence
behind it in that case, only an echo.

With a real provider registered, this agent asks for a genuine, working
implementation -- not a description -- and is honest about the same
constraints AuditGate enforces (see docs/SOUL.md's "Self-Improvement
Philosophy" and src/orchestrator/audit.py's denylist), so the model isn't
guessing at what will pass. The LLM's response is validated as syntactically
correct Python (after stripping a markdown fence, if present) before it's
ever used as code; if it isn't valid Python, this falls back to the same
safe note-wrapping template the deterministic floor uses, rather than
handing AuditGate something that can't even parse. Either way, nothing here
executes the response directly -- AuditGate's sandboxed run is what
actually runs it, exactly as before.
"""

from __future__ import annotations

import ast
import re

from src.cognition.provider import CognitionRouter
from src.orchestrator.audit import ModificationProposal

_NOTE_TEMPLATE = '''"""Drafted skill: {topic}."""


def run() -> str:
    return {content!r}


if __name__ == "__main__":
    print(run())
'''

_DRAFT_PROMPT = """Write a complete, working Python module implementing a skill for: {topic}

Constraints (code violating these will be automatically rejected before it
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
- Keep it small and focused: one clear capability, not a framework.

Output ONLY the Python code. No markdown code fences, no explanation
before or after."""

_RETRY_SUFFIX = """

Your previous attempt was rejected for: {reasons}
Write a corrected version that avoids this, following all the constraints
above. Output ONLY the corrected Python code."""


class SkillResearchAgent:
    """Turns a topic into a draft skill proposal via a CognitionRouter
    completion, ready for AuditGate.review().
    """

    def __init__(self, cognition: CognitionRouter | None = None) -> None:
        self._cognition = cognition or CognitionRouter()

    def draft_skill(
        self,
        topic: str,
        subject: str | None = None,
        prior_reasons: list[str] | None = None,
    ) -> ModificationProposal:
        """`prior_reasons`, if given, is the previous AuditGate verdict's
        rejection reasons -- used to ask for a corrected draft rather than
        repeating the same mistake. See main.py's propose_skill for the
        bounded retry loop that supplies this.
        """
        prompt = _DRAFT_PROMPT.format(topic=topic)
        if prior_reasons:
            prompt += _RETRY_SUFFIX.format(reasons="; ".join(prior_reasons))

        response = self._cognition.complete(prompt)

        if response.provider_name == "deterministic_fallback":
            code = _NOTE_TEMPLATE.format(topic=topic, content=response.text)
        else:
            candidate = _extract_code(response.text)
            code = (
                candidate
                if candidate is not None and _is_valid_python(candidate)
                else _NOTE_TEMPLATE.format(topic=topic, content=response.text)
            )

        return ModificationProposal(
            subject=subject or f"src/agents/skills/{_slugify(topic)}.py",
            code=code,
            rationale=(
                f"drafted via cognition provider {response.provider_name!r} "
                f"on topic {topic!r}"
            ),
        )


_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


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
