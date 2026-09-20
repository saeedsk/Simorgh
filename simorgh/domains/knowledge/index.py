"""The index: one sqlite file holding documents, passages, a full-text
index over them, and their vectors.

One file, in `workspace/knowledge/index.db`, for a reason beyond
tidiness: `describe_data` and `query_data` (the data toolset) find it
there, so "how many documents did I add last month" is a SQL question
nobody had to build a tool for.

`sqlite-vec` would give a real vector index; it is not installed and is
not required. Vectors live in an ordinary table and are scored in
Python. At the scale this is for -- a person's own documents, tens of
thousands of passages, not millions -- a linear scan over a few
thousand candidate vectors is a few milliseconds, and being wrong about
that is a matter of adding an index later, not of a different design.

FTS5 is compiled into the Python that ships with macOS and every Linux
distribution worth the name, and is checked for at open time rather
than assumed: a missing FTS5 degrades this to vector-only with a stated
reason, which is a worse search and an honest one.
"""

from __future__ import annotations

import array
import hashlib
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .api import Chunk, Document, SourceSpec

SCHEMA_VERSION = 1

#: `unicode61 remove_diacritics 2` and NOT porter stemming: stemming
#: mangles names, and a personal corpus is full of them ("Karimabadi"
#: must not stem to something that matches "karimabad").
_FTS_TOKENIZER = "unicode61 remove_diacritics 2"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    spec TEXT NOT NULL,
    added_at REAL NOT NULL,
    last_scan REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    mime TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    pages INTEGER NOT NULL DEFAULT 0,
    privacy TEXT NOT NULL DEFAULT 'personal',
    indexed_at REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'indexed',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS documents_source ON documents(source);
CREATE INDEX IF NOT EXISTS documents_path ON documents(path);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    page INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS chunk_vec (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embedding BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (doc_id, tag)
);
"""

_FTS_SCHEMA = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='id',
    tokenize='{_FTS_TOKENIZER}'
);
"""


def fts5_available() -> bool:
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.Error:
        return False


def document_id(source: str, path: str) -> str:
    """Stable across runs and across a rescan, derived from where the
    document is rather than from its content -- a file whose contents
    change is the same document, and its citations must keep working."""
    return hashlib.sha256(f"{source}\x00{path}".encode("utf-8")).hexdigest()[:16]


def pack_vector(values) -> bytes:
    return array.array("f", values).tobytes()


def unpack_vector(blob: bytes) -> array.array:
    out = array.array("f")
    out.frombytes(blob)
    return out


class Index:
    """The store. Not thread-safe by itself; every tool call opens and
    closes its own connection, which for a local file at this scale
    costs less than the bookkeeping of sharing one would."""

    def __init__(self, path: Path | str, *, clock=time.time) -> None:
        self.path = Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.has_fts = fts5_available()
        # `check_same_thread=False` because a scan runs in a worker
        # thread (`kb_sources scan` uses `asyncio.to_thread`: parsing and
        # embedding a documents folder would otherwise hold the event
        # loop for minutes). Without it every real scan raised
        # "SQLite objects created in a thread can only be used in that
        # same thread" -- caught by the tool's own test, not by any
        # amount of testing the scanner directly. Only ever one thread
        # uses a given connection at a time: the event loop awaits the
        # worker rather than running beside it.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._create()

    def _create(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)
            if self.has_fts:
                self._conn.executescript(_FTS_SCHEMA)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Index":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- sources -------------------------------------------------------------

    def add_source(self, spec: SourceSpec) -> None:
        import json

        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO sources(name, spec, added_at, last_scan) "
                "VALUES (?, ?, ?, COALESCE((SELECT last_scan FROM sources WHERE name = ?), 0))",
                (spec.name, json.dumps(spec.to_dict()), self._clock(), spec.name))

    def remove_source(self, name: str) -> int:
        """Drops the source and every document that came from it: a
        source that is gone leaves no searchable remains, which is the
        only behaviour that makes `kb_sources remove` a real answer to
        "stop indexing my mail"."""
        with self._conn:
            removed = self._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE source = ?", (name,)).fetchone()[0]
            doc_ids = [r[0] for r in self._conn.execute(
                "SELECT id FROM documents WHERE source = ?", (name,))]
            for doc_id in doc_ids:
                self._delete_document(doc_id)
            self._conn.execute("DELETE FROM sources WHERE name = ?", (name,))
        return int(removed)

    def sources(self) -> list[SourceSpec]:
        import json

        return [SourceSpec.from_dict(json.loads(row["spec"]))
                for row in self._conn.execute("SELECT spec FROM sources ORDER BY name")]

    def mark_scanned(self, name: str, when: float | None = None) -> None:
        with self._conn:
            self._conn.execute("UPDATE sources SET last_scan = ? WHERE name = ?",
                               (when if when is not None else self._clock(), name))

    def last_scan(self, name: str) -> float:
        row = self._conn.execute("SELECT last_scan FROM sources WHERE name = ?", (name,)).fetchone()
        return float(row["last_scan"]) if row else 0.0

    # -- documents -----------------------------------------------------------

    def sha_of(self, doc_id: str) -> str | None:
        row = self._conn.execute("SELECT sha256 FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return row["sha256"] if row else None

    def get_document(self, doc_id: str) -> Document | None:
        row = self._conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return self._document(row) if row else None

    def find_document(self, path: str) -> Document | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE path = ? ORDER BY indexed_at DESC LIMIT 1",
            (path,)).fetchone()
        return self._document(row) if row else None

    @staticmethod
    def _document(row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"], source=row["source"], path=row["path"], title=row["title"],
            mime=row["mime"], sha256=row["sha256"], bytes=row["bytes"], mtime=row["mtime"],
            pages=row["pages"], privacy=row["privacy"], indexed_at=row["indexed_at"],
            status=row["status"], detail=row["detail"],
        )

    def document_paths(self, source: str) -> set[str]:
        return {row["path"] for row in self._conn.execute(
            "SELECT path FROM documents WHERE source = ?", (source,))}

    def _delete_document(self, doc_id: str) -> None:
        rows = [r[0] for r in self._conn.execute(
            "SELECT id FROM chunks WHERE doc_id = ?", (doc_id,))]
        if self.has_fts:
            for chunk_id in rows:
                self._conn.execute(
                    "INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', ?, "
                    "(SELECT text FROM chunks WHERE id = ?))", (chunk_id, chunk_id))
        self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def delete_document(self, doc_id: str) -> None:
        with self._conn:
            self._delete_document(doc_id)

    def put_document(self, document: Document, chunks: list[Chunk], *, vectors=None) -> None:
        """Replace a document and everything derived from it.

        Replace rather than update: a re-parsed document may have any
        number of chunks in any arrangement, and reconciling that in
        place is a great deal of code whose only purpose is to save
        writing a few kilobytes.
        """
        with self._conn:
            self._delete_document(document.id)
            self._conn.execute(
                "INSERT INTO documents(id, source, path, title, mime, sha256, bytes, mtime, pages, "
                "privacy, indexed_at, status, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (document.id, document.source, document.path, document.title, document.mime,
                 document.sha256, document.bytes, document.mtime, document.pages, document.privacy,
                 document.indexed_at or self._clock(), document.status, document.detail))
            for chunk in chunks:
                cursor = self._conn.execute(
                    "INSERT INTO chunks(doc_id, ordinal, heading_path, page, text, tokens) "
                    "VALUES (?,?,?,?,?,?)",
                    (chunk.doc_id, chunk.ordinal, chunk.heading_path, chunk.page, chunk.text,
                     chunk.tokens))
                chunk_id = cursor.lastrowid
                if self.has_fts:
                    self._conn.execute(
                        "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)", (chunk_id, chunk.text))
                if vectors is not None:
                    vector = vectors.get(chunk.ordinal)
                    if vector is not None:
                        provider, values = vector
                        self._conn.execute(
                            "INSERT OR REPLACE INTO chunk_vec(chunk_id, provider, dim, embedding) "
                            "VALUES (?,?,?,?)",
                            (chunk_id, provider, len(values), pack_vector(values)))

    # -- reading back --------------------------------------------------------

    def chunk_row(self, chunk_id: int):
        return self._conn.execute(
            "SELECT c.*, d.title, d.path, d.privacy, d.source FROM chunks c "
            "JOIN documents d ON d.id = c.doc_id WHERE c.id = ?", (chunk_id,)).fetchone()

    def chunks_of(self, doc_id: str) -> list[Chunk]:
        return [Chunk(doc_id=row["doc_id"], ordinal=row["ordinal"], text=row["text"],
                      heading_path=row["heading_path"], page=row["page"], tokens=row["tokens"])
                for row in self._conn.execute(
                    "SELECT * FROM chunks WHERE doc_id = ? ORDER BY ordinal", (doc_id,))]

    def search_lexical(self, query: str, limit: int = 50, *, source: str = "",
                       since: float = 0.0) -> list[tuple[int, float]]:
        """`(chunk_id, rank)` best first. Empty when FTS5 is absent --
        the caller says so rather than pretending the corpus is empty."""
        if not self.has_fts:
            return []
        match = _fts_query(query)
        if not match:
            return []
        sql = ("SELECT f.rowid AS chunk_id, bm25(chunks_fts) AS rank FROM chunks_fts f "
               "JOIN chunks c ON c.id = f.rowid JOIN documents d ON d.id = c.doc_id "
               "WHERE chunks_fts MATCH ?")
        params: list = [match]
        if source:
            sql += " AND d.source = ?"
            params.append(source)
        if since:
            sql += " AND d.mtime >= ?"
            params.append(since)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            return [(int(row["chunk_id"]), float(row["rank"]))
                    for row in self._conn.execute(sql, params)]
        except sqlite3.OperationalError:
            # A malformed MATCH expression is the user's phrasing, not a
            # broken index: answer nothing rather than raising.
            return []

    def vectors(self, *, source: str = "", since: float = 0.0):
        sql = ("SELECT v.chunk_id, v.provider, v.embedding FROM chunk_vec v "
               "JOIN chunks c ON c.id = v.chunk_id JOIN documents d ON d.id = c.doc_id WHERE 1=1")
        params: list = []
        if source:
            sql += " AND d.source = ?"
            params.append(source)
        if since:
            sql += " AND d.mtime >= ?"
            params.append(since)
        for row in self._conn.execute(sql, params):
            yield int(row["chunk_id"]), row["provider"], unpack_vector(row["embedding"])

    # -- stats ---------------------------------------------------------------

    def stats(self) -> dict:
        counts = {}
        for key, sql in (
            ("documents", "SELECT COUNT(*) FROM documents"),
            ("chunks", "SELECT COUNT(*) FROM chunks"),
            ("vectors", "SELECT COUNT(*) FROM chunk_vec"),
            ("sources", "SELECT COUNT(*) FROM sources"),
        ):
            counts[key] = int(self._conn.execute(sql).fetchone()[0])
        counts["by_status"] = {row["status"]: int(row["n"]) for row in self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM documents GROUP BY status")}
        counts["bytes"] = int(self._conn.execute(
            "SELECT COALESCE(SUM(bytes), 0) FROM documents").fetchone()[0])
        counts["db_bytes"] = self.path.stat().st_size if self.path.exists() else 0
        counts["fts"] = self.has_fts
        return counts

    def failures(self, limit: int = 10) -> list[Document]:
        return [self._document(row) for row in self._conn.execute(
            "SELECT * FROM documents WHERE status NOT IN ('indexed') "
            "ORDER BY indexed_at DESC LIMIT ?", (limit,))]


def _fts_query(query: str) -> str:
    """A person's phrasing, turned into something FTS5 will accept.

    Bare user text goes into MATCH as an expression, so `what's the
    excess?` is a syntax error and `AND` means something. Every term is
    quoted and joined explicitly; a leading `"` in the raw query is
    taken as the person meaning a phrase and passed through.
    """
    query = (query or "").strip()
    if not query:
        return ""
    if query.startswith('"') and query.endswith('"') and len(query) > 1:
        return query
    terms = [t for t in _tokenize(query) if t]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


def _tokenize(text: str) -> list[str]:
    import re

    return [t.lower() for t in re.findall(r"[\w']+", text, flags=re.UNICODE) if len(t) > 1]


__all__ = ["Index", "SCHEMA_VERSION", "document_id", "fts5_available", "pack_vector",
           "unpack_vector"]
