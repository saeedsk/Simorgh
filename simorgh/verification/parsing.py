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


def parse_verdict(text: str) -> Literal["yes", "no"] | None:
    for line in (text or "").strip().splitlines():
        match = _YES_NO_RE.search(line.strip())
        if match is not None:
            return match.group(1).lower()
    return None
