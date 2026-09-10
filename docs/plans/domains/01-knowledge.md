# Domain 1: Personal knowledge and documents

Sim indexes what the creator has -- files, PDFs, notes, scans, mail
archives, web clippings -- and answers from it, with citations, without
any of it leaving the machine. Prerequisites: `platform-connectors-
design.md` §1 (vault), §9 (data flow), §10 (privacy), and
`data-toolset-design.md` (`query_data`, `db_exec`). The memory
embedder (cc7aa78) is the recall engine.

## 0. What exists

- `read_file` reads PDF/DOCX/XLSX text already (`execution/pdftext.py`,
  `doctext.py`); nothing *indexes* them -- every question re-reads.
- Memory stores what Sim *learned*; it has no notion of a document
  corpus, and `memory.retrieve` returns items, not passages with a
  source and page.
- `percept.file.changed` exists as a topic; `watchdog` is installed;
  nothing subscribes for documents.
- Absent: `docling`, `unstructured`, `pdfplumber`, `pymupdf`,
  `tesseract` (the OCR wire exists but has no binary).

## 1. Open-source inventory

| component | role | notes |
|---|---|---|
| **Docling** (IBM, MIT) | PDF/DOCX/PPTX/HTML → structured markdown with tables, headings, reading order; layout-aware | the best open document parser in 2025–26; heavy (torch) but optional |
| **PyMuPDF** (`fitz`, AGPL) / **pdfplumber** | fast text + coordinates; the fallback when Docling is absent | |
| **Tesseract** / **PaddleOCR** / **EasyOCR** | OCR for scans and images | PaddleOCR is the most accurate open one; Tesseract is the lightest |
| **Paperless-ngx** | if the creator already scans: a full document archive with OCR, tags, a REST API | a *connector*, not a dependency |
| **Obsidian / Logseq vaults** (plain markdown) | notes | read as files; an Obsidian MCP exists but files are simpler |
| **Apple Notes / Notion export** | notes | via export files; Notion also has an API + MCP |
| **sentence-transformers** (`bge-m3`, `nomic-embed-text`, `all-MiniLM`) | passage embeddings, local | the `local` embedder from cc7aa78 |
| **`rank_bm25`** / SQLite FTS5 | lexical search beside vectors | hybrid retrieval beats either alone; FTS5 is stdlib |
| **`sqlite-vec`** (or `usearch`) | vector index inside the same sqlite file | keeps the index in `workspace/knowledge/index.db`, queryable by `query_data` |
| **ColBERT/`bge-reranker`** | reranking the top 50 → 8 | optional, +quality |
| **`watchdog`** (present) | file change events | |
| **`mailbox`** (stdlib), `imapclient` | mail archives (mbox/Maildir) and live IMAP | mail *bodies* are `sensitive` |
| **`trafilatura`** | web clippings → clean text | |
| MCP: filesystem MCP, Obsidian MCP, Notion MCP | only if a native path is worse; here files win | |

## 2. Architecture -- `simorgh/knowledge/` (subsystem #20)

```
knowledge/
  api.py         Source, Document, Chunk, Hit, Citation
  config.py
  sources/       base.py files.py paperless.py mail_archive.py web_clips.py notion_export.py
  parse/         base.py docling.py pymupdf.py plaintext.py ocr.py office.py
  chunk.py       structure-aware chunking (headings, tables intact, ~400 tokens, 15% overlap)
  index.py       sqlite: documents, chunks, FTS5, vec table; incremental by content hash
  retrieve.py    hybrid: FTS5 ∪ vector → RRF fuse → rerank → citations
  watcher.py     watchdog → reindex debounced; percept.file.changed → same
  service.py     Service, scheduled full scans, health, stats
  fakes.py       FakeCorpus
```

Index schema (`workspace/knowledge/index.db`):

```
documents(id, source, path, title, mime, sha256, bytes, mtime, pages, privacy, indexed_at, status)
chunks(id, doc_id, ordinal, heading_path, page, text, tokens, embedding_provider)
chunks_fts(text)                      -- FTS5 external content
chunk_vec(id, embedding float[dim])   -- sqlite-vec
tags(doc_id, tag)                     -- user + auto (paperless tags, folder names, dates)
```

Everything a document produces is derived and reproducible; deleting
the db and rescanning is the recovery story.

## 3. Tools (`execution/knowledge.py`)

| tool | args | read_only | reversibility | privacy |
|---|---|---|---|---|
| `kb_search` | `query`, `k?`, `source?`, `since?`, `tags?` | yes | read_only | returns passages + citations; rows → results/ |
| `kb_ask` | `question`, `k?` | yes | read_only | retrieve → *one* cognition call with passages; answer must cite `[doc:page]` or say "not in your documents"; sensitive docs → local model per §10 |
| `kb_open` | `citation` (`doc_id:page` or path) | yes | read_only | the page/section text around a hit |
| `kb_sources` | `op: list\|add\|remove\|scan`, `spec?` | no | reversible | a source is a config row in the ledger `knowledge:sources` |
| `kb_status` | -- | yes | read_only | docs, chunks, last scan, failures, OCR backlog |
| `kb_tag` | `doc`, `tags` | no | reversible | |
| `kb_summarize` | `doc`, `length?` | yes | read_only | cached per (doc sha, length) |
| `kb_similar` | `doc` | yes | read_only | near-duplicate detection (`simhash`) -- "you have this contract three times" |

Markers: `KB_SEARCH: <query>`; `KB_ASK: <question>`; `KB_SOURCES: add\n{"kind": "files", "path": "~/Documents", "privacy": "personal"}`.
Profiles: `kb_search/ask/open/status` in RESEARCH, PATCH, PLAN.
Scaffold line: *"the creator's own documents are searchable with
KB_SEARCH; prefer them over the web for anything about their life,
house, contracts or past work."*

## 4. Config

```python
enabled: bool = False
index_path: str = "workspace/knowledge/index.db"
sources: tuple[SourceSpec, ...] = ()      # kind, path/url, include/exclude globs, privacy, scan_every_s
parser: str = "auto"                      # auto | docling | pymupdf | plaintext
ocr: str = "auto"                         # auto | paddle | tesseract | off
ocr_max_pages: int = 50
chunk_tokens: int = 400
chunk_overlap: float = 0.15
embedder: str = "memory"                  # reuse [memory] embedder; "local" recommended here
rerank: bool = True
max_file_mb: int = 100
scan_every_s: float = 3600
watch: bool = True
excluded_globs: tuple = ("**/.git/**", "**/node_modules/**", "**/*.key", "**/.env*", "**/id_rsa*")
```

`excluded_globs` reuses `pathsafety.looks_like_credential_path` -- a
knowledge base that indexes `.env` is a credential leak with a search
box.

## 5. Guardian and privacy

- Indexing reads only paths under configured sources; `kb_sources add`
  outside `$HOME` or on a network mount → escalate.
- `kb_ask` on `sensitive` documents routes to `[cognition]
  sensitive_provider`; if that is unset and the primary is cloud, the
  tool answers with passages only ("here is what your documents say")
  and no synthesis -- extraction without exposure.
- Mail archive bodies default `sensitive`; subjects/senders `personal`.
- No document text enters `notify`.

## 6. Automations and monitors

- `new_document` percept → optional rule ("a new PDF in ~/Scans →
  summarise and tag").
- Monitors: `index_stale` (source not scanned in 2× interval),
  `ocr_backlog`, `parse_failures` (> 5% of a source), `duplicates`
  (weekly digest line).
- Digest section: documents added, top duplicates, sources failing.

## 7. Tests

- Parser fallbacks: Docling absent → PyMuPDF → plaintext; each yields
  chunks with page numbers; a scanned PDF with OCR off yields a
  `needs_ocr` status, never an empty success.
- Chunking keeps a table in one chunk; heading path is right.
- Hybrid retrieval: a query matching only lexically and one matching
  only semantically both hit; RRF order is deterministic.
- Incremental: an unchanged file is skipped by sha; a moved file keeps
  its chunks; a deleted file is tombstoned.
- `kb_ask` cites; with no hits says "not in your documents"; sensitive
  routing.
- Credential-looking paths never indexed.
- End-to-end: a `FakeCorpus` of 20 files → `KB_ASK` through the marker
  path → cited answer.

## 8. Build order and acceptance

1. Index + files source + plaintext/PyMuPDF + FTS5 + `kb_search`.
   Acceptance: ~/Documents indexed; a known phrase found with its page.
2. Vector + hybrid + `kb_ask` with citations. Acceptance: three
   paraphrased questions answered from the right document.
3. Docling + OCR + office formats. 4. Watcher + incremental + monitors.
5. Paperless/mail-archive/web-clip sources. 6. Reranker, summaries,
   duplicates.

## 9. Traps

- PDF text order is wrong without a layout parser; two-column papers
  interleave. Docling fixes it; the fallback should at least sort by
  y then x.
- Embedding 50k chunks with a cloud embedder costs real money; the
  design pins `local` and refuses cloud embedding above
  `cloud_embed_max_chunks` without confirmation.
- FTS5 tokenizer: use `unicode61 remove_diacritics 2`; porter stemming
  breaks names.
- `watchdog` on macOS with many files needs `FSEvents`; on network
  mounts use polling.
- Never index `~/Library`, browser profiles, or the Sim ledger itself.
