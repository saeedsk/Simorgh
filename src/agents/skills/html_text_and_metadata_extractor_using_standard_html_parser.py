"""HTML text and metadata extractor using standard html.parser."""

from html.parser import HTMLParser
from typing import Dict, List, Optional, Any
import re


class HTMLContentExtractor(HTMLParser):
    """Extracts cleaned text and metadata from HTML content."""

    # Tags whose inner content should be completely ignored
    SKIPPED_TAGS = {"script", "style", "noscript", "template"}

    # Block tags that warrant line breaks
    BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer", "main", "nav",
        "aside", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table",
        "blockquote", "pre", "br", "hr"
    }

    def __init__(self) -> None:
        super().__init__()
        self.title: Optional[str] = None
        self.metadata: Dict[str, str] = {}
        self.links: List[Dict[str, str]] = []
        self.headings: List[Dict[str, str]] = []

        self._in_title = False
        self._title_parts: List[str] = []
        self._skip_depth = 0
        self._text_chunks: List[str] = []
        
        # Link tracking
        self._current_link: Optional[Dict[str, Any]] = None
        # Heading tracking
        self._current_heading_tag: Optional[str] = None
        self._current_heading_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attr_dict = dict(attrs)
        tag_lower = tag.lower()

        if tag_lower in self.SKIPPED_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower == "title":
            self._in_title = True
        elif tag_lower == "meta":
            self._extract_meta(attr_dict)
        elif tag_lower == "link":
            rel = attr_dict.get("rel", "").lower()
            if rel in ("canonical", "icon", "shortcut icon", "alternate"):
                href = attr_dict.get("href")
                if href:
                    key = f"link_{rel.replace(' ', '_')}"
                    if key not in self.metadata:
                        self.metadata[key] = href
        elif tag_lower == "a":
            href = attr_dict.get("href")
            if href:
                self._current_link = {
                    "href": href,
                    "text": [],
                    "title": attr_dict.get("title", "")
                }
        elif tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._current_heading_tag = tag_lower
            self._current_heading_parts = []

        if tag_lower in self.BLOCK_TAGS:
            self._text_chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower in self.SKIPPED_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower == "title":
            self._in_title = False
            self.title = "".join(self._title_parts).strip()
        elif tag_lower == "a" and self._current_link is not None:
            link_text = "".join(self._current_link["text"]).strip()
            item = {
                "href": self._current_link["href"],
                "text": link_text
            }
            if self._current_link["title"]:
                item["title"] = self._current_link["title"]
            self.links.append(item)
            self._current_link = None
        elif tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6") and self._current_heading_tag == tag_lower:
            text = "".join(self._current_heading_parts).strip()
            if text:
                self.headings.append({
                    "level": int(tag_lower[1]),
                    "text": text
                })
            self._current_heading_tag = None
            self._current_heading_parts = []

        if tag_lower in self.BLOCK_TAGS:
            self._text_chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return

        if self._in_title:
            self._title_parts.append(data)

        if self._current_link is not None:
            self._current_link["text"].append(data)

        if self._current_heading_tag is not None:
            self._current_heading_parts.append(data)

        self._text_chunks.append(data)

    def _extract_meta(self, attrs: Dict[str, Optional[str]]) -> None:
        # Standard <meta name="..." content="...">
        name = attrs.get("name") or attrs.get("property") or attrs.get("http-equiv")
        content = attrs.get("content")

        if name and content is not None:
            self.metadata[name.lower()] = content
        elif "charset" in attrs and attrs["charset"]:
            self.metadata["charset"] = attrs["charset"]

    def get_clean_text(self) -> str:
        raw_text = "".join(self._text_chunks)
        # Normalize whitespace within lines and collapse multiple blank lines
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw_text.splitlines()]
        cleaned = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def extract_html(html_str: str) -> Dict[str, Any]:
    """
    Extract text and metadata from an HTML string.

    Returns:
        A dictionary with keys:
            - 'title': Page title (str or None)
            - 'text': Cleaned human-readable plain text
            - 'metadata': Extracted metadata (name/property/http-equiv/charset)
            - 'headings': List of {'level': int, 'text': str}
            - 'links': List of {'href': str, 'text': str, Optional['title']: str}
    """
    parser = HTMLContentExtractor()
    parser.feed(html_str)
    parser.close()

    return {
        "title": parser.title,
        "text": parser.get_clean_text(),
        "metadata": parser.metadata,
        "headings": parser.headings,
        "links": parser.links,
    }