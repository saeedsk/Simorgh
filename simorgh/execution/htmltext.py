"""HTML to readable text, stdlib only.

`web_fetch` handed the model raw markup. Measured on real pages
(observer, 2026-09-08):

| page                    | bytes   | markup | content |
|-------------------------|---------|--------|---------|
| docs.python.org asyncio | 177,075 | 74.2%  | present, at offset 19,215 |
| arXiv abstract          |  44,095 | 87.4%  | 5,537 visible chars |
| a JavaScript app        |  41,954 | 99.5%  | **224 chars, and `ok=True`** |

Three costs, in rising order of seriousness. The token bill: an arXiv
abstract spent 11k tokens to deliver 1.4k of content. Silent loss: the
docs page is cut at `max_output_bytes` with the remainder in a blob,
while its extracted text (45,516 chars) would have fitted whole. And
the dead end: a page whose content is drawn by JavaScript returns a
success with nothing in it, so the model burns a step and is told
nothing is wrong.

That last one is why this module reports a JS shell explicitly rather
than returning an empty string. A tool that succeeds and says nothing
is the same class of quiet lie as a benchmark that scores a run it
discarded.

No dependency: `beautifulsoup4` and `lxml` are both installed here, and
`html.parser` is enough. Execution's tools stay importable on a machine
with neither.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Subtrees whose text is never content.
_SKIP = frozenset({"script", "style", "noscript", "svg", "template", "iframe", "head"})
# ...except the title, which is often the single most useful line.
_KEEP_IN_HEAD = frozenset({"title"})
_BLOCK = frozenset({
    "p", "div", "section", "article", "header", "footer", "main", "nav", "aside",
    "ul", "ol", "table", "tr", "form", "figure", "blockquote", "pre", "hr", "br",
})
_HEADING = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}

# What separates a JavaScript shell from a small page. Measured, not
# guessed: the HF Space returned 224 characters from 41,954 bytes
# (0.5%); the arXiv abstract 5,537 from 44,095 (12.6%); the Python docs
# 45,516 from 177,075 (25.7%). A page too small to hide anything is
# never flagged -- a short document with short text is just short.
_SHELL_MIN_HTML = 5_000
_SHELL_MIN_CHARS = 300
_SHELL_MIN_RATIO = 0.02
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False
        self._links: list[str] = []

    # -- structure -----------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _KEEP_IN_HEAD:
            self._in_title = True
            return
        if tag in _SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING:
            self.parts.append(f"\n\n{_HEADING[tag]} ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in _BLOCK:
            self.parts.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            # Only a real destination is worth the characters; a
            # fragment or a relative path tells the model nothing it can
            # fetch.
            self._links.append(href if href.startswith(("http://", "https://")) else "")

    def handle_endtag(self, tag: str) -> None:
        if tag in _KEEP_IN_HEAD:
            self._in_title = False
            return
        if tag in _SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _HEADING or tag in _BLOCK:
            self.parts.append("\n")
        elif tag == "a" and self._links:
            href = self._links.pop()
            if href:
                self.parts.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_depth or not data.strip():
            return
        self.parts.append(_WS.sub(" ", data))

    def text(self) -> str:
        body = "".join(self.parts)
        body = _WS.sub(" ", body)
        body = "\n".join(line.strip() for line in body.splitlines())
        return _BLANKS.sub("\n\n", body).strip()


def looks_like_html(text: str) -> bool:
    """Cheap and conservative: JSON, Markdown and plain text pass
    through untouched."""
    head = (text or "")[:2000].lstrip().lower()
    if head.startswith(("{", "[")):
        return False
    return head.startswith("<!doctype html") or head.startswith("<html") or "<body" in head or "<div" in head


def _visible_chars(text: str) -> int:
    """Characters of prose, not counting the link targets we chose to
    keep -- hrefs alone inflate the total and hide a shell (observer,
    2026-09-08)."""
    return len(re.sub(r"\(https?://[^)]*\)", " ", text).strip())


def is_js_shell(body: str, html: str) -> bool:
    """Whether this page's content is drawn by JavaScript we do not run."""
    if not body.strip():
        return True  # a fetch that yields nothing must always say so
    if len(html) < _SHELL_MIN_HTML:
        return False
    visible = _visible_chars(body)
    return visible < _SHELL_MIN_CHARS or (visible / len(html)) < _SHELL_MIN_RATIO


def html_to_text(html: str, *, url: str = "") -> tuple[str, bool]:
    """`(text, is_js_shell)`.

    A shell gets a message saying so, with whatever text there was --
    never a blank, and never a bare success.
    """
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 -- malformed markup is common; keep what parsed
        pass
    body = parser.text()
    title = " ".join(parser.title.split())
    if title:
        body = f"{title}\n\n{body}" if body else title

    if is_js_shell(body, html):
        where = f" from {url}" if url else ""
        note = (
            f"[this page{where} returned {len(html)} bytes of HTML but only {len(body)} characters "
            f"of text: it draws its content with JavaScript, which this tool does not run. "
            f"Try an API, a raw file, or an export URL for the same content.]"
        )
        return (f"{note}\n\n{body}".strip() if body else note), True
    return body, False


__all__ = ["html_to_text", "is_js_shell", "looks_like_html"]
