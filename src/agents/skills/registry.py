"""Discovers and loads applied skill files under src/agents/skills/ by
name, so a skill Sim developed and applied (propose/improve) can
actually be *used* afterward -- closing the gap the creator pointed at:
"develop skill/tool... deploy them... use these changes."

Unlike a self-patch to Sim's own already-loaded core logic
(src/orchestrator/self_patch.py), a newly applied skill was never
imported into the running process in the first place -- there's nothing
stale in memory to replace, so no relaunch is needed here. Each
invocation (`build_invocation_code`) re-reads the file fresh from disk
via `load_skill_source` and runs it through the exact same sandbox every
other skill execution goes through (src/sandboxing/sandbox.py), never a
live in-process import -- consistent with the existing "arbitrary skill
code only ever runs in the sandbox" boundary, not a new one.
"""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = "src/agents/skills"

# This package's own infrastructure, never listed or loadable as a
# "skill" to use -- kept in sync by hand with what actually lives in
# src/agents/skills/ alongside drafted skills.
_EXCLUDED = {"__init__.py", "base.py", "research.py", "registry.py"}


def list_applied_skills(repo_root: Path) -> list[str]:
    """Names (without .py) of every applied skill file under
    src/agents/skills/, sorted. Empty if the directory doesn't exist yet
    (nothing applied) rather than raising.
    """
    skills_dir = repo_root / SKILLS_DIR
    if not skills_dir.is_dir():
        return []
    return sorted(p.stem for p in skills_dir.glob("*.py") if p.name not in _EXCLUDED)


def load_skill_source(repo_root: Path, name: str) -> str | None:
    """The current on-disk source of the named skill, or None if it
    doesn't exist or resolves outside the skills directory. Deliberately
    re-reads from disk on every call rather than caching -- a skill
    patched or re-proposed a moment ago should be picked up immediately,
    with no relaunch required.
    """
    target = (repo_root / SKILLS_DIR / f"{name}.py").resolve()
    scope_root = (repo_root / SKILLS_DIR).resolve()
    if scope_root not in target.parents or not target.is_file():
        return None
    return target.read_text()


def build_invocation_code(skill_source: str) -> str:
    """Wraps `skill_source` so its run() entrypoint is called exactly
    once, in a controlled way, regardless of whether the skill itself
    also defines an `if __name__ == "__main__":` guard (the deterministic
    fallback template does; a real LLM-drafted skill may or may not).
    The skill is exec'd under a namespace where __name__ is deliberately
    NOT "__main__", so any such guard inside it never fires -- this
    wrapper is the only thing that ever calls run(), so a skill is never
    accidentally run twice (once by its own guard, once by this).
    """
    return (
        "_simorgh_skill_ns = {'__name__': 'simorgh_skill'}\n"
        f"exec(compile({skill_source!r}, 'skill', 'exec'), _simorgh_skill_ns)\n"
        "if callable(_simorgh_skill_ns.get('run')):\n"
        "    print(_simorgh_skill_ns['run']())\n"
        "else:\n"
        "    print('[no run() entrypoint found in this skill]')\n"
    )
