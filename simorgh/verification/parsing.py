"""`parse_verdict` -- a verbatim port of the milestone-92 fix in
`src/orchestrator/verification.py`. Live-caught with a real provider
(Claude Code CLI): asked for "exactly one word first -- YES or NO," the
model can narrate instead ("I'll check the actual file that was
modified...") and never actually answer. The old strict "first line
must start with YES" check silently read that as NO, wrongly blocking a
change that had already passed every mechanical gate. This scans every
line for a standalone YES/NO token -- a verdict stated after some
narration still counts -- and returns `None` (not `False`) when nothing
answers: a non-answer is evidence the reviewer didn't review, never
evidence the change looks wrong (docs/blueprint/harness-04, "Non-answers
must never be silently graded as failures").
"""

from __future__ import annotations

import re
from typing import Literal

_YES_NO_RE = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)
_UNKNOWN_RE = re.compile(r"^\W*UNKNOWN\b", re.IGNORECASE)


def parse_verdict(text: str) -> Literal["yes", "no"] | None:
    """The one-word verdict the answer prompt asks for first.

    The first line that states a verdict decides, and nothing after it
    is read. Scanning on let the evidence sentence vote: "UNKNOWN\nno
    test shows it" parsed as a hard NO (2026-09-07). `UNKNOWN` -- the
    prompt's own word for "the evidence does not say" -- is None, never
    a failure. Narration before the verdict is still skipped over."""
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if _UNKNOWN_RE.search(line):
            return None
        match = _YES_NO_RE.search(line)
        if match is not None:
            return match.group(1).lower()
    return None
