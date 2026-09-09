# Resourcefulness toolset: detailed designs

Companion to `resourcefulness-toolset.md` (the plan). That file says
*what* and *why*; this one says *exactly how*, per workstream, so the
implementing session writes code and tests without making design
calls. Written 2026-09-09 against the code at `aaaf57d`. Every path and
name below was read in that checkout; if one has moved, the surrounding
description says what it does, so find it by role.

Conventions used throughout:

- **Tool template** = the ten-step wiring checklist in the plan,
  section 2. "Wire per template" means all ten steps.
- **Refusal** = `ToolResult(ok=False, error="refused: <reason>")` with
  nothing done. **Failure** = the tool ran and reports why it failed.
- **Guardian-visible string**: Guardian's `DenylistRule`/
  `StaticAnalysisRule` read only `args["code"]` and `args["command"]`
  (`guardian/rules.py::_CODE_ARG_KEYS`). A tool whose danger lives in a
  list or a JSON object must *also* put a joined, human-readable string
  in `command` before it is proposed, or Guardian is blind to it.
- Tests live beside the existing ones: `tests/simorgh/execution/
  test_<module>.py`, `tests/simorgh/guardian/test_rules.py`,
  `tests/simorgh/verification/checks/test_<check>.py`. Each new tool's
  test module has (a) unit tests with the I/O boundary injected and
  (b) one real smoke test that `skipTest`s cleanly when the dependency,
  binary, daemon or network is absent.

---

## 0. Cross-cutting pieces (build these first; several workstreams use them)

### 0.1 New topics and schemas

`simorgh/contracts/topics.py` gains:

```python
TOOL_UNREGISTERED = "tool.unregistered"        # payload: {name, provider, reason}
CAPABILITY_GRANTED = "capability.granted"      # payload: {grant_id, kind, name, tools:[str], reversibility, granted_by_task, reason}
CAPABILITY_REVOKED = "capability.revoked"      # payload: {grant_id, name, tools:[str], reason}
CAPABILITY_PROBED = "capability.probed"        # payload: {name, ok, detail, cost, at}
```

One schema file each under `simorgh/contracts/schema/`, named
`<topic>.v1.json`, copying `tool.registered.v1.json`'s shape
(`additionalProperties: true` is the project convention -- keep it).
All four are published by `execution` (`CAPABILITY_PROBED` also by
`kernel`); add them to the bus policy where `tool.registered` is
allowed (`grep -rn "tool.registered" simorgh/bus simorgh/contracts`).
`Service.produces` tuples in `execution/service.py` and
`kernel/*` list them.

Subscribers to `TOOL_UNREGISTERED`: `orchestration/service.py`
(remove from `_TOOL_POLICY`/`_MARKER_ARG_KEY` via a new
`unregister_tool_policy(name)` in `orchestration/tools.py`; also drop it
from any runtime-offered tool list), `guardian/service.py` (drop the
`ToolInfo` from its tools projection), `interface` (footer/`tools`
listing). Replay: `orchestration/service.py::_replay_registrations`
must apply `unregistered` events from `TOOLS_STREAM` after
`registered` ones so a revoked tool does not come back on restart.

### 0.2 Metadata persistence and large-result hand-back (WS10 core)

Today `Execution._publish_result` (execution/service.py, the
`payload = {"action_id", "ok", "output_ref", "stdout_preview", ...}`
builder) stores only the output text as a blob and a preview; a tool's
`ToolResult.metadata` is dropped except for a few hand-picked
`web_fetch`/`propose_mcp_server` fields.

Build:
- `metadata_ref`: JSON-encode `result.metadata` (`default=str`), store
  with `ledger.put_blob(..., content_type="application/json")`, add
  `"metadata_ref"` to the `action.result` payload and to
  `contracts/schema/action.result.v1.json`. Empty metadata -> `""`.
- Large-result files: if `result.metadata` contains a key named `rows`
  (list) or `file_payload` (str), write it to
  `<data_dir>/results/<action_id>.<json|txt>` and append one line to
  `result.output`: `full data: <path> (<n> rows)`. `read_file` must be
  able to open it: add `<data_dir>/results` to what `pathsafety` treats
  as readable -- simplest is to make `readable_roots` accept an
  absolute path that resolves under `data_dir` (today it refuses every
  absolute path; add the one exception and test it).
- Nothing about `stdout_preview` changes; the model still sees the
  same preview plus the one extra line.

Tests: `tests/simorgh/execution/test_service_results.py` --
`test_metadata_is_persisted_as_a_blob_and_referenced`,
`test_rows_are_written_to_a_results_file_and_named_in_output`,
`test_a_results_file_is_readable_through_read_file`,
`test_empty_metadata_yields_an_empty_ref`.

### 0.3 Verification request carries the written paths

`orchestration/session.py::_put_verify_subject` adds two keys to the
JSON it stores: `"subject": session.subject` and
`"written_paths": sorted(session.uncommitted | session.created)`.
Checks that need a file (WS9) read those, never guess from summaries.
Add `repo_root: Path` to `verification/config.py`'s `VerificationConfig`
(Kernel passes the same root Execution gets) and a helper
`verification/checks/_files.py::read_repo_file(ctx, path) -> str |
None` that calls `execution.pathsafety.read_source(ctx.config.repo_root,
path, readable_roots=(...))` -- uncapped, refusal -> `None`.

Test: `tests/simorgh/orchestration/test_session_verify_subject.py::
test_written_paths_and_subject_travel_with_the_verify_request`.

### 0.4 Two-part markers for multi-argument tools

`orchestration/tools.py::_MARKER_SPLIT_FIRST_LINE` maps a tool to
`(first_line_key, rest_key)`. Add a sibling `_MARKER_JSON_REST:
frozenset[str]` -- tools whose `rest` is a JSON object merged into
`args` (rest empty -> no extra args; rest not a JSON object ->
`{rest_key: rest}` unchanged, so a plain second line still works).
`to_action_payload` handles it right after the split. Register:
`search_listings` (`("location", "filters")`, JSON), `browse_page`
(`("target", "actions")`), `run_container` (`("image", "spec")`),
`grant_capability` (`("kind", "spec")`), `install_package`
(`("manager", "spec")`). Update each tool's `_MARKER_ARG_HINT` entry
with a two-line example. `_TOOL_NOTES` lines say "first line X, then
JSON".

Tests in `tests/simorgh/orchestration/test_tools_router.py`:
`test_a_json_rest_marker_merges_into_args`,
`test_a_non_json_rest_stays_a_plain_string`,
`test_an_empty_rest_adds_nothing`.

### 0.5 Interface commands

`interface/parser.py` has the known-command tuple (`"status", "tasks",
... "mcp", ...`); `interface/dispatch.py` branches on `command.name`.
New commands (all read the Ledger/bus, none write except where noted):
`capabilities` (list grants), `capability promote <name>
<read_only|reversible>` (human-only loosening -- writes `grants.toml`
through Execution via a `capability.promote` request, not directly),
`capability revoke <name>`, `capability check` (D4 probes on demand),
`packages` (list `simorgh_packages.txt`). Add each to the parser tuple,
the `help` text, and `_VERBS` where a verb is shown. Tests in
`tests/simorgh/interface/test_dispatch.py`, one per command, using the
existing fake-bus responder pattern.

---

## WS1. `find_package` and `install_package`

### `execution/packages.py::FindPackageTool`

- `name = "find_package"`, `read_only = True`, `reversibility =
  "read_only"`, network.
- `args_schema`: `{"query": str (required), "manager": "pypi"|"npm"|"any" (default "any")}`.
  Marker: single arg `query`.
- Behaviour: exact-name lookups first --
  `GET https://pypi.org/pypi/<name>/json` and
  `GET https://registry.npmjs.org/<name>` (both keyless; through
  `netsafety.validate_public_http_url` + a 10s timeout; `opener=`
  injectable). Extract: name, summary/description, latest version,
  latest release date (PyPI: `max(upload_time)` over
  `releases[version]`; npm: `time[dist-tags.latest]`), first release
  date (PyPI: earliest upload_time across all releases; npm:
  `time.created`), homepage/repository, licence, weekly downloads if
  cheap (npm: skip; PyPI: skip -- no keyless endpoint worth the call).
  If the exact name 404s on both, fall back to `WebSearchTool` with
  `f"{query} site:pypi.org OR site:npmjs.com"` and return its results
  labelled "not an exact package name -- candidates:".
- Output: one block per hit: `pypi homeharvest 0.8.18 (latest
  2026-08-30, first 2023-10-02) MIT -- "Real estate scraping ..."
  https://github.com/...`. Metadata: `{"hits": [{...}]}`.
- Edge cases: PyPI's JSON can be several MB for big packages -- cap
  the read at 2 MB and parse only `info` + release keys; a name with a
  `/` is npm-scoped, never sent to PyPI; a name failing
  `^[A-Za-z0-9][A-Za-z0-9._@/-]{0,127}$` is refused.

### `execution/packages.py::InstallPackageTool`

- `name = "install_package"`, `read_only = False`, `reversibility =
  "irreversible"` (environment change + network; Guardian gates it
  exactly like `run_shell`).
- `args_schema`: `{"manager": "pip"|"npm" (required), "spec": str
  (required; `name`, `name==1.2`, `name@1.2`, `@scope/name`),
  "allow_new": bool (default false), "reason": str}`.
  Marker: two-part (`manager` first line, `spec` rest; rest may be
  JSON with `spec`/`allow_new`/`reason`).
- Guardian-visible string: the tool's proposal (built in
  `orchestration/tools.py::to_action_payload`) adds
  `args["command"] = f"{manager} install {spec}"` so `DenylistRule`
  sees it; add denylist entries for `pip install -e`, `--pre` only when
  `allow_new`, and any spec containing a URL or a local path
  (`://`, `/`, `file:`) -- refused by the tool too, belt and braces.
- Typosquat guard: `FindPackageTool`'s exact lookup runs first; refuse
  when the package's *first* release is younger than
  `execution.package_min_age_days` (default 30) unless `allow_new`,
  and when there is no homepage/repository *and* `allow_new` is false.
  A lookup failure (network) -> refuse with "could not verify the
  package; retry or pass allow_new".
- Run: `[sys.executable, "-m", "pip", "install",
  "--disable-pip-version-check", spec]` or `[npm, "install", "-g",
  spec]`; `env` = `{"PATH", "HOME"}` from the process env only;
  timeout `execution.package_install_timeout_s` (default 300); stdin
  DEVNULL; output capped at 4000 chars, tail kept (pip's useful line is
  last).
- Audit: append `<iso-date> <manager> <spec> resolved=<version>
  task=<task_id or -> reason="<reason>"` to `<repo_root>/
  simorgh_packages.txt`; append a `packages` ledger event with the
  same fields. The resolved version comes from `pip show <name>` /
  `npm ls -g <name> --json` after install.
- Quota: `execution.max_installs_per_day` (default 10), rolling window
  from the ledger stream.
- Config (execution/config.py): `package_min_age_days: int = 30`,
  `package_install_timeout_s: float = 300.0`,
  `max_installs_per_day: int = 10`, `package_denylist: tuple[str, ...]`
  (names never installed; seed with obvious sudo/escalation helpers).

Tests (`tests/simorgh/execution/test_packages.py`): find -- exact PyPI
hit parsed; npm scoped name routed to npm only; 404 both -> web
fallback labelled; oversized JSON capped. install -- refuses a URL
spec; refuses a young package without `allow_new`; allows with it;
records the audit line and ledger event; nonzero pip exit is a failure
with the tail; quota refuses the 11th; real smoke: `pip install
--dry-run`-style probe skipped without network.

Acceptance: as in the plan WS1.

## WS2. `run_script`

`execution/script.py::RunScriptTool`, `name = "run_script"`,
`reversibility = "irreversible"`, network.

- `args_schema`: `{"code": str (required), "timeout_s": number
  (optional, capped)}`. Marker: single code-bearing arg (add to the
  code-fence-stripping branch and the "everything after the marker is
  the program" hint, next to `run_python_sandboxed`).
- Writes `code` to `<data_dir>/scratch/<action_id>.py` (not the repo:
  no git noise, no readable-roots question), runs `[sys.executable,
  path]` with `cwd=repo_root` (so `import simorgh` works), env `PATH`,
  `HOME`, `PYTHONPATH=<repo_root>`; rlimits as the sandbox
  (`_apply_rlimits`, but memory `execution.script_memory_mb` default
  1024, cpu `script_cpu_seconds` default 120); timeout
  `script_timeout_s` default 180; output capped 8000 chars.
- Guardian: `code` is already visible to `DenylistRule` and
  `StaticAnalysisRule`. Keep the denylist: a script that wants the
  network imports a library that does it (the scaffold says so).
- Scratch retention: keep the last 50 files; older ones deleted at
  tool construction.

Tests: runs a print; `requests.get(` payload is denied *by Guardian*
(integration test through the real pipeline in
`tests/simorgh/integration/`); import of a repo module works; timeout
kills and reports; stdin is DEVNULL.

## WS4. `browse_page`

Extends `execution/render.py`. `RenderPageTool` stays as is;
`BrowsePageTool` (`name = "browse_page"`) shares the driver.

- `args_schema`: `{"target": str, "actions": [ {click: sel} | {type:
  [sel, text]} | {press: key} | {wait: sel | ms} | {screenshot: name} |
  {scroll: px} ], "submit": bool}`. `reversibility`: `"read_only"`
  when `actions` has no `click`/`press`/`type`; else `"reversible"`
  (a click on a public page can post something; Guardian escalates
  only under `irreversible`, and the creator runs auto-approve, so this
  is classification for the record, not a gate -- say so in the
  docstring). Marker: two-part (`target`, JSON `actions`).
- Limits: <= 20 actions; selectors <= 200 chars, no `javascript:`; no
  `evaluate`/arbitrary-JS action -- deliberately absent so Guardian's
  code rules are not bypassed by a JS string inside JSON; `type` text
  <= 2000 chars; a `type` whose text looks like a credential
  (`pathsafety.looks_like_credential_path` on the *selector*, and a
  `password`/`secret`/`token` substring in the selector) is refused --
  Sim never types secrets.
- Driver: the same Node script with an `actions` JSON argv; each
  action awaited with a 10s per-action timeout; `screenshot` writes
  `<data_dir>/screenshots/<action_id>-<name>.png` (path validated to
  that directory) and the result lists the paths. Final payload adds
  `actions_done: int`, `last_error`.
- Output: like `render_page` plus `actions: n/m done` and screenshot
  paths. Metadata: `screenshots: [paths]`.

Tests: refusals (too many actions, bad selector, secret-looking type);
driver argv shape (mock `subprocess.run`); real smoke on a bundled
local form page (`tests/fixtures/form.html`): type + click changes the
visible text; screenshot file exists.

## WS7. Keyless source book and JSON passthrough

- `web_fetch` already passes JSON through untouched:
  `htmltext.looks_like_html` returns False for a body starting with
  `{`/`[`. Add a test that pins this
  (`test_web_fetch_returns_json_bodies_verbatim`) and raise
  `web_fetch_max_bytes` awareness in the output: when a JSON body is
  cut at the cap, append `[json truncated at N bytes -- narrow the
  query]` rather than returning broken JSON silently.
- `docs/sourcebook.md`: one row per source: name, what, example URL,
  auth (none / demo key / key + env var), rate limit, JSON or not.
  Seed: Open-Meteo, Nominatim, Overpass, Wikipedia REST, Wikidata
  SPARQL, arXiv API, Semantic Scholar, Hacker News Firebase, Reddit
  `.json`, SEC EDGAR full-text + submissions, US Census, USGS
  earthquakes, NASA (DEMO_KEY), Open Library, Open Food Facts, GitHub
  REST (60/h anon), PyPI/npm registries, `yfinance` (library,
  unofficial), Open-Elevation, exchangerate.host-style FX (pick one
  that is actually keyless at implementation time and say so).
- `orchestration/scaffolds.py`: a `_SOURCEBOOK` block (<= 12 lines,
  the name + one example URL each) appended to `_RESEARCH` and, when
  `web_fetch` is offered, to `_CHAT`. Generated from a small table in
  `scaffolds.py`, not duplicated prose, so the doc and the prompt stay
  in step (a test asserts every prompt entry appears in
  `docs/sourcebook.md`).

## WS8. Documents and media

New `execution/doctext.py`:

```python
def document_to_text(data: bytes, *, name: str, max_chars: int) -> tuple[str, str]:
    """(text, problem). Dispatch by magic bytes, then extension."""
```

- `.docx` (zip containing `word/document.xml`): `python-docx`
  paragraphs + table cells, tab-separated. `.xlsx` (zip containing
  `xl/workbook.xml`): `openpyxl` read-only, first `doc_sheet_rows`
  (default 200) rows per sheet as TSV, sheet names as headers. `.csv`/
  `.tsv`: stdlib `csv`, same row cap. Images (PNG/JPEG/GIF/WebP magic):
  `Pillow` -> `image <w>x<h> <mode>` + EXIF DateTimeOriginal/Model if
  present; if `pytesseract` is importable *and* `tesseract` is on
  PATH, append OCR text under `--- text (ocr) ---`. Audio: only when
  `execution.audio_transcription = true` and `faster-whisper` is
  importable -- default off; otherwise the problem string says how to
  enable.
- Each optional import is lazy and its absence yields
  `problem="install python-docx to read .docx"` -- `read_file`
  returns that string, same as the PDF path does today.
- Wire into `pathsafety.read_source` beside the PDF branch (magic first,
  so a mis-named file still works) and into `web_fetch` by
  `Content-Type` (`application/vnd.openxmlformats-*`, `text/csv`,
  `image/*`) before the HTML branch.
- `requirements.txt`: `python-docx`, `openpyxl`, `Pillow` as optional
  with the usual comment; `pytesseract`/`faster-whisper` mentioned but
  not listed.

Tests (`tests/simorgh/execution/test_doctext.py`): a generated docx,
xlsx, csv, PNG fixture each round-trips; missing library -> the
install hint, no exception; row cap honoured; `read_file` on a
`.docx` renamed to `.bin` still reads (magic wins).

## WS9. Verification for non-Python subjects and the `run_tests` trap

All three checks use 0.3's `written_paths` and `read_repo_file`.

### `verification/checks/js_syntax.py::JsSyntaxCheck`
- `cost = "cheap"`; `applies` when any written path ends `.js`/`.mjs`/
  `.html`.
- For `.html`: extract `<script>` bodies (skip `type="module"`? no --
  check them too, with `--input-type=module`); for each body run
  `ctx.act("run_js_sandboxed", {"code": <wrapper>})` where the wrapper
  is `new Function(<JSON-encoded body>)` -- no execution, parse only.
  `.js` files: the file body the same way. Failure detail names the
  file, the script index, and Node's message; `Feedback(retryable=True,
  revise_hint=...)`.
- Skip (status `skipped`, detail says why) when `run_js_sandboxed`
  answers "no node executable".

### `verification/checks/render.py::RenderCheck`
- `cost = "expensive"`; `applies` when any written path ends `.html`.
- `ctx.act("render_page", {"target": path})`; fail on any
  `page_errors`, or on `failed_requests` whose URL is same-origin
  (`file://`) -- a CDN 404 is reported as a warning in `detail` but does
  not fail (no network in CI). Skip when the tool is missing/refuses.

### `verification/checks/trailing_narration.py::TrailingNarrationCheck`
- `cost = "free"`; `applies` when any written path ends `.html` or
  `.py`.
- `.html`: non-whitespace after the last `</html>` -> fail, evidence
  = the first 200 chars of the tail. `.py`: parse with `ast`; if a
  `SyntaxError` and the failing line is after the last line of any
  top-level node in a parse of the text *up to that line*, and that
  tail contains no `=`/`(`/`:` on its first line, report "prose after
  the code" rather than a generic syntax error (this is a heuristic;
  the generic `SyntaxCheck` still runs -- this one only improves the
  message). Fail; `retryable=True`; hint: "the marker keeps everything
  after it as file content -- end the reply at the last line of the
  file".

Register all three in `verification/checks/__init__.py::ALL_CHECKS`
(free before cheap before expensive is already enforced by `_ORDER`).

### `RunTestsTool` non-Python target
In `execution/tools.py::RunTestsTool.run`: if `target` is not
`tests`/a directory/a `.py` path *or* pytest returns exit code 4
(usage), report `ok=True` with the existing "no tests cover this
target yet -- nothing was run" note and add "for a non-Python file, run
the whole suite: RUN_TESTS: with no target". `FullSuiteRanCheck`: apply
only when some written path ends `.py` and lives under `simorgh/`,
`simorgh_skills/`, `tools/` or `tests/`; a pure `docs/`/`games/` HTML
task no longer needs a suite run to pass (its gates are the three
checks above).

### `search_listings` two-part marker
Register per 0.4 with `("location", "filters")`; filters keys are the
tool's existing `zip_code`/`min_*`/`max_*`. `_TOOL_NOTES`: "first line
the location, then optional JSON filters, e.g. {"zip_code": "95120",
"max_price": 2500000}".

Tests: one module per check with the exact fixtures from `games/`
history: the original unclosed-IIFE `snake.html` (recover from git:
`git show b02b4d7:games/snake.html` is the fixed one; the broken
original is in the scratch history -- if unavailable, synthesise:
`<script>(()=>{ let x=1;</script>`), the narration-tailed
`breakout.html` (synthesise: valid page + `\nNote: apply_source_patch
is scoped...`). `RunTestsTool`: `docs/x.html` target -> ok with the
note; `FullSuiteRanCheck` skips for an HTML-only task and still fails
a `.py` task that ran a narrowed target.

## WS11. Guardian coverage for the new surface

- `ShellcheckRule` (new, after `StaticAnalysisRule`): for
  `args["command"]` only, when `shutil.which("shellcheck")`; run
  `shellcheck -f json -s bash -` with the command on stdin; deny on
  `error`-level findings whose code is in a small list that maps to
  real danger (`SC2115` -- `rm -rf "$var/"` with possibly-empty var,
  `SC2114`, `SC2216`), report the rest as reasons on an `abstain`
  (visible in the trace, not blocking). Abstain when not installed.
  Config: `guardian.shellcheck_enabled: bool = True`.
- `install_package` guard rails live in the tool (WS1) *and* in a
  Guardian `PackageRule`: deny when `args["manager"]` is set and
  `args["spec"]` matches `guardian.package_denylist` patterns or
  contains `://`/`file:`. Keeps working even if the tool's own check is
  edited away.
- `grant_capability` import-path denylist: implemented in the tool
  (D1) and mirrored as a `GrantRule` in Guardian on
  `args["import_path"]` / `args["command"]` -- the tool is the
  usability check, the rule is the boundary.
- Tests: each rule's deny/abstain table in `test_rules.py`, plus one
  pipeline-level test per rule in `tests/simorgh/guardian/
  test_pipeline.py` confirming order and first-deny-wins.

---

## D1 (detail). Grants: signatures, storage, wiring

Plan Part II settles behaviour; this pins the code.

- `execution/grants.py`:
  ```python
  @dataclass(frozen=True)
  class Grant:  # one [[grants]] row
      id: str; kind: Literal["external","mcp"]; status: Literal["active","revoked"]
      granted_at: str; granted_by_task: str; reason: str; reversibility: str
      name: str = ""; import_path: str = ""; adapter: str = "callable"
      command: str = ""; args: tuple[str, ...] = (); read_only_tools: tuple[str, ...] = ()
      env_keys: tuple[str, ...] = ()
  class GrantStore:  # grants.toml, write-temp-then-rename, tomllib read / hand-written toml write
      def __init__(self, path: Path) ...
      def load(self) -> list[Grant]
      def append(self, grant: Grant) -> None
      def set_status(self, grant_id: str, status: str) -> Grant
  def validate_external(spec: dict) -> str | None   # refusal reason or None
  def validate_mcp(spec: dict) -> str | None
  class GrantCapabilityTool: name="grant_capability"; reversibility="irreversible"
  class RevokeCapabilityTool: name="revoke_capability"; reversibility="reversible"
  ```
- `GrantCapabilityTool` needs Execution's registry and the MCP starter:
  construct it in `Execution.start` with callbacks
  (`register=self._register_tool`, `start_mcp=self._start_mcp_server`)
  rather than importing the service -- the same injection style
  `SkillTool` uses. Refactor `_start_mcp_server` to return the list of
  registered tools; extract `_register_tool(tool, provider)` from the
  boot loop so boot, skills, MCP and grants all publish the same
  `tool.registered` + `TOOLS_STREAM` event.
- Config (`execution/config.py`): `grants_path: str = ""` (empty ->
  `<data_dir>/grants.toml`), `max_grants_per_day: int = 10`,
  `allow_uncatalogued_mcp_grants: bool = False`,
  `grant_import_denylist: tuple[str, ...] = ("os", "sys", "subprocess",
  "shutil", "socket", "ctypes", "importlib", "builtins", "pickle",
  "marshal", "code", "pty", "signal", "multiprocessing", "http",
  "urllib", "requests")`.
- `kernel/config.py`: after the TOML merge, `GrantStore(path).load()`
  active grants are appended as `ExternalToolSpec`/`McpServerConfig`
  with `provider` marked `...:granted` (add a `provider` field to both
  specs, default `"external"`/`"mcp"`). A load error is logged, never
  fatal.
- `.gitignore`: `grants.toml`.
- Ledger: `CAPABILITIES_STREAM = "capabilities"` in `execution/
  service.py`; every grant/revoke/promote appends there and publishes
  the topics from 0.1.
- Interface (0.5): `capabilities`, `capability promote|revoke|check`.
  `promote` is human-only: the dispatch handler sends a
  `capability.promote` request to Execution, which rewrites the row's
  `reversibility` and re-publishes `tool.registered` with the new
  value (Orchestration's `register_tool_policy` overwrites in place).

Tests: `tests/simorgh/execution/test_grants.py` covering every
acceptance line in the plan's D1, with `grants.toml` in a temp dir and
a fake MCP server (the existing MCP test helper) for the MCP kind;
`tests/simorgh/kernel/test_config_grants.py` for the boot merge and
the malformed-file case.

## D3 (detail). `run_container` signatures

`execution/container.py::RunContainerTool` -- `args_schema`:
`{"image": str, "command": [str], "network": bool=false, "timeout_s":
number, "input_files": [str]}`; marker two-part (`image`, JSON).
Guardian-visible string: `args["command_text"] = " ".join(command)`
is *not* read by the rules; instead set `args["command"] = " ".join
(shlex.quote(c) for c in command)` and have the tool accept either a
list or that string (splitting with `shlex`). Config: 
`container_image_prefixes`, `container_timeout_s = 300`,
`container_memory_mb = 1024`, `container_cpus = 1.0`,
`container_docker_path = ""`. Fake-docker test binary: a shell script
that appends `"$@"` to a log file and `exit 0`; tests assert the argv
(`--rm`, `--network none` by default, `--read-only`, `-v <scratch>:/
work`, no repo mount), the timeout kill path (`docker kill` then `rm
-f` recorded), and the prefix refusal.

## D4 (detail). Capability probes

`kernel/capabilities.py`:
```python
@dataclass(frozen=True)
class Probe: name: str; cost: Literal["free","cheap","network"]; run: Callable[[], Awaitable[tuple[bool, str]]]
PROBES: tuple[Probe, ...]
async def run_probes(*, include_network: bool, ttl_s: float, ledger) -> list[ProbeResult]
```
Free/cheap probes run in `Kernel.start` after Execution registers (a
background task, never blocking boot); network probes only when the
last `capability.probed` event for that name is older than `ttl_s`
(read from the `capabilities` stream) or when `capability check` is
typed. Results publish `CAPABILITY_PROBED` and append to the stream;
`Execution.health()` reports failed free probes as degraded; the
scaffold renderer reads the latest failed *network* probes (via a
small `capability.status` request) and appends "currently failing:
<tool> -- <detail>" under the tool list. Config (`kernel`):
`capabilities_probe_ttl_s: float = 21600`.

## D5 (detail). Distillation hook

In `reflection/service.py::_run_critique`, after the critique is
appended and `MEMORY_STORE` published, and only when `succeeded`:
compute `distinct_tools = {s.tool for s in steps if s.tool}` from the
task's step log (Reflection already tracks steps per task in
`_TaskMeta` -- extend it to keep tool names); if `len >= 3` and
`distinct_tools & DISTILLABLE` (`{"search_listings", "web_fetch",
"render_page", "run_container", "run_script"}` plus any
`x_`/`mcp_` name) and `meta.kind in ("patch", "research")` and the
daily count from a `distillations` stream is below
`reflection.max_distillations_per_day` (default 3): send a
`TASK_CREATE` request (`kind="skill"`, `origin="reflection"`,
`subject=f"simorgh_skills/{slug}.py"`, `description=...` built from
the task text and the ordered tool names with argument *keys* only,
`task_type="distill"` so `intake._find_duplicate`'s `distinguish`
works) and append `distillations` `proposed`. Slug = first four
significant words of the task text, snake_case, deduped against the
skills dir. Tests in `tests/simorgh/reflection/test_distillation.py`:
proposes for a 3-tool successful patch; not for chat; not on failure;
quota; dedupe on a repeat.

---

## Order of implementation (refines the plan's D6)

1. 0.1-0.5 (half a session; everything else depends on them).
2. WS9 + `run_tests` fix + `search_listings` marker (the acceptance
   trial stops blocking on verification).
3. WS10 (rows hand-back), WS7, WS1, WS2, D4.
4. D1 (external grants, then MCP), D2 catalogue, WS11.
5. D3, WS4, WS8, D5.

Run the acceptance trial from the plan's section 5 after step 2 and
after step 4.
