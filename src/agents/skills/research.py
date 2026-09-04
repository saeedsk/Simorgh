"""Skill-research agent: drafts ModificationProposals for AuditGate to
review.

With no real LLM provider registered, CognitionRouter falls back to
DeterministicFallbackProvider, so what this agent drafts today is
necessarily minimal and safe -- a literal echo of the topic, wrapped in a
runnable skeleton -- not a claim of genuine autonomous code design. The
point of building this now is the *pipeline*: a topic in, a drafted
proposal out, ready for AuditGate.review(). Once a real provider is
registered ahead of the fallback (src/cognition/provider.py), this same
agent produces substantively richer proposals without changing at all --
`complete()`'s output is always embedded as a Python string literal via
`repr`, never executed as-is, so this stays safe to sandbox regardless of
which provider produced it.
"""

from __future__ import annotations

import re

from src.cognition.provider import CognitionRouter
from src.orchestrator.audit import ModificationProposal

_SKILL_TEMPLATE = '''"""Drafted skill: {topic}."""


def run() -> str:
    return {content!r}


if __name__ == "__main__":
    print(run())
'''


class SkillResearchAgent:
    """Turns a topic into a draft skill proposal via a CognitionRouter
    completion, ready for AuditGate.review().
    """

    def __init__(self, cognition: CognitionRouter | None = None) -> None:
        self._cognition = cognition or CognitionRouter()

    def draft_skill(self, topic: str, subject: str | None = None) -> ModificationProposal:
        response = self._cognition.complete(
            f"Draft a short, safe, self-contained note about: {topic}"
        )
        code = _SKILL_TEMPLATE.format(topic=topic, content=response.text)
        return ModificationProposal(
            subject=subject or f"src/agents/skills/{_slugify(topic)}.py",
            code=code,
            rationale=(
                f"drafted via cognition provider {response.provider_name!r} "
                f"on topic {topic!r}"
            ),
        )


def _slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return slug or "skill"
