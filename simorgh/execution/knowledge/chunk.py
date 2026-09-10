"""Turning a document's text into passages worth retrieving.

Retrieval quality is decided here far more than in the ranking. A chunk
that splits a table down the middle can never answer a question about
that table however well it is scored, and a chunk that has lost the
heading it sat under is unciteable even when it is exactly right.

Three rules, each from a way this goes wrong:

- **Split on structure first, size second.** Headings are where a
  document changes subject, so they are the natural seams. Only when a
  section is too big for one passage is it cut by size.
- **A table stays whole.** A run of lines that look like a table is
  never split, even when that makes an oversized chunk: half a table is
  worse than no table, because it retrieves and then misleads.
- **Overlap between size-cut passages.** A fact that straddles a cut is
  otherwise in neither passage properly. The overlap is the cheapest
  insurance there is against that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .api import Chunk

#: Markdown ATX headings, and the underlined Setext form Docling and
#: pandoc both emit.
_ATX = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_SETEXT = re.compile(r"^(=+|-{2,})\s*$")

#: A page break as `pdftext`/`pdfminer` writes it.
_PAGE_BREAK = "\f"

#: A line with two or more runs of whitespace between non-space runs, or
#: a pipe/tab table row. Crude on purpose: the cost of a false positive
#: is one chunk that is bigger than it needed to be.
_TABLE_ROW = re.compile(r"^\s*\S+(?:( {2,}|\t+|\s*\|\s*)\S+){2,}\s*$")


def estimate_tokens(text: str) -> int:
    """Words plus a fudge for punctuation and sub-word splits. Good
    enough to size a chunk; nothing here bills by the token, and a real
    tokenizer would mean a dependency and a model choice for a number
    used only as a length."""
    words = len(text.split())
    return int(words * 1.3) + 1


@dataclass
class _Section:
    heading_path: str
    page: int
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def _heading_of(line: str, previous: str | None) -> tuple[int, str] | None:
    """`(level, title)` when `line` is a heading."""
    match = _ATX.match(line)
    if match:
        return len(match.group(1)), match.group(2).strip()
    if previous is not None and _SETEXT.match(line) and previous.strip():
        return (1 if line.startswith("=") else 2), previous.strip()
    return None


def _lines(text: str) -> list[str]:
    """Split on newlines only, keeping `\f` inside the line it sits on."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def split_sections(text: str) -> list[_Section]:
    """Structure first: one section per heading, carrying the trail of
    headings above it and the page it starts on."""
    sections: list[_Section] = []
    trail: list[tuple[int, str]] = []
    page = 1
    current = _Section("", page, [])
    previous_line: str | None = None

    # NOT `splitlines()`: it treats a form feed as a line terminator and
    # consumes it, so every page break vanished before this loop could
    # count it and every citation in a 300-page PDF said "page 1".
    for raw in _lines(text):
        if _PAGE_BREAK in raw:
            page += raw.count(_PAGE_BREAK)
            raw = raw.replace(_PAGE_BREAK, "")
            if not raw.strip():
                previous_line = None
                continue

        heading = _heading_of(raw, previous_line)
        if heading is not None:
            level, title = heading
            # A Setext underline turns the line before it into a
            # heading, so that line has to be taken back out of the
            # section it was already put into.
            if _SETEXT.match(raw) and current.lines and current.lines[-1].strip() == title:
                current.lines.pop()
            if current.text:
                sections.append(current)
            trail = [(lvl, name) for lvl, name in trail if lvl < level]
            trail.append((level, title))
            current = _Section(" / ".join(name for _, name in trail), page, [])
            previous_line = None
            continue

        current.lines.append(raw)
        previous_line = raw

    if current.text:
        sections.append(current)
    return sections


def _table_runs(lines: list[str]) -> list[tuple[int, int]]:
    """Half-open ranges of `lines` that look like a table."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if _TABLE_ROW.match(line):
            if start is None:
                start = index
        elif start is not None:
            if index - start >= 2:
                runs.append((start, index))
            start = None
    if start is not None and len(lines) - start >= 2:
        runs.append((start, len(lines)))
    return runs


def _split_by_size(lines: list[str], max_tokens: int, overlap: float) -> list[list[str]]:
    """Cut a too-long section, never through a table.

    The overlap is applied *after* empty groups are dropped, not while
    cutting. Carrying lines forward first produced a trailing chunk made
    of nothing but the carry -- one duplicated table row and a blank
    line, which retrieves as a real passage and says nothing.
    """
    protected: set[int] = set()
    for start, end in _table_runs(lines):
        # A cut "at index i" means the new chunk starts at i, so it is a
        # cut *after* i-1. Marking every row but the last stops a cut
        # landing inside the run while still allowing one after it.
        protected.update(range(start, end - 1))

    groups: list[list[str]] = []
    current: list[str] = []
    tokens = 0
    for index, line in enumerate(lines):
        line_tokens = estimate_tokens(line)
        if current and tokens + line_tokens > max_tokens and index - 1 not in protected:
            groups.append(current)
            current, tokens = [], 0
        current.append(line)
        tokens += line_tokens
    if current:
        groups.append(current)

    groups = [g for g in groups if "".join(g).strip()]
    if overlap <= 0 or len(groups) < 2:
        return groups

    out = [groups[0]]
    for previous, group in zip(groups, groups[1:]):
        carry = max(1, int(len(previous) * overlap))
        out.append(previous[-carry:] + group)
    return out


def chunk_text(text: str, *, doc_id: str, max_tokens: int = 400, overlap: float = 0.15
               ) -> list[Chunk]:
    """The whole pipeline: structure, then size, then overlap.

    An empty or whitespace-only document yields no chunks rather than
    one empty one -- an empty passage matches nothing and clutters
    every count.
    """
    chunks: list[Chunk] = []
    ordinal = 0
    for section in split_sections(text or ""):
        lines = [line for line in section.lines]
        if not "".join(lines).strip():
            continue
        for group in _split_by_size(lines, max_tokens, overlap):
            body = "\n".join(group).strip()
            if not body:
                continue
            chunks.append(Chunk(
                doc_id=doc_id, ordinal=ordinal, text=body,
                heading_path=section.heading_path, page=section.page,
                tokens=estimate_tokens(body),
            ))
            ordinal += 1
    return chunks


__all__ = ["chunk_text", "estimate_tokens", "split_sections"]
