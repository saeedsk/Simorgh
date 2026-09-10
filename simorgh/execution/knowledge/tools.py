"""The `kb_*` tools: what the model actually calls.

A note on `kb_ask`, which the design describes as "retrieve, then one
cognition call over the passages". Inside a tool that is a second,
nested model call -- and the thing calling the tool is already a model,
mid-turn, with the budget and the context. So `kb_ask` retrieves,
renders the passages with their citations, and hands them back with the
instruction to answer from them or say the answer is not there. The
cognition is the caller's, which costs one model call instead of two
and puts the answer where the person asking can see the passages it
came from.

That leaves `kb_ask` doing one thing `kb_search` does not, and it is
the important one: **the privacy gate**. Retrieval can pull a passage
out of a `sensitive` document -- a medical letter, a bank statement --
and handing that text back to a caller running on a cloud model is
exactly the exposure `platform-connectors-design.md` section 10 exists
to prevent. When the retrieved set is more sensitive than
`[execution] knowledge_cloud_llm_may_see` allows, `kb_ask` returns
*where the answer is* and not what it says. That is a worse answer and
an honest one, and `kb_open` is there for a person who wants the text.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from .api import SourceSpec
from .embed import Embedder
from .index import Index
from .retrieve import most_privileged, render_passages, search
from .sources import scan_all, scan_source

#: Ordered by how much it would matter if it got out.
_PRIVACY_ORDER = {"public": 0, "personal": 1, "sensitive": 2, "secret": 3}


class _KnowledgeTool:
    """Shared plumbing: open the index lazily, and answer usefully when
    there is nothing in it yet.

    Lazily because a tool is constructed at boot, and creating a sqlite
    file (and a WAL beside it) for a feature nobody has configured is
    litter. Every call opens and closes its own connection -- at one
    query per model step, connection setup is not the cost worth
    optimising, and a shared handle across an async tool registry is.
    """

    def __init__(self, config, *, index_factory=None, embedder=None, clock=time.time) -> None:
        self._config = config
        self._index_factory = index_factory
        self._embedder_override = embedder
        self._clock = clock

    # -- helpers -------------------------------------------------------------

    def _index_path(self) -> Path:
        raw = getattr(self._config, "knowledge_index_path", "workspace/knowledge/index.db")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path(getattr(self._config, "repo_root", ".")) / path
        return path

    def _open(self) -> Index:
        if self._index_factory is not None:
            return self._index_factory()
        return Index(self._index_path(), clock=self._clock)

    def _embedder(self):
        if self._embedder_override is not None:
            return self._embedder_override
        return Embedder(getattr(self._config, "knowledge_embedder", "auto"))

    def _may_see(self) -> tuple[str, ...]:
        return tuple(getattr(self._config, "knowledge_cloud_llm_may_see", ("public", "personal")))

    def _empty_hint(self, index: Index) -> str:
        if index.stats()["sources"]:
            return ("nothing is indexed yet from the sources you have configured -- "
                    "run KB_SOURCES: scan")
        return ("no document sources are configured yet. Add one with, e.g.\n"
                'KB_SOURCES: add\n{"kind": "files", "path": "~/Documents", "privacy": "personal"}')


class KbSearchTool(_KnowledgeTool):
    name = "kb_search"
    description = (
        "Search the creator's own indexed documents (files, PDFs, notes) and get back the "
        "matching passages with citations. Prefer this over the web for anything about their "
        "life, house, contracts, finances or past work."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object", "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer"},
            "source": {"type": "string"},
            "since": {"type": "string", "description": "ISO date; only documents modified since"},
        },
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="refused: an empty query")
        k = _clamp_int(args.get("k"), default=8, low=1,
                       high=int(getattr(self._config, "knowledge_max_results", 25)))
        since = _parse_since(args.get("since"))

        index = self._open()
        try:
            if index.stats()["chunks"] == 0:
                return ToolResult(ok=True, output=self._empty_hint(index),
                                  metadata={"hits": 0, "rows": []})
            found = search(index, query, embedder=self._embedder(), k=k,
                           source=str(args.get("source") or ""), since=since)
        finally:
            index.close()

        if not found.hits:
            note = f" ({found.note})" if found.note else ""
            return ToolResult(ok=True, output=f"nothing in your documents matched {query!r}{note}",
                              metadata={"hits": 0, "rows": []})

        lines = []
        rows = []
        for hit in found.hits:
            lines.append(
                f"{hit.citation.render()} {hit.citation.human}"
                f"  [{'+'.join(hit.found_by)}]\n{_indent(hit.chunk.text)}")
            rows.append({
                "doc_id": hit.citation.doc_id, "title": hit.citation.title,
                "path": hit.citation.path, "page": hit.citation.page,
                "heading": hit.citation.heading_path, "score": round(hit.score, 6),
                "found_by": list(hit.found_by), "privacy": hit.privacy,
            })
        body = "\n\n".join(lines)
        if found.note:
            body += f"\n\n(note: {found.note})"
        # `rows` in metadata is the convention every list/search tool
        # follows (platform section 9), so `query_data` can aggregate
        # over the results without a new path.
        return ToolResult(ok=True, output=body,
                          metadata={"hits": len(found.hits), "rows": rows,
                                    "privacy": most_privileged(found.hits)})


class KbAskTool(_KnowledgeTool):
    name = "kb_ask"
    description = (
        "Ask a question of the creator's own documents. Returns the passages that answer it, "
        "each with a citation you must quote as [doc:page]. If the passages do not answer the "
        "question, say so rather than filling the gap from general knowledge."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object", "required": ["question"],
        "properties": {"question": {"type": "string"}, "k": {"type": "integer"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        question = str(args.get("question") or "").strip()
        if not question:
            return ToolResult(ok=False, error="refused: an empty question")
        k = _clamp_int(args.get("k"), default=8, low=1,
                       high=int(getattr(self._config, "knowledge_max_results", 25)))

        index = self._open()
        try:
            if index.stats()["chunks"] == 0:
                return ToolResult(ok=True, output=self._empty_hint(index), metadata={"hits": 0})
            found = search(index, question, embedder=self._embedder(), k=k)
        finally:
            index.close()

        if not found.hits:
            return ToolResult(
                ok=True,
                output=("That is not in your documents. Say so plainly -- do not answer it from "
                        "general knowledge as though it came from their files."),
                metadata={"hits": 0, "answerable": False})

        worst = most_privileged(found.hits)
        allowed = self._may_see()
        if _PRIVACY_ORDER.get(worst, 1) > max(_PRIVACY_ORDER.get(c, 0) for c in allowed):
            # Where the answer is, not what it says.
            # The PATH, not just the title: "where to look" is only
            # useful if it names the file the person has to open.
            where = "\n".join(
                f"- {hit.citation.render()} {hit.citation.human}\n  {hit.citation.path}"
                for hit in found.hits)
            return ToolResult(
                ok=True,
                output=(f"The answer is in {len(found.hits)} passage(s) classed {worst!r}, which "
                        f"this session may not show you (`[execution] knowledge_cloud_llm_may_see` "
                        f"= {list(allowed)}). Tell the person where to look and do not guess at "
                        f"the contents:\n{where}\n\n"
                        f"They can read it themselves, or add {worst!r} to that setting."),
                metadata={"hits": len(found.hits), "privacy": worst, "withheld": True,
                          "rows": [{"doc_id": h.citation.doc_id, "path": h.citation.path,
                                    "page": h.citation.page} for h in found.hits]})

        passages = render_passages(found.hits,
                                   max_chars=int(getattr(self._config, "knowledge_max_chars", 6000)))
        instruction = (
            "Answer the question using only the passages below. Put the citation "
            "(the [id:page] label) after each fact you take from them. If they do not contain "
            "the answer, say \"that is not in your documents\" -- do not fill the gap."
        )
        body = f"{instruction}\n\nQuestion: {question}\n\n{passages}"
        if found.note:
            body += f"\n\n(retrieval note: {found.note})"
        return ToolResult(ok=True, output=body,
                          metadata={"hits": len(found.hits), "privacy": worst, "withheld": False,
                                    "answerable": True})


class KbOpenTool(_KnowledgeTool):
    name = "kb_open"
    description = (
        "Open what is around a citation from kb_search or kb_ask -- the passage itself plus its "
        "neighbours, so you can read more than the snippet. Takes a [doc:page] citation or a "
        "document id."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {
        "type": "object", "required": ["citation"],
        "properties": {"citation": {"type": "string"}, "around": {"type": "integer"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        raw = str(args.get("citation") or "").strip().strip("[]")
        if not raw:
            return ToolResult(ok=False, error="refused: no citation given")
        doc_id, _, page_part = raw.partition(":")
        doc_id = doc_id.strip()
        around = _clamp_int(args.get("around"), default=2, low=0, high=10)

        index = self._open()
        try:
            document = index.get_document(doc_id) or index.find_document(doc_id)
            if document is None:
                return ToolResult(
                    ok=False,
                    error=(f"no indexed document {doc_id!r}. Citations look like [a1b2c3d4e5f6:3] "
                           "and come from kb_search or kb_ask."))
            chunks = index.chunks_of(document.id)
        finally:
            index.close()

        if not chunks:
            return ToolResult(
                ok=True,
                output=(f"{document.title} ({document.path}) is indexed with status "
                        f"{document.status!r}: {document.detail or 'no passages were extracted'}"),
                metadata={"doc_id": document.id, "status": document.status})

        page = _int_or_none(page_part)
        if page is not None:
            centre = next((i for i, c in enumerate(chunks) if c.page == page), 0)
        else:
            centre = 0
        low = max(0, centre - around)
        high = min(len(chunks), centre + around + 1)
        window = chunks[low:high]

        header = f"{document.title}\n{document.path}"
        if document.pages:
            header += f"  ({document.pages} page(s))"
        body = "\n\n".join(
            f"[{document.id}:{c.page}] {c.heading_path or '(no heading)'}\n{c.text}" for c in window)
        more = ""
        if high < len(chunks) or low > 0:
            more = (f"\n\n(passages {low + 1}-{high} of {len(chunks)}; "
                    "raise `around` for more, or read_file the path for all of it)")
        return ToolResult(ok=True, output=f"{header}\n\n{body}{more}",
                          metadata={"doc_id": document.id, "path": document.path,
                                    "passages": len(window), "of": len(chunks),
                                    "privacy": document.privacy})


class KbSourcesTool(_KnowledgeTool):
    name = "kb_sources"
    description = (
        "Manage which folders are indexed into the creator's knowledge base: list, add, remove, "
        "or scan them now. Adding a source does not read anything until a scan runs."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["op"],
        "properties": {
            "op": {"type": "string", "enum": ["list", "add", "remove", "scan"]},
            "path": {"type": "string"},
            "kind": {"type": "string"},
            "privacy": {"type": "string", "enum": ["public", "personal", "sensitive"]},
            "include": {"type": "array", "items": {"type": "string"}},
            "exclude": {"type": "array", "items": {"type": "string"}},
            "name": {"type": "string", "description": "for remove/scan: which source"},
        },
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        op = str(args.get("op") or "list").strip().lower()
        index = self._open()
        try:
            if op == "list":
                return self._list(index)
            if op == "add":
                return self._add(index, args)
            if op == "remove":
                return self._remove(index, args)
            if op == "scan":
                return await self._scan(index, args)
            return ToolResult(ok=False, error=f"refused: unknown op {op!r}; use list, add, remove or scan")
        finally:
            index.close()

    def _list(self, index: Index) -> ToolResult:
        specs = index.sources()
        if not specs:
            return ToolResult(ok=True, output=self._empty_hint(index), metadata={"rows": []})
        rows, lines = [], []
        for spec in specs:
            last = index.last_scan(spec.name)
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else "never"
            lines.append(f"- {spec.name}  privacy={spec.privacy}  last scan: {when}")
            rows.append({**spec.to_dict(), "name": spec.name, "last_scan": last})
        return ToolResult(ok=True, output="\n".join(lines), metadata={"rows": rows})

    def _add(self, index: Index, args: dict) -> ToolResult:
        path = str(args.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, error="refused: `path` is required to add a source")
        resolved = Path(path).expanduser()
        if not resolved.exists():
            return ToolResult(ok=False, error=f"refused: {resolved} does not exist")
        privacy = str(args.get("privacy") or "personal").strip().lower()
        if privacy not in ("public", "personal", "sensitive"):
            return ToolResult(ok=False,
                              error=f"refused: privacy must be public, personal or sensitive, not {privacy!r}")
        spec = SourceSpec(
            kind=str(args.get("kind") or "files"), path=str(resolved), privacy=privacy,
            include=tuple(args.get("include") or ("**/*",)),
            exclude=tuple(args.get("exclude") or ()),
        )
        index.add_source(spec)
        return ToolResult(
            ok=True,
            output=(f"added {spec.name} (privacy={privacy}). Nothing has been read yet -- "
                    "run KB_SOURCES: scan to index it."),
            side_effects=(f"knowledge source added: {spec.name}",),
            metadata={"source": spec.name, "privacy": privacy})

    def _remove(self, index: Index, args: dict) -> ToolResult:
        name = str(args.get("name") or args.get("path") or "").strip()
        if not name:
            return ToolResult(ok=False, error="refused: `name` is required (see kb_sources list)")
        known = {spec.name: spec for spec in index.sources()}
        if name not in known:
            match = [n for n in known if n.endswith(name) or Path(n.split(":", 1)[-1]).name == name]
            if len(match) != 1:
                return ToolResult(ok=False,
                                  error=f"refused: no source {name!r}; known: {', '.join(sorted(known)) or 'none'}")
            name = match[0]
        removed = index.remove_source(name)
        return ToolResult(ok=True,
                          output=f"removed {name} and the {removed} document(s) indexed from it",
                          side_effects=(f"knowledge source removed: {name}",),
                          metadata={"source": name, "documents_removed": removed})

    async def _scan(self, index: Index, args: dict) -> ToolResult:
        import asyncio

        specs = index.sources()
        if not specs:
            return ToolResult(ok=True, output=self._empty_hint(index))
        name = str(args.get("name") or "").strip()
        chosen = [s for s in specs if not name or s.name == name or s.path.endswith(name)]
        if not chosen:
            return ToolResult(ok=False, error=f"refused: no source matching {name!r}")

        embedder = self._embedder()
        kwargs = dict(
            embedder=embedder,
            chunk_tokens=int(getattr(self._config, "knowledge_chunk_tokens", 400)),
            overlap=float(getattr(self._config, "knowledge_chunk_overlap", 0.15)),
            max_file_bytes=int(getattr(self._config, "knowledge_max_file_mb", 100)) * 1024 * 1024,
            clock=self._clock,
        )

        def _work():
            from .api import ScanReport

            total = ScanReport()
            for spec in chosen:
                total.merge(scan_source(index, spec, **kwargs))
            return total

        # Scanning is blocking file and sqlite work; a directory of PDFs
        # would otherwise hold the event loop for minutes and stall
        # every other subsystem on the bus.
        report = await asyncio.to_thread(_work)
        body = report.summary()
        if report.problems:
            body += "\n\nnot indexed:\n" + "\n".join(f"- {p}" for p in report.problems[:10])
        if embedder.degraded:
            body += f"\n\n(embedder: {embedder.degraded})"
        return ToolResult(ok=True, output=body,
                          side_effects=(f"scanned {len(chosen)} knowledge source(s)",),
                          metadata={"scanned": report.scanned, "added": report.added,
                                    "updated": report.updated, "removed": report.removed,
                                    "failed": report.failed, "needs_ocr": report.needs_ocr,
                                    "chunks": report.chunks})


class KbStatusTool(_KnowledgeTool):
    name = "kb_status"
    description = (
        "What is in the creator's knowledge base: how many documents and passages, which sources, "
        "when they were last scanned, and what failed to index."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {}}

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        index = self._open()
        try:
            stats = index.stats()
            specs = index.sources()
            failures = index.failures(limit=5)
            last_scans = {spec.name: index.last_scan(spec.name) for spec in specs}
        finally:
            index.close()

        embedder = self._embedder()
        lines = [
            f"{stats['documents']} document(s), {stats['chunks']} passage(s), "
            f"{stats['vectors']} vector(s) from {stats['sources']} source(s)",
            f"index: {self._index_path()} ({stats['db_bytes'] // 1024} KB)",
            f"full-text search: {'on' if stats['fts'] else 'OFF -- this sqlite has no FTS5'}",
            f"embedder: {embedder.provider}"
            + ("" if embedder.semantic else " (matches shared words, not meaning)"),
        ]
        if embedder.degraded:
            lines.append(f"  {embedder.degraded}")
        for spec in specs:
            last = last_scans.get(spec.name, 0.0)
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else "never"
            lines.append(f"- {spec.name}  privacy={spec.privacy}  last scan: {when}")
        by_status = {k: v for k, v in stats["by_status"].items() if k != "indexed"}
        if by_status:
            lines.append("not fully indexed: "
                         + ", ".join(f"{n} {status}" for status, n in sorted(by_status.items())))
        for document in failures:
            lines.append(f"  [{document.status}] {document.path}: {document.detail[:120]}")
        return ToolResult(ok=True, output="\n".join(lines), metadata=stats)


def _indent(text: str, width: int = 400) -> str:
    body = text.strip()
    if len(body) > width:
        body = body[:width].rstrip() + "…"
    return "\n".join("    " + line for line in body.splitlines())


def _clamp_int(value, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _int_or_none(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_since(value) -> float:
    """An ISO date, or "" for no bound. A date nobody can parse is
    treated as no bound rather than as an error: the failure mode of
    guessing wrong here is a slightly wider search, and refusing the
    whole query over a date format is worse."""
    text = str(value or "").strip()
    if not text:
        return 0.0
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def knowledge_tools(config, **kwargs) -> list:
    return [
        KbSearchTool(config, **kwargs),
        KbAskTool(config, **kwargs),
        KbOpenTool(config, **kwargs),
        KbSourcesTool(config, **kwargs),
        KbStatusTool(config, **kwargs),
    ]


__all__ = ["KbAskTool", "KbOpenTool", "KbSearchTool", "KbSourcesTool", "KbStatusTool",
           "knowledge_tools"]
