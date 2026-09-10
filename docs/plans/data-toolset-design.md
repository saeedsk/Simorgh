# Data toolset: fast, inline, and complex database use

Design pass, 2026-09-09 (Fable). Implementation is handed to a cheaper
model; this document is written so that nothing below requires a design
decision. Where a choice was open, it is made here and the reason given.
Follow `docs/plans/resourcefulness-toolset.md`'s five invariants and its
ten-step wiring checklist for every tool -- that checklist is where five
tools silently broke last time.

## 0. What was measured, and what it means

Three facts, all checked against the running code rather than assumed:

1. **The model cannot see its own data.** A data tool's rows go to
   `results/<action_id>.json` (`results_max_rows = 500`, pruned at
   `results_keep_files = 50`). 500 listing rows is **115,390 chars**;
   `read_file` cuts a result at 8,000. To answer "median price per sqft
   in 95120", Sim must write a pandas program and run it through
   `run_script`. Every question is a program.
2. **Guardian cannot tell a read from a write.** Five samples run
   through the real `DEFAULT_PIPELINE` as `run_script` code -- `sqlite3`
   on a local file, `pandas.read_json`, a DuckDB `count(*)`, a
   SQLAlchemy Postgres connect, a raw `psycopg` connect -- ALL produced
   `needs_human / reversibility`, identical. Guardian reads Python, not
   SQL: `SELECT count(*)` on a local file and `DROP TABLE` on production
   are the same thing to it. `_CODE_ARG_KEYS = ("code", "command")`, so
   an argument named `sql` is invisible to every content rule.
3. **Installed:** `sqlite3`, `pandas`, `sqlalchemy`, `pyarrow` (the Ledger
   already has a sqlite backend). **Absent:** `duckdb` (1.5.5 on PyPI),
   `polars`, `psycopg`, `asyncpg`.

So the gaps are: no cheap path for a harmless read; no specific guard
for a dangerous write; and nothing tells the model what data exists.

## 1. Tools, in build order

| # | tool | arg shape | reversibility | key needed | one-line purpose |
|---|---|---|---|---|---|
| A  | `query_data`    | `sql` | `read_only`   | none | SQL over local files, inline, no gate |
| A' | `describe_data` | `target?` | `read_only` | none | what datasets/tables exist, with schemas |
| C  | `db_query`      | `connection` + `sql` | `read_only` / `irreversible` | per connection | named remote database |
| B  | `db_exec`       | `path` + `sql` | `reversible` | none | persistent local sqlite in `workspace/` |

Plus one Guardian change (section 5) that B and C both depend on. Build
it before C.

Three modules, all under `simorgh/execution/`:

- `sqlsafety.py` -- statement classification. Pure functions, no I/O,
  shared by all four tools AND by Guardian's `SqlRule`. Guardian may not
  import Execution (`tests/simorgh/test_module_boundaries.py`), so this
  is the one file that goes in `simorgh/contracts/` instead:
  **`simorgh/contracts/sqlsafety.py`**. Contracts is importable by
  everyone. Keep it dependency-free.
- `localdata.py` -- A, A', B.
- `databases.py` -- C.

## 2. `simorgh/contracts/sqlsafety.py`

```python
Kind = Literal["read", "write", "ddl", "dangerous", "multi", "unknown"]

@dataclass(frozen=True)
class Statement:
    kind: Kind
    verb: str            # first keyword, upper-cased: SELECT, INSERT, DROP...
    reason: str = ""     # for dangerous/multi/unknown: why

def classify(sql: str) -> Statement: ...
def is_read_only(sql: str) -> bool: ...   # classify(sql).kind == "read"
def strip_comments(sql: str) -> str: ...
```

Rules for `classify`, in order:

1. `strip_comments` removes `-- ...` to end of line and `/* ... */`.
   A classifier that reads the comment `-- SELECT` and then runs
   `DROP` has been fooled; strip first, then look.
2. Split on `;` outside quotes. **More than one statement → `multi`.**
   One statement at a time, always: the whole point of classification
   is that the verdict applies to what runs, and `SELECT 1; DROP TABLE x`
   is not a read. A trailing `;` is fine.
3. Leading `WITH ... ` (a CTE): skip to the main verb after the CTE
   body. A CTE can wrap an INSERT/UPDATE/DELETE in every dialect that
   matters, so `WITH` alone proves nothing.
4. First keyword decides:
   - `read`: `SELECT`, `EXPLAIN`, `DESCRIBE`, `DESC`, `SHOW`, `PRAGMA`
     (read-only pragmas only: `table_info`, `table_list`, `index_list`,
     `foreign_key_list`, `schema_version`; any other PRAGMA is `write`),
     `VALUES`, `TABLE`.
   - `write`: `INSERT`, `UPDATE`, `DELETE`, `REPLACE`, `MERGE`,
     `UPSERT`, `COPY ... FROM`.
   - `ddl`: `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `RENAME`, `VACUUM`,
     `ATTACH`, `DETACH`, `INSTALL`, `LOAD`.
   - anything else → `unknown`. Unknown is refused by every tool.
     Never guess.
5. `dangerous` overrides `write`/`ddl` when:
   - `DROP` or `TRUNCATE` of anything;
   - `DELETE FROM x` or `UPDATE x SET ...` with no `WHERE` (the whole
     table);
   - `ALTER ... DROP COLUMN`;
   - `ATTACH`/`INSTALL`/`LOAD` (DuckDB/sqlite can load extensions and
     other files -- this is a way out of the sandbox);
   - `COPY ... TO` / `INTO OUTFILE` / `EXPORT` (writes a file the path
     tools never see);
   - `read_file`/`read_csv`/`read_json`/`read_parquet`/`glob`/
     `read_text` **called with a path outside the readable roots** --
     but path validation is the tool's job (it has the config); the
     classifier only reports the paths it finds, see `referenced_paths`.

```python
def referenced_paths(sql: str) -> tuple[str, ...]:
    """Every string literal that looks like a file path: contains '/'
    or ends in .json/.csv/.parquet/.db/.sqlite/.txt/.jsonl, or is a
    bare-word table reference ending in one of those suffixes (DuckDB
    accepts `from 'results/a.json'` AND `from results/a.json`)."""
```

Tests (`tests/simorgh/contracts/test_sqlsafety.py`), each a one-liner
table; the ones that matter most are the ones that would let a write
through as a read:

- `-- SELECT\nDROP TABLE x` → dangerous, not read.
- `/* select */ delete from t` → dangerous (no WHERE).
- `SELECT 1; DROP TABLE x` → multi.
- `WITH c AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT * FROM c)` →
  write (has WHERE), NOT read.
- `with c as (select 1) select * from c` → read.
- `select * from 'results/a.json'` → read, `referenced_paths ==
  ("results/a.json",)`.
- `select * from read_csv('/etc/passwd')` → read, paths ==
  ("/etc/passwd",) -- the TOOL refuses this, the classifier just
  reports it; a test in `test_localdata.py` proves the refusal.
- `pragma table_info(t)` → read; `pragma journal_mode=wal` → write.
- `explain select 1` → read.
- `COPY t TO 'out.csv'` → dangerous.
- `INSTALL httpfs` → dangerous.
- `SELECT` with a quoted `';'` inside a string → single statement.
- empty / whitespace → unknown.

## 3. `simorgh/execution/localdata.py` -- A, A', B

### 3.1 Engine choice, decided

DuckDB when importable, else sqlite3 + pandas. **Optional dependency,
guarded import** (the boundary test requires the `try/except
ImportError`). Both paths must pass the same tests; parametrise the
test class over `engine in ("duckdb", "sqlite")` and skip the duckdb
half when it is absent -- do not make CI depend on it.

Why DuckDB first: it reads `results/*.json`, `*.csv`, `*.parquet` and
`*.db` directly from SQL with no load step, it is in-process, and it is
one `pip install duckdb`. The fallback exists so the tool works on a
machine that never runs that install: it loads the referenced file(s)
with pandas into an in-memory sqlite via `DataFrame.to_sql`, names the
table after the file stem, and rewrites the quoted path in the SQL to
that table name. That rewrite is the ugly part; keep it in one function
`_sqlite_rewrite(sql, mapping) -> str` with its own tests, and accept
that the fallback supports `FROM 'path'` and `JOIN 'path'` and nothing
fancier. Say so in the tool's error when the SQL needs more.

Add a capability probe (`capabilities.py::PROBES`): `Probe("duckdb",
"free", _duckdb, tools=("query_data",))` -- import check only.

### 3.2 `QueryDataTool` (A)

```python
class QueryDataTool:
    name = "query_data"
    description = ("Run a read-only SQL query over local data files -- results/*.json, "
                   "workspace/*.csv|parquet|json|db -- and get a table back. "
                   "SELECT only; no gate, no program to write.")
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["sql"],
                   "properties": {"sql": {"type": "string"},
                                  "max_rows": {"type": "integer"}}}

    def __init__(self, config: Config, *, engine: str | None = None) -> None: ...
    async def run(self, args, *, ctx) -> ToolResult: ...
```

`run`, in order -- **every refusal before any I/O**:

1. `sql` empty → `refused: no SQL given`.
2. `classify(sql)`: kind must be `read`. Otherwise
   `refused: query_data is read-only and this is a <kind> (<verb>); use db_exec for a local write, db_query for a remote database`.
   This is what makes `read_only = True` TRUE. The honesty rule
   (`project_honesty_rules`): a tool must not claim a property it does
   not enforce.
3. Every path in `referenced_paths(sql)` must resolve via
   `pathsafety.resolve_safe_path(repo_root, path, readable_roots=
   config.readable_roots)` -- that is the same boundary `read_file`
   uses, so `read_csv('/etc/passwd')` and `'../secrets.db'` are refused
   with pathsafety's own message. Also refuse a path that
   `looks_like_credential_path`. **This is the only reason a
   `read_only` tool can safely skip Guardian: it cannot read anything
   `read_file` could not.**
4. Run in a thread (`asyncio.to_thread`) under
   `asyncio.wait_for(config.query_data_timeout_s)`. DuckDB:
   `duckdb.connect(":memory:")`, then
   `conn.execute("SET enable_external_access = true")` is the default
   -- leave it, we validated paths ourselves -- but
   `SET lock_configuration = true` after setting
   `SET disabled_filesystems = 'HTTPFileSystem'` and
   `SET autoinstall_known_extensions = false; SET autoload_known_extensions = false`.
   Those three lines are the sandbox; test that `select * from
   'https://x/y.csv'` is refused (the classifier catches `https://` as a
   non-local path first, but the engine setting is the second wall).
5. Fetch at most `max_rows` (default `config.query_data_max_rows =
   500`, hard cap 5000) plus one, so "truncated" is known honestly.
6. Output: a rendered table (`_render_table`, below), capped at
   `config.query_data_output_max_chars = 8000`. Metadata: `{"rows":
   [...dicts...], "columns": [...], "row_count": n, "truncated": bool,
   "engine": "duckdb"|"sqlite", "duration_s": ...}`. **`rows` in
   metadata is what makes `_store_rows` write `results/<id>.json`** --
   so a query's result is itself queryable. Say the path in the output
   (service does that already).
7. Errors from the engine are results, not crashes: `ok=False,
   error=f"query failed: {exc}"` with the engine's message intact --
   the model needs the column name it got wrong.

`_render_table(columns, rows, *, max_chars)`: fixed-width columns,
`|`-separated, header + rule line, numeric right-aligned, cell values
cut at 40 chars with `…`, and a final line `N rows (M shown)` when cut.
No box-drawing characters (the TUI width rule in `project_tui_width`
applies to narration, not tool output, but a table wider than the
terminal wraps unreadably -- so also cap the row width at 200 chars).

### 3.3 `DescribeDataTool` (A')

Without this, A is an unconnected wire: the model cannot query what it
does not know exists.

```python
class DescribeDataTool:
    name = "describe_data"
    description = "List the local datasets you can query -- results/, workspace/ -- with their columns; or describe one file/table."
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "properties": {"target": {"type": "string"}}}
```

- No `target`: walk `results_dir` and `workspace_dir` (readable roots
  only), list files with suffix in `.json .jsonl .csv .parquet .db
  .sqlite`, newest first, capped at 50, each as
  `results/a1.json   500 rows   12 cols   2m ago   address, city, zip_code, price, …`.
  Row count for JSON/CSV: read it (files are small by construction);
  for `.db`: list tables with `sqlite_master` and per-table
  `count(*)`. Use the same engine as A.
- `target` a file: columns with inferred types and 3 sample rows.
- `target` a `.db`: tables, each with columns and row count.
- `target` outside readable roots: pathsafety's refusal.
- Never opens anything not in the two data directories, even though
  `readable_roots` is wider -- a `describe_data simorgh/` would list
  source files as "datasets", which is noise, not a capability.

Output when empty: `no datasets yet -- a search_listings, web_fetch table, or
query_data result will appear here`. Say what would make one, not just
"none".

### 3.4 `DbExecTool` (B)

Persistent local store: sqlite files under `workspace/`.

```python
class DbExecTool:
    name = "db_exec"
    description = ("Run SQL that changes a local sqlite database under workspace/ "
                   "(CREATE, INSERT, UPDATE, DELETE...). The file is snapshotted first, "
                   "so a bad statement can be reverted.")
    read_only = False
    reversibility = "reversible"
    args_schema = {"type": "object", "required": ["path", "sql"],
                   "properties": {"path": {"type": "string"}, "sql": {"type": "string"}}}
```

- `path` must be under `workspace_dir` (`pathsafety.in_write_scope`
  with `("workspace/",)` only -- NOT the full `write_scopes_source`;
  a `.db` in `simorgh/` is source pollution) and end in `.db` or
  `.sqlite`. Created if absent.
- `classify(sql)`: `read` is allowed too (a convenience; result is the
  table, same as A) -- but `dangerous`, `multi`, `unknown` are refused
  with the reason. `DROP TABLE` on a scratch db IS allowed? **No.**
  Decided: refuse `dangerous` here too. The workspace is scratch, but
  "delete this table" is exactly the accident a snapshot exists to
  undo, and refusing costs one extra `db_exec` with a WHERE. Keep one
  rule, not two.
- **Snapshot before write**: copy `<path>` to
  `<path>.bak-<action_id>` (in the same directory) before executing
  any non-read statement; keep the last `config.db_exec_snapshots = 5`
  per db, delete older. This is what makes `reversible` honest --
  `side_effects=("file_write:<path>", "db_snapshot:<bak>")`. The bak
  path also goes in metadata. (`git_discard` cannot restore a
  gitignored file; the snapshot is the whole revert story, so a
  `db_exec` with `sql = "RESTORE"` -- a literal keyword this tool
  handles itself, not SQL -- copies the newest `.bak-*` back. Test it.)
- `workspace/` is scratch per `session.py::is_scratch`, so a `.db`
  write never blocks a finished task and cleanup never deletes it.
  That already works; add one test in `test_scratch_workspace.py`
  that a `file_write:workspace/x.db` effect lands only in `wrote`.
- Run with `sqlite3` directly (no DuckDB; a DuckDB-written file is not
  a sqlite file, and A reads sqlite fine). `isolation_level=None` with
  explicit `BEGIN`/`COMMIT` around the one statement; timeout
  `config.db_exec_timeout_s = 30`.
- Output: `ok: N rows affected` for writes; the table for reads.

## 4. `simorgh/execution/databases.py` -- C

### 4.1 Connections are named by the operator, never by the model

```toml
[execution.databases.analytics]
url = "env:ANALYTICS_DB_URL"        # or a literal for sqlite: "sqlite:///workspace/x.db"
allow_write = false                  # default
read_only_role = true                # ask the engine for a read-only transaction
timeout_s = 60
max_rows = 1000
description = "warehouse replica, nightly"   # shown to the model by describe_data
```

`Config.databases: dict[str, DatabaseSpec]` (a frozen dataclass:
`name, url_source, allow_write, read_only_role, timeout_s, max_rows,
description`). `url_source` is the raw string; **resolution to a real
URL happens once, at tool construction, inside the tool, and the
resolved URL is stored on a private attribute that nothing ever
serialises.** `env:NAME` reads `os.environ[NAME]`; a missing variable
makes the connection *present but unavailable*, and the tool says
exactly which variable to set. Same shape as `notify.PROVIDERS`.

Why names: the same reason `run_remote` has no `host` argument. A
`db_query` that took a URL is a tool that will, on the day the model is
prompt-injected by a web page, connect this machine to
`postgresql://attacker/…` carrying whatever it was told to `INSERT`.
Naming makes every destination something a person typed into config.

### 4.2 `DbQueryTool`

```python
class DbQueryTool:
    name = "db_query"
    description = ("Query a database this system is configured for, by name (see describe_data "
                   "for the list). Read-only unless the connection allows writes; you cannot "
                   "name a database that is not configured.")
    read_only = False                      # see 4.3 -- decided dynamically per call
    reversibility = "irreversible"         # the conservative declaration; Guardian relaxes for reads
    args_schema = {"type": "object", "required": ["connection", "sql"],
                   "properties": {"connection": {"type": "string"}, "sql": {"type": "string"},
                                  "max_rows": {"type": "integer"}}}
    def __init__(self, config: Config, *, env=None, engine_factory=None) -> None: ...
```

`run`, in order:

1. `connection` must be a configured name, else
   `refused: no database named 'x'; configured: a, b, c` (names only,
   never URLs). Empty config → `refused: no databases are configured
   -- add [execution.databases.<name>] to simorgh.toml`.
2. Connection present but its env var unset →
   `refused: database 'analytics' needs ANALYTICS_DB_URL in the environment`.
3. `classify(sql)`: `multi`/`unknown` refused always. `read` always
   allowed. `write`/`ddl` allowed only when `spec.allow_write`;
   `dangerous` refused **always, even with allow_write** -- a
   `DROP TABLE` on a remote database is not something an autonomous
   loop gets to do through this tool; a human with `psql` can.
4. Driver: SQLAlchemy `create_engine(url, pool_pre_ping=True,
   connect_args={"connect_timeout": ...} where the dialect supports it)`
   -- SQLAlchemy is installed; the DBAPI driver may not be
   (`psycopg`, `pymysql`). Catch `ModuleNotFoundError` from
   `create_engine` and answer
   `refused: database 'analytics' needs the psycopg package (install_package pip psycopg[binary])`
   -- naming the package is what makes the resourceful path work.
   `engine_factory` is injected for tests; no test opens a real socket.
5. For a `read` on a connection with `read_only_role`: wrap in
   `BEGIN` + dialect-specific read-only (`SET TRANSACTION READ ONLY`
   on postgres/mysql; sqlite gets `PRAGMA query_only = 1`). Belt and
   braces with step 3.
6. `asyncio.wait_for(to_thread(...), spec.timeout_s)`; statement
   timeout at the engine too where supported
   (`options=-c statement_timeout=…` for postgres).
7. Reads: same rendering and `rows` metadata as A. Writes: `N rows
   affected`, `side_effects=(f"db_write:{name}",)` -- the tool cannot
   undo it and says so in metadata (`"remote": True, "note": "ran on
   an external database; nothing here can revert it"`), exactly as
   `run_remote` does.
8. **Never** include the URL, the env var's value, or the driver's
   full exception (which often echoes the DSN) in output or metadata.
   Log the exception class and the first line; strip anything matching
   `://[^@]*@`. Test: a failing connect with a URL containing
   `secret` yields an error without `secret` in it.

Capability probe: none at boot (a probe that connects to production is
not a probe). `describe_data` with no target also lists configured
connections: `db: analytics  (warehouse replica, nightly)  read-only  ready`
or `… needs ANALYTICS_DB_URL`.

### 4.3 What Guardian sees for `db_query`

`reversibility = "irreversible"` on the class is the honest static
declaration. But a `SELECT` gated by `irreversible_requires_human` is
the thing that makes the model route around the tool through
`run_script`, which is the outcome the whole layer exists to prevent.
So `orchestration/tools.py::to_action_payload` sets the proposal's
`reversibility` **per call**:

```python
if tool == "db_query":
    kind = classify(args.get("sql", "")).kind
    reversibility = "read_only" if kind == "read" else "irreversible"
```

and `_TOOL_POLICY["db_query"] = ("irreversible", True)` stays as the
default the table shows. Orchestration importing `contracts.sqlsafety`
is allowed (contracts is shared). Guardian then does the right thing
with no new rule -- and `SqlRule` (section 5) independently re-checks
the same SQL, so a mis-tagged payload cannot get a write through as a
read: Guardian never trusts the proposer's label.

## 5. Guardian: `sql` becomes visible, and `SqlRule`

### 5.1 `_CODE_ARG_KEYS`

`("code", "command")` → `("code", "command", "sql")`. Consequences to
check, each with a test in `tests/simorgh/guardian/`:

- `DenylistRule` now scans SQL text for its Python patterns. That is
  harmless (SQL rarely contains `subprocess.run`) but means a query
  whose string literal contains `socket.` would be denied -- accept
  it; note it in the rule's docstring.
- `StaticAnalysisRule` `ast.parse`s the text and abstains on a
  SyntaxError -- SQL is a SyntaxError in Python, so it abstains. Fine.
- `ProtectedRule`'s write-scan: `_looks_like_a_write` on SQL text
  will not match Python write idioms. Fine. But `_mentioned_paths`
  will now see `'results/a.json'` -- and results/ is not protected.
  Fine. Test that `select * from 'simorgh.toml'` is DENIED by
  ProtectedRule (a read of a protected file through SQL) -- if it is
  not, the tool's own pathsafety check is the only wall; that is
  acceptable but the test documents which it is.
- `ShellcheckRule` reads only `command`. Unaffected.

### 5.2 `SqlRule`

Position in `DEFAULT_PIPELINE`: **after `DenylistRule`, before
`StaticAnalysisRule`** (cheap, pure, first-deny-wins).

```python
class SqlRule:
    """The SQL half of what DenylistRule is for Python and
    ShellcheckRule for shell: the few statements that mean "this
    destroys something you did not mean to destroy". Pure, no I/O,
    reads `args["sql"]` only."""
    name = layer = "sql"

    async def evaluate(self, proposal, ctx) -> Decision:
        if not ctx.config.sql_rule_enabled: return abstain
        sql = proposal.args.get("sql")
        if not isinstance(sql, str) or not sql.strip(): return abstain
        st = classify(sql)
        if st.kind in ("multi", "unknown"):
            return deny(f"denied: {st.reason}")
        if st.kind == "dangerous":
            return deny(f"denied: {st.verb}: {st.reason}")
        if proposal.tool == "query_data" and st.kind != "read":
            return deny("denied: query_data is read-only")      # second wall behind the tool's own
        if st.kind in ("write", "ddl") and proposal.tool == "db_query":
            return Decision("escalate", self.layer, (f"{st.verb} on an external database",))
        return Decision("abstain", self.layer, (f"sql {st.kind}: {st.verb}",))   # a note, per e80fec0
```

`GuardianConfig.sql_rule_enabled: bool = True`. Wire it in
`[guardian]` like `shellcheck_enabled`.

Note the asymmetry rule from `project_honesty_rules`: a guard that
cannot classify **denies**; it never abstains on `unknown`.

## 6. Orchestration wiring (the ten steps, per tool)

| step | query_data | describe_data | db_exec | db_query |
|---|---|---|---|---|
| `builtin_tools` | always | always | always | always (refuses if unconfigured) |
| `_TOOL_POLICY` | `("read_only", False)` | `("read_only", False)` | `("reversible", False)` | `("irreversible", True)` + per-call override (4.3) |
| `_MARKER_ARG_KEY` | `"sql"` | `"target"` | -- | -- |
| `_MARKER_SPLIT_FIRST_LINE` | -- | -- | `("path", "sql")` | `("connection", "sql")` |
| `_CODE_BEARING_MARKERS` | `QUERY_DATA` | -- | `DB_EXEC` | `DB_QUERY` |
| `_MARKER_ARG_HINT` | yes (below) | short | yes | yes |
| `_TOOL_NOTES` | yes | yes | yes | yes |
| `_ACTION_TIMEOUTS` | 45 | 20 | 45 | 90 |
| profiles | PATCH, RESEARCH | PATCH, RESEARCH | PATCH | PATCH, RESEARCH |
| `live_status` verb | "Querying" | "Listing data" | "Writing data" | "Querying db" |

Multi-line SQL is the norm (`QUERY_DATA:\nselect …\nfrom …`), which is
exactly the truncation that broke five tools -- the parser test in
`test_tools_router.py::TestNotifyMarkerReachesTheTool` is the template;
copy it per tool.

Hint for `query_data` (the one the model will get wrong otherwise):

> every line after the marker is one SQL SELECT. Query a file by its
> path in quotes: `select zip_code, avg(price) from 'results/a1.json'
> group by 1`. Only SELECT/WITH/EXPLAIN; only files under results/ and
> workspace/. Run describe_data first to see what exists. Not for a
> remote database -- that is db_query, by connection name.

Scaffold: the RESEARCH and PATCH scaffolds' "when you have data" line
should say: *"a tool that fetched rows wrote them to results/; query
them with QUERY_DATA rather than reading the file or writing pandas."*
One sentence; a test asserts it is present, as `_KEYLESS_SOURCES` does.

## 7. Config fields (`execution/config.py`)

```python
# -- query_data / describe_data / db_exec (localdata.py)
query_data_engine: str = "auto"          # auto | duckdb | sqlite
query_data_timeout_s: float = 30.0
query_data_max_rows: int = 500
query_data_output_max_chars: int = 8000
db_exec_timeout_s: float = 30.0
db_exec_snapshots: int = 5
# -- db_query (databases.py); see the module docstring for the TOML shape
databases: tuple[DatabaseSpec, ...] = ()
```

`Config.from_mapping` must parse `[execution.databases.<name>]` tables
into `DatabaseSpec`s. `kernel/configcheck.py`'s dead-field probe: make
sure these are all READ (the `project_unconnected_wires` pattern --
twelve subsystems already ignore their config).

## 8. Tests that are not optional

Beyond the per-module unit tests implied above:

- `tests/simorgh/integration/test_data_tools_end_to_end.py`: boot a
  real Kernel, run `search_listings` with an injected scraper (30 rows)
  → `QUERY_DATA: select count(*) from 'results/<id>.json'` through the
  whole marker→Guardian→Execution path → assert `30`. Then
  `describe_data` lists the file. Then `DB_EXEC: workspace/t.db\ncreate
  table …` → `insert` → `query_data` over the `.db` → snapshot exists.
  This is the test that proves the wire is connected; unit tests only
  prove shape (`feedback_why_tests_missed_it`).
- Guardian: a `db_query` proposal with `sql = "DROP TABLE x"` and
  `reversibility = "read_only"` (a lying proposer) is **denied by
  SqlRule**, not approved.
- Boundary test still passes (contracts placement; guarded duckdb
  import).
- `TestBuiltinTools` exhaustive set updated: `query_data`,
  `describe_data`, `db_exec`, `db_query`.
- No test opens a network socket or reads outside a tempdir.

## 9. Acceptance trial (run with `tools/trial.py`, one task)

Task: *"Using the 95120 listings already in results/, tell me the
median price per sqft by number of bedrooms, and save the table to the
workspace."* Passes when the session uses `describe_data` →
`query_data` → `db_exec` (or a workspace write) and **never**
`run_script`, and the answer's numbers match a pandas computation done
by hand in the trial's checker. Record the step count; the point of
this whole toolset is that it should be ≤ 5 steps where today it is
10+ and a program.

## 10. Traps, so they are not rediscovered

- `results/` is readable-not-writable; `workspace/` is both. A
  `db_exec` path under `results/` must be refused, not silently
  redirected.
- DuckDB's `read_json` auto-detects; a `results/*.json` written by
  `_store_rows` is a JSON **array**, which DuckDB reads with
  `read_json_auto` / bare `'path'`. jsonl also works. Test both.
- A DuckDB-created `.db` is not sqlite. B writes sqlite only; A reads
  sqlite via DuckDB's sqlite scanner **only if the extension is
  installed**, which `autoinstall_known_extensions = false` forbids. So
  A reading a `.db` must go through `sqlite3` + pandas regardless of
  engine. Route `.db`/`.sqlite` targets to the sqlite path always.
- `pandas.to_sql` needs a table name that is a valid identifier: derive
  from the file stem, replace non-`[A-Za-z0-9_]` with `_`, prefix `t_`
  if it starts with a digit. Collisions between `a-1.json` and
  `a_1.json` → refuse with both names, do not pick one.
- The `rows` metadata key is what triggers `_store_rows`; a query
  result therefore lands in `results/` and is pruned at 50 files. That
  is intended (a query is cheap to re-run). Do not add a second
  storage path.
- Statement timeout ≠ connect timeout. Set both for remote.
- `describe_data` counting rows of a 5,000-row CSV is fine; of a
  500 MB parquet is not -- use `pyarrow.parquet.read_metadata` for
  parquet row counts and cap CSV/JSON row counting at the file size
  `config.query_data_describe_max_bytes = 20_000_000`, above which say
  `>N rows (large)`.
