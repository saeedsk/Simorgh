"""The domain objects. Deliberately small and frozen: everything else in
this package turns bytes into these and these into an answer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceSpec:
    """One place documents come from.

    `privacy` is the class from `platform-connectors-design.md` section
    10 and travels with every chunk the source produces, because the
    decision it drives -- may a cloud model see this text -- has to be
    makeable at answer time, long after the file was read.
    """

    kind: str = "files"           # files | paperless | mail_archive | web_clips
    path: str = ""
    privacy: str = "personal"     # public | personal | sensitive
    include: tuple[str, ...] = ("**/*",)
    exclude: tuple[str, ...] = ()
    scan_every_s: float = 3600.0

    @property
    def name(self) -> str:
        return f"{self.kind}:{self.path}"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "path": self.path, "privacy": self.privacy,
                "include": list(self.include), "exclude": list(self.exclude),
                "scan_every_s": self.scan_every_s}

    @classmethod
    def from_dict(cls, data: dict) -> "SourceSpec":
        return cls(
            kind=str(data.get("kind", "files")),
            path=str(data.get("path", "")),
            privacy=str(data.get("privacy", "personal")),
            include=tuple(data.get("include") or ("**/*",)),
            exclude=tuple(data.get("exclude") or ()),
            scan_every_s=float(data.get("scan_every_s", 3600.0)),
        )


@dataclass(frozen=True)
class Document:
    id: str
    source: str
    path: str
    title: str
    mime: str
    sha256: str
    bytes: int
    mtime: float
    pages: int = 0
    privacy: str = "personal"
    indexed_at: float = 0.0
    #: `indexed` | `needs_ocr` | `failed` | `skipped`. A scanned PDF with
    #: OCR off is `needs_ocr`, never an empty `indexed` -- a document
    #: that reports success with no text is one nobody ever looks at
    #: again, and the reason it was empty is lost.
    status: str = "indexed"
    detail: str = ""


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    ordinal: int
    text: str
    #: The heading trail this passage sits under ("Cover / Exclusions"),
    #: which is most of what makes a citation readable.
    heading_path: str = ""
    page: int = 0
    tokens: int = 0


@dataclass(frozen=True)
class Citation:
    doc_id: str
    title: str
    path: str
    page: int = 0
    heading_path: str = ""

    def render(self) -> str:
        """What the model is told to put in its answer, and what
        `kb_open` accepts back."""
        where = f":{self.page}" if self.page else ""
        return f"[{self.doc_id}{where}]"

    @property
    def human(self) -> str:
        bits = [self.title or self.path]
        if self.heading_path:
            bits.append(self.heading_path)
        if self.page:
            bits.append(f"p.{self.page}")
        return " / ".join(bits)


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    citation: Citation
    score: float
    #: Which retriever(s) found it: `("lexical",)`, `("vector",)`, or
    #: both. Shown in `kb_search` output, because "found by both" is a
    #: much stronger result than either alone and a person reading the
    #: list deserves to know which they are looking at.
    found_by: tuple[str, ...] = ()
    privacy: str = "personal"


@dataclass
class ScanReport:
    """What one pass over the sources did. Returned by `kb_sources scan`
    and summarised by `kb_status`."""

    scanned: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: int = 0
    failed: int = 0
    needs_ocr: int = 0
    chunks: int = 0
    problems: list[str] = field(default_factory=list)

    def merge(self, other: "ScanReport") -> None:
        self.scanned += other.scanned
        self.added += other.added
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.removed += other.removed
        self.skipped += other.skipped
        self.failed += other.failed
        self.needs_ocr += other.needs_ocr
        self.chunks += other.chunks
        self.problems.extend(other.problems)

    def summary(self) -> str:
        parts = [f"{self.scanned} file(s) seen"]
        for label, value in (("added", self.added), ("updated", self.updated),
                             ("unchanged", self.unchanged), ("removed", self.removed),
                             ("skipped", self.skipped), ("failed", self.failed),
                             ("needs OCR", self.needs_ocr)):
            if value:
                parts.append(f"{value} {label}")
        if self.chunks:
            parts.append(f"{self.chunks} passage(s) indexed")
        return ", ".join(parts)


__all__ = ["Chunk", "Citation", "Document", "Hit", "ScanReport", "SourceSpec"]
