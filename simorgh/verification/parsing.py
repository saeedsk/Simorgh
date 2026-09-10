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
#: A lowercase `no` immediately followed by another word is English's
#: determiner, not a verdict: "no test output is shown", "no clear
#: signal", "there is no way to tell". Read as a verdict it turned an
#: admission of uncertainty into a hard NO, and in one observed case
#: overruled a stated YES on the next line: "Hmm, no clear signal.\nYES
#: it does address the task." parsed as `no` (observer, 2026-09-10).
#: This is the same failure the docstring below says this function
#: exists to prevent, one level further down.
_DETERMINER_NO = re.compile(r"\bno\s+\w")
_UNKNOWN_RE = re.compile(r"^\W*UNKNOWN\b", re.IGNORECASE)
#: The verdict the prompt asks for is SHOUTED -- `YES` or `NO`, caps.
#: The guard above compared the MATCHED TEXT to the lowercase literal
#: `"no"`, so it only ever ran on an all-lowercase `no`, and an ordinary
#: English sentence capitalises its first word. "The diff shows No
#: changes to the file.\nYES the docstring exists" took the guard's
#: branch never and parsed as a hard NO, overruling the stated YES --
#: the same failure the guard was added for, one spelling over
#: (observer, 2026-09-10). All-caps is still read as a verdict wherever
#: it sits; any other casing gets the determiner test.
#:
#: And a determiner OPENING a line was exempt, which is where a
#: reviewer's throat-clearing usually sits ("No clear signal.").
#: Exempting it is only safe while nothing else in the answer states a
#: verdict: when the answer DOES shout one somewhere, that is the
#: verdict, and a sentence-case `No ...` before it is prose.
_SHOUTED = re.compile(r"\b(?:YES|NO)\b")


def parse_verdict(text: str) -> Literal["yes", "no"] | None:
    """The one-word verdict the answer prompt asks for first.

    The first line that states a verdict decides, and nothing after it
    is read. Scanning on let the evidence sentence vote: "UNKNOWN\nno
    test shows it" parsed as a hard NO (2026-09-07). `UNKNOWN` -- the
    prompt's own word for "the evidence does not say" -- is None, never
    a failure. Narration before the verdict is still skipped over."""
    body = (text or "").strip()
    # A shouted verdict anywhere means the answer DID answer, so a
    # sentence-case `No ...` ahead of it is narration, not the verdict.
    shouted_elsewhere = _SHOUTED.search(body) is not None
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if _UNKNOWN_RE.search(line):
            return None
        match = _YES_NO_RE.search(line)
        if match is None:
            continue
        word = match.group(1)
        shouted = word == word.upper()
        if (not shouted and word.lower() == "no"
                and _is_determiner(line, match.start(), at_line_start=shouted_elsewhere)):
            continue        # ordinary English, not a verdict
        return word.lower()
    return None


def _is_determiner(line: str, at: int, *, at_line_start: bool = False) -> bool:
    """Whether the un-shouted `no`/`No` at `at` is a determiner.

    A verdict is shouted (`NO`), or stands alone or at the end of a line
    ("The answer is: no", "No, it does not"). A `no` with a bare word
    after it is the determiner -- "no test output is shown", "No clear
    signal", "there is no way to tell" -- and refusing to read it as a
    verdict yields None (the evidence does not say), never `yes`.

    A determiner opening the line is only read as prose when the answer
    shouts a verdict somewhere else (`at_line_start`); otherwise the
    line-opening word is all the answer we have, and turning a genuine
    "No changes ..." into None would let an unanswered item slip past
    `checklist_min_answered_fraction` instead of failing."""
    if at == 0 and not at_line_start:
        return False
    return _DETERMINER_NO.match(line[at:].lower()) is not None
