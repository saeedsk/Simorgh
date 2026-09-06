"""Output parsing: markers, edit blocks, non-answer detection (docs/
blueprint/subsystems/04-cognition.md section 5, "Output parsing"). Ported
directly from v1 `src/cognition/tool_protocol.py` and
`src/orchestrator/self_patch.py` -- every rule below is a real,
live-caught lesson (see docs/EVOLUTION.md), not a fresh design:

- A model doesn't always stop at a marker; it keeps reasoning out loud
  in the same response. For a single-bare-token argument (a path, a
  name), only the first non-empty line was ever the real answer
  (`first_line_argument`). For a code-bearing marker (`DRAFT`/`RUN`),
  everything after the marker is the payload, kept intact.
- A "verdict" response (`YES`/`NO`) can be silently non-compliant: the
  model narrates instead of answering. Scanning every line for a
  standalone YES/NO, and reporting `non_answer=True` when none is found,
  turns a would-be false rejection into an honest "the reviewer didn't
  review" signal the caller can defer on, never a rejection.
- SEARCH/REPLACE blocks use the exact three-way conflict-marker shape
  (`<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE`) real merge conflicts
  and tools like Aider already use -- a shape the model has seen
  thousands of times, not a bespoke format.
"""

from __future__ import annotations

import ast
import re

from .api import ParsedOutput

_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)
_YES_NO_RE = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)
_EDIT_BLOCK_RE = re.compile(
    r"<<<<<<< SEARCH\n(?P<old>.*?)\n=======\n(?P<new>.*?)\n>>>>>>> REPLACE", re.DOTALL,
)
_DEFAULT_PREVIEW_LIMIT = 150


def preview(text: str, limit: int = _DEFAULT_PREVIEW_LIMIT) -> str:
    """A bounded, single-line-safe preview for narration/telemetry --
    never the value used for real work."""
    collapsed = text.replace("\r\n", " ").replace("\n", " ⏎ ").strip()
    if len(collapsed) > limit:
        return collapsed[:limit] + f"… (+{len(collapsed) - limit} more chars)"
    return collapsed


def first_line_argument(text: str) -> str:
    """The first non-empty line, stripped -- for an argument that's
    always exactly one bare token (a path, a name), never free-form
    prose the model may have kept generating past the marker."""
    stripped = text.strip()
    return stripped.splitlines()[0].strip() if stripped else ""


def parse_marker(text: str, markers: tuple[str, ...]) -> tuple[str | None, str]:
    """If `text` (stripped) starts with one of `markers` (case-
    insensitive, followed by ':'), returns (marker.lower(), payload).
    Otherwise (None, text) -- the whole stripped text, meaning "final
    answer, no tool call."
    """
    stripped = text.strip()
    for marker in markers:
        prefix = f"{marker}:"
        if stripped[: len(prefix)].upper() == prefix.upper():
            return marker.lower(), stripped[len(prefix):].strip()
    return None, stripped


def extract_code(text: str) -> str | None:
    match = _CODE_FENCE.search(text)
    stripped = (match.group(1) if match else text).strip()
    return stripped or None


def is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def parse_search_replace_blocks(text: str) -> list[tuple[str, str]] | None:
    """(old, new) pairs, or None if the text contains no recognizable
    block at all -- distinct from an empty list, which never happens.
    None is the signal the caller uses to fall back to treating `text`
    as a plain full-file/final answer instead: a model that ignores the
    edit-block instruction and answers directly is still a working
    answer, not an error.
    """
    matches = [(m.group("old"), m.group("new")) for m in _EDIT_BLOCK_RE.finditer(text)]
    return matches or None


def scan_verdict(text: str) -> bool | None:
    """The first standalone YES/NO found on any line, or None if the
    response never states one -- a non-answer, not a rejection."""
    for line in text.strip().splitlines():
        match = _YES_NO_RE.search(line.strip())
        if match is not None:
            return match.group(1).upper() == "YES"
    return None


class OutputParser:
    """Parses a provider's raw text according to `expected` (04 section
    3.4's `OutputSpec`): `{kind: final|markers|edit_blocks|verdict, markers?: [...]}`.
    """

    def parse(self, text: str, expected: dict | None) -> ParsedOutput:
        expected = expected or {"kind": "final"}
        kind = expected.get("kind", "final")
        if kind == "markers":
            return self._parse_markers(text, tuple(expected.get("markers", ())))
        if kind == "edit_blocks":
            return self._parse_edit_blocks(text)
        if kind == "verdict":
            return self._parse_verdict(text)
        return ParsedOutput(kind="final", text=text.strip())

    def _parse_markers(self, text: str, markers: tuple[str, ...]) -> ParsedOutput:
        marker, payload = parse_marker(text, markers)
        if marker is None:
            return ParsedOutput(kind="final", text=payload)
        # Multi-line-payload markers (code-bearing) keep the payload intact;
        # single-token markers use only the first line (the live-caught lesson).
        arg = payload if marker.upper() in {"DRAFT", "RUN"} else first_line_argument(payload)
        return ParsedOutput(kind="tool_calls", text=text.strip(), tool_calls=({"tool": marker, "args": {"argument": arg}},))

    def _parse_edit_blocks(self, text: str) -> ParsedOutput:
        blocks = parse_search_replace_blocks(text)
        if blocks is None:
            candidate = extract_code(text)
            return ParsedOutput(kind="final", text=candidate or text.strip())
        return ParsedOutput(
            kind="edit_blocks", text=text.strip(),
            edit_blocks=tuple({"search": old, "replace": new} for old, new in blocks),
        )

    def _parse_verdict(self, text: str) -> ParsedOutput:
        verdict = scan_verdict(text)
        if verdict is None:
            return ParsedOutput(kind="non_answer", text=text.strip(), non_answer=True)
        return ParsedOutput(kind="verdict", text=text.strip(), verdict=verdict)


__all__ = [
    "OutputParser", "extract_code", "first_line_argument", "is_valid_python",
    "parse_marker", "parse_search_replace_blocks", "preview", "scan_verdict",
]
