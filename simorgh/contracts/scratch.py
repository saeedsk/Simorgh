"""What counts as scratch, in one place.

`workspace/` is the one directory Sim's file tools may both read and
write, it is gitignored, and nothing in it is source: no test imports
it, no review sees it, and nothing there can break the suite.

Orchestration needed that fact to decide whether a written file is
disposable; Verification needs it to decide whether a change is worth
running the suite over. Neither may import the other, and neither may
reach into Execution's config, so the prefix lived as a private copy in
Orchestration and was about to acquire a second one in Verification.
Two copies of a rule is how the rule starts drifting, and this project
has paid for that before with three parallel command tables. Contracts
is stdlib-only and importable by everyone, which is exactly what a
shared fact needs.
"""

from __future__ import annotations

#: Trailing slash on purpose: `workspace-notes/x.py` is not scratch.
SCRATCH_PREFIX = "workspace/"


def is_scratch(path: str) -> bool:
    """True for a path under the scratch workspace.

    `removeprefix` rather than `lstrip("./")`, which strips a character
    SET and would turn `.dotfile/x` into `dotfile/x` -- the same shape
    as the `lstrip("notify.")` bug that quietly renamed a config key.
    """
    normalised = (path or "").strip().replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised.removeprefix("./")
    return normalised.startswith(SCRATCH_PREFIX)


__all__ = ["SCRATCH_PREFIX", "is_scratch"]
