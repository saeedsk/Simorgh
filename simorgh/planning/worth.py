"""Whether Sim's OWN idea is worth a task at all (2026-10-30).

The creator, after an audit of a week of autonomous work: "fix sim's
logic to not start bogus, useless tasks". The audit's three biggest
wastes were each knowable before the task existed:

- **Work Guardian will refuse.** 14 patches proposed on Guardian's
  protected paths (`simorgh/guardian/`, `simorgh/kernel/`,
  `simorgh/contracts/`, ...). Sim's own tasks may never edit those, so each
  ran, was denied, and was proposed again -- a self-feeding denial loop
  Sim's own review measured at 10 of 11 tasks in one area.
- **Growth working on itself.** The evening of 2026-10-30 went on
  calibration and area-picking code in `simorgh/growth/` that nothing calls
  (`weakest_areas()` with no caller; a third calibration module), while
  the fixes that mattered -- mail reconnecting, a voice retry, the music
  player -- were in the household's own subsystems.
- **Projects piling up.** Five overlapping "closed-loop self-improvement"
  projects in one evening, each decomposed into up to nine nodes.

Each rule here applies only to an autonomous origin. A person's request
is never refused by this: they asked.
"""

from __future__ import annotations

#: Sim's own machinery for improving itself. An autonomous patch here is
#: growth tuning growth; `[planning] autonomous_self_growth` lets it back.
SELF_GROWTH_PREFIX = "simorgh/growth/"


def protected_hit(subject: str | None, protected: tuple[str, ...]) -> str:
    """The protected entry `subject` falls under, or "". Matched as
    Guardian's `ProtectedRule` and Execution's landing check do: a
    case-folded substring of the path."""
    path = str(subject or "").replace("\\", "/").lstrip("./").casefold()
    if not path:
        return ""
    return next((entry for entry in protected if entry and entry.casefold() in path), "")


def refusal(*, kind: str, subject: str | None, protected: tuple[str, ...], self_growth: bool) -> str:
    """Why an autonomous task of `kind` on `subject` is not worth creating,
    or "". Only code-changing work is judged: reading a protected file
    or investigating growth is harmless."""
    if kind not in ("patch", "skill"):
        return ""
    hit = protected_hit(subject, protected)
    if hit:
        return (f"{subject} is under Guardian's protected {hit!r}: Sim's own tasks may not edit it, so the "
                f"task would only be denied -- the creator edits these by hand")
    if not self_growth and str(subject or "").replace("\\", "/").lstrip("./").startswith(SELF_GROWTH_PREFIX):
        return (f"{subject} is Sim's own growth machinery; an autonomous patch there is growth tuning "
                f"itself, which the creator found produced dead code (`[planning] autonomous_self_growth`)")
    return ""


__all__ = ["SELF_GROWTH_PREFIX", "protected_hit", "refusal"]
