# Resourcefulness toolset: groundwork and deployment plan

Written 2026-09-09 by the planning session (Fable). Meant to be executed
by a follow-on session on a cheaper model. Everything here is grounded
in the code as it stands at the end of 2026-09-09; verify a path before
relying on it, the way you would with any plan older than a day.

## 0. Why this exists: the 95120 post-mortem

The creator asked Sim to build a real-estate browser for San Jose ZIP
95120 with data accurate to Zillow/Realtor.com. Sim built the UI and
refused to fabricate data because "no listings API is configured." An
OpenClaw+Gemini agent given the same task found `homeharvest` on PyPI
(reads Realtor.com's own site backend), scraped nine cities, ran KNN
comparables with scikit-learn, and shipped a Streamlit dashboard. The
creator's verdict: adjust Sim's mindset to be resourceful and unblock
itself.

Root causes, in order of weight, all verified:

1. **The task prompt pre-authorised giving up.** The planning session
   wrote "do not attempt to scrape them" and "if you cannot get real
   data, say so and use sample data" into Sim's task. Sim did exactly
   what it was told. This is a prompt-writing failure, not a Sim
   failure, and it is now recorded as a standing correction in the
   planning session's memory.
2. **Nothing told Sim to look for a package.** `orchestration/
   scaffolds.py` said "Guardian sees every call; a denial is an answer"
   and nothing about a missing capability. Fixed 2026-09-09: the
   `_RESOURCEFUL` block, offered wherever `run_shell` is.
3. **The tools Sim reaches for first couldn't do it.** `web_fetch` reads
   one page; `web_search` finds pages. Neither returns structured
   listings. `run_python_sandboxed` has no repo access and Guardian's
   denylist refuses hand-written network code in it (`urllib.request`,
   `requests.get(`, `socket.`). What it does *not* refuse is importing
   an installed library that does the networking itself -- so
   `pip install homeharvest` via `run_shell` followed by `from
   homeharvest import scrape_property` in the sandbox would have
   worked. Nobody had said so anywhere Sim could read it.

What already landed on 2026-09-09 (all on `main`, full suite green):

| commit | what |
|---|---|
| `9c93c08` | `web_search`: flag DuckDuckGo results unrelated to the query (`results_look_unrelated`) |
| `99ebca9` | `run_js_sandboxed`: Node twin of the Python sandbox |
| `50d5502` | `render_page` (headless Chromium via Puppeteer), `search_listings` (homeharvest), `geocode` (Nominatim); `netsafety.py` shared SSRF guard |
| (next) | `StaticAnalysisRule` (bandit) in Guardian; `_RESOURCEFUL` scaffold directive; PATCH profile now offers `web_search`/`web_fetch`/`search_listings`/`geocode` |

The principle every item below serves: **a missing capability is not a
denial.** Find an existing open-source solution, install it, wrap it so
Guardian sees every call, use it, and say what it is and what its
limits are. ToS caution becomes disclosure, never refusal.

## 1. Invariants (do not trade these away)

- **Guardian sees every call.** The creator's one architectural
  constraint. `execution/external.py` exists precisely so a third-party
  tool is wrapped as an ordinary `Tool`, proposed via `action.proposed`,
  and gated -- never handed its own agent loop.
- **Optional dependencies stay optional.** Lazy import, clean refusal
  with the `pip install` hint, a commented entry in `requirements.txt`.
  A fresh checkout must boot with nothing extra installed.
- **Honesty over polish.** Unofficial sources are labelled in the
  tool's *output text*, not just its docstring (see
  `realestate.py::_DISCLAIMER`). Nothing fabricates data. A tool never
  succeeds while saying nothing true (`docs/` honesty rules).
- **Sandbox isolation stays.** `run_python_sandboxed` keeps no repo
  access; the network denylist stays. Resourcefulness routes through
  installed libraries and Guardian-gated tools, not through loosening
  the sandbox.
- **Never stage a file you did not change.** `src/memory/long_term.py`
  is a live self-edit by the creator's own running Sim; leave it alone.

## 2. The wiring checklist for any new tool

Done five times on 2026-09-09; copy it exactly. Missing any step means
the tool exists but the model can't call it, or calls it with the wrong
argument key, or it never shows up in the prompt.

1. `simorgh/execution/<name>.py`: a class with `name`, `description`,
   `read_only`, `reversibility` (`read_only` | `reversible` |
   `irreversible`), `args_schema`, `async run(args, *, ctx) ->
   ToolResult`. Inject the I/O boundary (`opener=`, `scraper=`,
   `node_path=`) so unit tests never touch the network.
2. `execution/tools.py::builtin_tools()`: add the instance.
3. `orchestration/tools.py`: `_TOOL_POLICY[name] = (reversibility,
   uses_network)`; `_MARKER_ARG_KEY[name] = "<the one string arg>"`;
   for a code-bearing tool add the "everything after the marker is the
   program" hint next to `run_python_sandboxed`'s and add the tool to
   the fence-stripping branch in `to_action_payload`.
4. `orchestration/scaffolds.py::_TOOL_NOTES[name]`: one line the model
   reads.
5. `orchestration/session.py::_ACTION_TIMEOUTS[name]`.
6. `orchestration/profiles.py`: add to the profiles that should offer it
   (CHAT, PATCH, RESEARCH, SKILL, PLAN). PLAN is read-only.
7. `interface/live_status.py::_VERBS[("act", name)]`.
8. Tests: `tests/simorgh/execution/test_<name>.py` with mocked-boundary
   unit tests plus one real smoke test that `skipTest`s without the
   dependency/network; update
   `tests/simorgh/execution/test_tools.py::TestBuiltinTools`'s exact set.
9. `requirements.txt`: the optional dependency with a comment saying
   which tool needs it and that it is lazy.
10. `python -m pytest tests -q -n auto -p no:cacheprovider --deselect
    tests/simorgh/interface/test_service.py::InterfaceTestCase::test_a_dispatch_created_task_prints_its_real_completion`
    (that one test is a known scheduling flake, unrelated). Commit with
    explicit paths and `git commit -F <msgfile>`; push.

## 3. Workstreams

Each: goal, what exists today, what to build, acceptance. Ordered by
value per hour. Sizes are honest guesses for one focused session.

### WS1. Package discovery and installation (small)

*Goal:* make "find a library that does X" a one-call operation and make
installs auditable rather than buried in `run_shell` history.

*Today:* `run_shell` (PATCH/RESEARCH profiles, `irreversible`, Guardian
prompts unless `sim.sh`'s auto-approve is on) can already `pip install`.
`propose_mcp_server` only records a proposal.

*Build:*
- `find_package` (read-only, network): query PyPI's JSON API
  (`https://pypi.org/pypi/<name>/json`) and the npm registry
  (`https://registry.npmjs.org/<name>`) for an exact name; fall back to
  `web_search` with `site:pypi.org` for a description. Return name,
  summary, latest version, release date, homepage, licence. Refuse
  nothing; this is lookup.
- `install_package` (`irreversible` -- it changes the environment and
  reaches the network; Guardian treats it like `run_shell`): manager in
  `{pip, npm}` only, one package name validated against
  `^[A-Za-z0-9_.@/-]+$`, optional version pin. Runs `sys.executable -m
  pip install <spec>` or `npm install -g <spec>`. Appends a line to
  `simorgh_packages.txt` (new, repo root): `<date> <manager> <spec>
  task=<task_id>`. Output includes the resolved version.
- Typosquat guard: `install_package` refuses a PyPI package younger than
  30 days or with no homepage unless the arg `allow_new=true` is given
  and the reason is in the rationale.

*Acceptance:* a PATCH task "get real weather for San Jose" ends with
`find_package` -> `install_package requests-cache`-style call ->
working code, and `simorgh_packages.txt` has the line.

### WS2. Run a script with the project interpreter (small)

*Goal:* a narrower, more auditable path than `run_shell` for "run this
Python with network access", so resourcefulness does not depend on the
broadest tool in the box.

*Today:* only `run_shell` (`python x.py`) or the sandbox (no repo
access; hand-written network code denied by Guardian).

*Build:* `run_script` (`irreversible`, network): writes `code` to
`<repo_root>/.simorgh/scratch/<action_id>.py`, runs it with
`sys.executable` from `repo_root`, inherits `PATH`/`HOME` only, timeout
from config, output capped like `run_shell`. Guardian's `DenylistRule`
and `StaticAnalysisRule` both see the payload (they key on `code`).

*Acceptance:* a script `from homeharvest import scrape_property; ...`
runs and prints rows; the same script with `requests.get(` is denied.

### WS3. Containers (medium)

*Goal:* run anything -- a different Python, a compiler, a service --
without touching the host environment.

*Today:* Docker is installed
(`/Applications/Docker.app/Contents/Resources/bin/docker`); nothing uses
it. Daemon may not be running.

*Build:* `run_container` (`irreversible`, network optional):
`docker run --rm --network {none|bridge} -v <scratch>:/work -w /work
-m <mem> --cpus <n> <image> <cmd...>`. Image must start with an
allowlisted prefix (`python:`, `node:`, `ubuntu:`, `debian:`, `alpine:`
-- config). Refuse cleanly when `docker info` fails. Capture stdout/
stderr, cap output, timeout kills the container (`docker kill` on
`TimeoutExpired`, the same lesson as `mcp.py`'s hung-server fix).

*Acceptance:* `run_container image=python:3.12-slim cmd="python -c
'import sys; print(sys.version)'"` returns the version; `image=evil/x`
is refused by prefix; a `sleep 999` is killed at the timeout with no
container left behind (`docker ps` clean).

### WS4. Browser interaction, not just rendering (medium)

*Goal:* fill a form, click, wait, screenshot -- for JS-heavy pages and
for verifying Sim's own generated UIs the way a person would.

*Today:* `render_page` (`execution/render.py`) loads a URL/local file in
headless Chromium and reports title, text, JS errors, failed requests.
Its `_DRIVER` is a Node script run with `NODE_PATH` at the global
`node_modules`.

*Build:* `browse_page` (read-only unless a `submit` action is present,
then `reversible`): `target` plus an `actions` list of
`{click: selector} | {type: [selector, text]} | {wait: selector|ms} |
{screenshot: name}`. Screenshots go under `ctx.data_dir/screenshots/`
and the path is returned. Same SSRF/path guards as `render_page`.
Marker form: first line target, rest JSON actions (`_MARKER_SPLIT_FIRST_LINE`
already supports a two-part marker -- see `orchestration/tools.py`).

*Acceptance:* against a local test page with a form, `type` + `click`
produces the expected DOM text; a screenshot file exists; a `javascript:`
target is refused.

### WS5. Self-registering library tools (the biggest lever, medium)

*Goal:* once a package is installed, Sim can expose one of its functions
as a Guardian-gated tool *at runtime*, without a human editing
`simorgh.toml`.

*Today:* `execution/external.py` wraps any plain callable, LangChain
tool, pydantic_ai toolset or Composio action as an `ExternalTool`, and
`orchestration/tools.py::register_tool_policy` learns the policy from
`tool.registered` -- but the list comes only from the static
`[[execution.external_tools]]` table read at boot.

*Build:*
- `register_tool` (`irreversible` -- it grants a capability):
  `import_path` (`pkg.module:callable`), `kind` (default `callable`),
  `name`, `reversibility` (default `irreversible`, the fail-safe
  `ExternalToolSpec` already uses), `description`. Execution builds the
  `ExternalTool`, registers it, publishes `tool.registered`
  (`provider="external"`), and appends the spec to
  `simorgh.local.toml` (new; loaded after `simorgh.toml`, git-ignored)
  so it survives restart and a human can read what Sim granted itself.
- A `DenylistRule` extension so a registered callable's *import path*
  is checked against the same denylist (no `os:system`).

*Acceptance:* after `install_package homeharvest`, `register_tool
import_path=homeharvest:scrape_property name=hh_scrape
reversibility=read_only` makes `HH_SCRAPE:` callable in the same
session with a JSON-object `input`; restart and it is still there;
`register_tool import_path=os:system` is denied.

### WS6. MCP: catalogue and adoption (small-medium)

*Goal:* the hundreds of ready MCP servers become one proposal away.

*Today:* `execution/mcp.py` runs configured servers; `propose_mcp_server`
records a proposal to a ledger stream; the `mcp` CLI command is the only
writer of `simorgh.toml`; policy for MCP tools is learned at runtime via
`register_tool_policy(provider="mcp")`.

*Build:*
- `docs/mcp-catalog.md` + a `_TOOL_NOTES`-style table in the RESEARCH
  and PATCH scaffolds naming the keyless, useful ones: `fetch`,
  `filesystem`, `git`, `sqlite`, `time`, `memory`, `puppeteer`,
  `sequential-thinking`, `ddg-search` (already wired), plus the keyed
  ones with the env var they need (`brave-search`, `github`,
  `google-maps`, `slack`).
- Auto-adopt path: a proposal whose server is in the catalogue *and*
  whose tools are all read-only is installed (`npx -y <pkg>` under the
  existing `_PROPOSAL_ALLOWED_COMMANDS`) and registered at runtime
  without a human; anything else still waits for `mcp` from a human.

*Acceptance:* `propose_mcp_server` for `@modelcontextprotocol/server-time`
results in `mcp_time_get_current_time` being callable in the same
session.

### WS7. Keyless public data: the source book (small)

*Goal:* Sim should *know* that most public data needs no key.

*Today:* the model knows only what `web_search` finds. `geocode` is the
one keyless-API tool.

*Build:* `docs/sourcebook.md`, and a compact version inserted into the
RESEARCH scaffold (`_RESEARCH` in `scaffolds.py`), listing keyless JSON
APIs with one example URL each: Open-Meteo (weather), Nominatim/
Overpass (places, OSM data), Wikipedia/Wikidata REST, arXiv, Semantic
Scholar, Hacker News Firebase, Reddit `.json`, SEC EDGAR, US Census,
USGS earthquakes, NASA APOD (demo key), Open Library, Open Food Facts,
GitHub REST (60/h unauthenticated), PyPI/npm registries, `yfinance`
(unofficial Yahoo, label it). Confirm `web_fetch` passes JSON through
untouched (it extracts text from HTML; check `looks_like_html` does not
trigger on a JSON body) -- if it mangles JSON, add a `web_fetch_json`
variant or an `accept: json` argument.

*Acceptance:* a RESEARCH task "what was the weather in San Jose
yesterday" answers from Open-Meteo without asking for a key.

### WS8. Documents and media (small-medium)

*Goal:* `read_file`/`web_fetch` understand more than text and PDF.

*Today:* PDF via `pypdf` (`execution/pdftext.py`), HTML via
`htmltext.py`.

*Build:* by extension in `read_file` and by content-type in
`web_fetch`: `.docx` (`python-docx`), `.xlsx/.csv` (`openpyxl` /
stdlib `csv`, first N rows), images (`Pillow` -> size, mode, EXIF; OCR
via `pytesseract` only if `tesseract` is on PATH), audio
(`faster-whisper`, opt-in config, large model download -- default off).
Each optional, each refusing with the install hint.

*Acceptance:* `read_file docs/x.xlsx` prints the first 20 rows as a
table; an image returns dimensions; a `.docx` returns its paragraphs.

### WS9. Verification gaps found by the game trials (small, high value)

*Goal:* the checks that would have caught today's real bugs.

*Today:* `verification/checks/syntax.py::SyntaxCheck` parses Python
only. No check runs a generated page. The parser's code-bearing markers
keep everything after the marker, so trailing prose landed inside
`breakout.html` and `3d_maze.html` (a documented trade-off in
`cognition/parser.py`).

*Build:*
- `JsSyntaxCheck`: for `.js`/`.html` subjects, extract `<script>` bodies
  and run `node --check` (or `new Function(...)` via
  `run_js_sandboxed`); fail with the error text.
- `RenderCheck`: for `.html` subjects, call `render_page` on the file
  and fail on any `page_errors`. Wire it into the verdict like
  `SandboxSmokeCheck` (`verification/checks/sandbox_smoke.py`).
- `TrailingNarrationCheck`: fail an `.html` subject with non-whitespace
  after the last `</html>`, and a `.py` subject whose tail (after the
  last line `ast` can attribute) is prose. Cheap, mechanical, and it
  targets the exact failure seen twice today.

- **`run_tests` on a non-Python subject is a trap (live, trial 2 of the
  95120 experiment, 2026-09-09).** Sim, told to run tests, called
  `run_tests docs/games/real_estate_95120_live.html`; pytest exits 4
  (usage error: not a test path), `RunTestsTool` reported it as a
  failing suite, `FullSuiteRanCheck` then demanded the whole suite, and
  the task blocked with a correct, clean, real-data page sitting
  uncommitted. Fix in `execution/tools.py::RunTestsTool`: a target that
  is not a `.py` file or a directory (or that pytest cannot collect)
  reports the same honest "no tests cover this target -- nothing was
  run" as exit code 5 does, not a failure; and in the PATCH scaffold,
  say that for a non-Python file `run_tests` with an empty target (the
  whole suite) is the right call. Verify `FullSuiteRanCheck` still
  refuses the zero-collected case (`_NO_TESTS_COLLECTED_MARKER`).
- **Single-string markers cannot carry filters.** Same run: Sim wrote
  `SEARCH_LISTINGS: San Jose, CA 95120 for sale, price filter 1000000
  to 4000000, single family` -- the whole string became `location`,
  homeharvest matched nothing, 0 results, two wasted steps. Give
  `search_listings` the two-part marker shape `_MARKER_SPLIT_FIRST_LINE`
  already supports (first line `location`, rest a JSON object of
  filters), and say so in its `_TOOL_NOTES` line. Same for any future
  tool with more than one meaningful argument.

*Acceptance:* the original unclosed-IIFE `snake.html` and the
narration-tailed `breakout.html` (both in `games/` history) fail
verification; the fixed versions pass; `run_tests docs/x.html` reports
"nothing was run" and does not block a task.

### WS10. Structured data hand-back (small)

*Goal:* analysis on real data inside the sandbox, which *can* import
pandas/scikit-learn (site-packages are visible; only the repo and
hand-written network code are off limits).

*Today:* `search_listings` returns rendered text capped at
`real_estate_max_results` (20) and metadata counts only.

*Build:* return `rows` (list of dicts, capped at a config value like
200) in `ToolResult.metadata`, and teach `orchestration/session.py` to
write large metadata payloads to `ctx.data_dir/results/<action_id>.json`
and mention the path in the tool output so the model can `read_file`
it -- a general mechanism, not listings-specific. Same for any future
data tool.

*Acceptance:* the OpenClaw KNN-comparables snippet (in the creator's
2026-09-09 message) runs in `run_python_sandboxed` on 50 real 95120 rows
loaded from that JSON file.

### WS11. Guardian coverage for the new surface (small)

*Today:* `DenylistRule` (regex), `StaticAnalysisRule` (bandit, Python
only, HIGH floor), `ProtectedRule`, `ScopeRule`, `ReversibilityRule`.

*Build:* `shellcheck` over `run_shell`/`run_script` commands when the
binary exists (optional, abstain otherwise); a package allow/deny list
for `install_package` (`typosquat` guard above; deny known-bad names);
`register_tool` import-path denylist (WS5). Keep the bandit floor at
HIGH unless a real false-negative shows up -- MEDIUM double-reports what
the denylist already catches.

## 4. Sequencing for the executing session

- **Phase A (one session, all small, all independent):** WS10, WS9, WS7,
  WS1. Each is its own commit. Run the 95120 acceptance trial (section
  5) after WS10.
- **Phase B:** WS2, WS5, WS6. WS5 before WS6 -- the runtime registration
  path is shared.
- **Phase C:** WS3, WS4, WS8, WS11.

Commit small; run the full suite before each commit; push after each.
If a workstream turns out to need a design decision the plan does not
settle, write the two options and the trade-off in the commit message
of a stub and move on -- do not stall on it.

## 5. Instructions for the executing session

Read first: this file; `CLAUDE.md`; `docs/architecture.md`; the
planning session's memory notes (`~/.claude/projects/-Users-saeed-ws-
Simorgh/memory/MEMORY.md`, especially `feedback_resourcefulness.md`,
`feedback_reuse_open_source.md`, `feedback_no_session_link_in_commits.md`,
`project_autotesting_paused_2026-09-09.md`).

Non-negotiables: section 1. The wiring checklist: section 2. The known
flaky test to deselect: section 2 step 10. Do not relaunch observer
waves (`tools/observer_wave.py`); the creator paused them.

The acceptance experiment for the whole effort, run it at the end of
Phase A and again at the end of Phase B:

```
python tools/trial.py "Build a complete, self-contained web application (one HTML file, inline CSS/JS) that lets a user browse real, current for-sale real estate listings for San Jose, CA, ZIP 95120: an interactive map with a marker per property, a list view (address, price, sqft, price per sqft, beds/baths), filters by price range, sqft range and price-per-sqft range, and map pan/zoom. Data accuracy matters: use real, currently listed properties, not placeholder data, and state plainly where the data comes from and what its limits are. Save your work and commit it." \
  --kind patch --subject docs/games/real_estate_95120_live.html \
  --timeout 900 --max-steps 40 --keep
```

Expected: Sim calls `search_listings` (and `geocode` if it needs it),
embeds real rows with the source disclaimer in the page, verifies with
`render_page`, commits. Verify the output yourself: Node syntax check on
the script, no text after `</html>`, addresses that exist in 95120.
Copy a clean result into `games/` and commit it there.

Report back in this shape: what landed (commit hashes), what was
verified *live* (not just unit-tested), what was deferred and why.

## 6. Environment facts (2026-09-09, this Mac)

- `node` on PATH; `puppeteer@25.8.0` global at `/opt/homebrew/lib/node_modules`
  (`npm root -g`); bundled Chromium launches headless.
- `bandit 1.9.4`, `homeharvest 0.8.18`, `pandas 2.3.3` installed in the
  project interpreter (`/opt/homebrew/anaconda3/bin/python`).
- Docker CLI at `/Applications/Docker.app/Contents/Resources/bin/docker`;
  daemon state unknown.
- No search/geocoding/real-estate API keys in the environment; none are
  needed for anything in this plan.
- The creator's own Sim process may be running and self-editing
  `src/memory/long_term.py`; leave that file alone.

---

# Part II: design pass (2026-09-09, later the same day)

The items above that were checklist-shaped stay as they are. These four
had real design decisions in them; they are now settled here so the
executing session implements rather than decides. Each names the exact
seams in today's code.

## D1. Self-granted capabilities (replaces WS5 and the adoption half of WS6)

### The idea in one paragraph

A **grant** is a record that Sim may add at runtime saying "this
external callable / this MCP server is now a tool." Grants live in
their own file, are loaded at boot like human config, are visible and
revocable by a human, default to the strictest Guardian tier, and are
themselves proposed through Guardian as an `irreversible` action. The
human-written `simorgh.toml` stays human-only; Sim never edits it.

### Storage: `${data_dir}/grants.toml`

```toml
[[grants]]
id = "g-2026-09-09-7f3a"          # ulid-ish, unique
kind = "external"                  # external | mcp
status = "active"                  # active | revoked
granted_at = "2026-09-09T14:02:11Z"
granted_by_task = "3c68a390"       # task_id, or "human"
reason = "listings for the 95120 map task"
reversibility = "irreversible"     # never looser than the grant rules allow
# kind = "external": the same fields as [[execution.external_tools]]
import_path = "homeharvest:scrape_property"
adapter = "callable"
name = "x_hh_scrape"
# kind = "mcp": the same fields as [[execution.mcp_servers]]
# command = "npx"; args = ["-y", "@modelcontextprotocol/server-time"]
# read_only_tools = ["get_current_time"]
```

- `kernel/config.py` (merge order today: `./simorgh.toml` >
  `${data_dir}/simorgh.toml` > defaults) gains one more step: load
  `${data_dir}/grants.toml` and append every `status = "active"` grant
  to `execution.external_tools` / `execution.mcp_servers` with
  `provider` tagged `external:granted` / `mcp:granted`. A malformed
  grants file is logged and skipped, never fatal (same rule as a bad
  MCP server in `Execution._start_mcp_server`).
- `.gitignore` the file. It is state, not source.

### Runtime path: the `grant_capability` tool

`execution/grants.py::GrantCapabilityTool`, `name = "grant_capability"`,
`reversibility = "irreversible"` (it changes what Sim can do; Guardian's
`ReversibilityRule` gates it -- human prompt unless `sim.sh`'s
auto-approve is on, which is the creator's current setting).

Marker shape: two-part (`_MARKER_SPLIT_FIRST_LINE`): first line `kind`,
rest a JSON object with the fields above minus `id/status/granted_*`.

`run()`:
1. Validate (section "Guard rails"). Any failure is a refusal with the
   reason; nothing is written.
2. `kind = external`: `external.adapt(ExternalToolSpec(...))` ->
   `ExternalTool`s. `kind = mcp`: `Execution._start_mcp_server(
   McpServerConfig(...))` (refactor its body into a function that
   returns the registered tools so the grant tool can call it).
3. Register each tool in `Execution._registry` (collision -> refuse,
   same as boot), publish `tool.registered` with the `:granted`
   provider, append to `TOOLS_STREAM` exactly as boot does.
   `orchestration/tools.py::register_tool_policy` already learns the
   policy from that event -- nothing to edit there.
4. Append the grant to `grants.toml` (write-temp-then-rename), append a
   `capability.granted` event to a new `CAPABILITIES_STREAM`.
5. Output: the new tool names and the marker each answers to, plus the
   sentence "granted as irreversible: every call will be gated; a human
   can promote it with `capability promote <name> read_only`."

### Guard rails (the part that must not be loosened)

- **Reversibility floor.** A self-grant is always `irreversible`. Only a
  human `capability promote` (Interface command, writes `grants.toml`)
  can set `reversible` or `read_only`. For MCP grants, tools the
  *catalogue* (D2) lists as read-only may be registered `read_only`
  directly, because a human curated that list.
- **Import-path denylist** (external grants): the module root may not
  be any of `os, sys, subprocess, shutil, socket, ctypes, importlib,
  builtins, pickle, marshal, code, pty, signal, multiprocessing,
  http, urllib, requests`; the callable may not be a dunder; the path
  must match `^[A-Za-z_][\w.]*:[A-Za-z_]\w*$`. This is a guard against
  the obvious, exactly like `DEFAULT_SHELL_REFUSALS`, not a sandbox.
- **Command allowlist** (MCP grants): `command` in
  `_PROPOSAL_ALLOWED_COMMANDS` (`npx, uvx, node, python, python3`);
  first arg for `npx`/`uvx` must be `-y`/a package name matching
  `^(@[\w-]+/)?[\w.-]+(@[\w.-]+)?$`; no `-e`, `-c`, `--eval`, absolute
  paths, or shell metacharacters anywhere in `args`; `env` keys must be
  names only -- values are read from the process environment, never
  from the grant (a grant never stores a secret).
- **Name prefix.** External grants are named `x_<name>`; MCP tools keep
  `mcp_<server>_<tool>`. A grant can never claim a builtin's name.
- **Immunity.** A grant Guardian denies is recorded like any rejected
  proposal, so `ImmunityRule` refuses a near-identical retry.
- **Quota.** `execution.max_grants_per_day` (default 10). Over quota ->
  proposal only, no grant.

### Revocation and audit

- `revoke_capability <name>` -- a tool (`reversible`) *and* an Interface
  command. Sets `status = "revoked"`, publishes a new
  `tool.unregistered` topic (Orchestration drops the policy and the
  marker; Guardian's tool projection drops the `ToolInfo`; Execution
  removes it from `_registry` and closes the MCP client if no other
  tool uses it), appends `capability.revoked`.
- `capabilities` Interface command: every grant with who/when/why/
  status and the tools it produced. `status` shows the count.

### Acceptance

1. `pip install homeharvest` (via `install_package` or `run_shell`),
   then `GRANT_CAPABILITY:` external `homeharvest:scrape_property` ->
   `X_HH_SCRAPE:` works in the same session with a JSON `input`; the
   call is gated as irreversible; restart the Kernel and it is still
   registered; `capabilities` lists it.
2. `GRANT_CAPABILITY:` external `os:system` -> refused, reason names
   the denylisted module; a retry with `subprocess:run` -> refused by
   immunity or the denylist, never granted.
3. MCP grant of `@modelcontextprotocol/server-time` (catalogued,
   read-only) -> `mcp_time_get_current_time` callable and `read_only`;
   an uncatalogued package -> `irreversible`; `args = ["-e", ...]` ->
   refused.
4. `revoke_capability x_hh_scrape` -> the marker no longer routes; the
   file shows `revoked`; boot does not load it.
5. The 11th grant in a day -> proposal recorded, nothing granted.

## D2. MCP catalogue (the curated half of WS6)

`docs/mcp-catalog.toml` (human-maintained; Sim reads, never writes):

```toml
[[servers]]
package = "@modelcontextprotocol/server-time"
command = "npx"; args = ["-y", "@modelcontextprotocol/server-time"]
read_only_tools = ["get_current_time", "convert_time"]
needs_env = []
[[servers]]
package = "@modelcontextprotocol/server-fetch"     # read-only fetch
command = "uvx"; args = ["mcp-server-fetch"]
read_only_tools = ["fetch"]
needs_env = []
[[servers]]
package = "@modelcontextprotocol/server-github"
command = "npx"; args = ["-y", "@modelcontextprotocol/server-github"]
read_only_tools = ["search_repositories", "get_file_contents", "list_issues"]
needs_env = ["GITHUB_PERSONAL_ACCESS_TOKEN"]
```

Seed it with: time, fetch, filesystem (scoped to `data_dir`), git,
sqlite, memory, sequential-thinking, puppeteer, ddg-search (already
wired), github, brave-search, google-maps, slack (the last four keyed).

`propose_mcp_server` gains the auto path: if the proposed package is in
the catalogue and every `needs_env` name is set in the environment, it
calls the D1 grant path directly (still an `irreversible` proposal, so
Guardian sees it) instead of only recording a proposal. Off-catalogue
-> proposal only, for a human `mcp`, unless
`execution.allow_uncatalogued_mcp_grants = true`.

The RESEARCH and PATCH scaffolds get a five-line note: "servers you can
ask for by name, and the env var each needs" rendered from the
catalogue, so the model knows what exists.

## D3. Containers (WS3, settled)

`execution/container.py::RunContainerTool`, `name = "run_container"`,
`reversibility = "irreversible"`.

- Docker binary: `shutil.which("docker")`, then the Docker Desktop path
  in section 6. `docker info` probed once per 60s and cached; failure
  -> refusal "Docker daemon is not running".
- Args: `image` (must start with a prefix in
  `execution.container_image_prefixes`, default `("python:", "node:",
  "ubuntu:", "debian:", "alpine:")`), `command` (list of strings, no
  shell), `network` (bool, default false), `timeout_s` (capped by
  config), `input_files` (repo-relative paths under `readable_roots`,
  copied into the scratch dir -- never a bind mount of the repo).
- Run: `docker run --rm --name simorgh-<action_id> --network
  {none|bridge} -m <mem> --cpus <n> --pids-limit 256 --read-only
  --tmpfs /tmp -v <scratch>:/work -w /work <image> <command...>`.
  Scratch = `<data_dir>/containers/<action_id>/`; files the command
  writes there come back as paths in the result (WS10's hand-back).
- Timeout: `subprocess.TimeoutExpired` -> `docker kill simorgh-<id>`
  then `docker rm -f`, same lesson as `mcp.py`'s hung-server fix. Never
  leave a container behind: a test asserts `docker ps -a` has no
  `simorgh-` names after a timeout.
- Guardian: `DenylistRule` cannot read a command list today (it scans
  `code`/`command` strings); join the list with spaces into a synthetic
  `command` arg before proposing so the existing rules see it.
- Marker: two-part -- first line `image`, rest JSON.
- Tests: unit tests with a fake `docker` (a shell script on a temp
  PATH that records its argv and echoes); one smoke test that skips
  unless `docker info` succeeds.

## D4. Capability self-test (new)

`kernel/capabilities.py`: a table of probes, each `(name, cost,
probe() -> (ok, detail))`, run by `kernel/selfcheck.py` at boot in the
background and by a new `capabilities check` Interface command on
demand.

| probe | cost | expect |
|---|---|---|
| node present | free | `node --version` |
| puppeteer resolvable | free | `NODE_PATH` from `npm root -g` has `puppeteer/` |
| bandit importable | free | `importlib.util.find_spec("bandit")` |
| homeharvest importable | free | same |
| docker daemon | cheap | `docker info` exit 0 |
| web_search | network | `python` returns >= 1 result, not `low_confidence` |
| geocode | network | "San Jose, CA" -> lat within 0.5 of 37.34 |
| search_listings | network, rate-limited | "San Jose, CA 95120", zip 95120 -> >= 1 |
| render_page | cheap | a bundled fixture with a thrown error reports it |

Rules: network probes run at most once per `capabilities_probe_ttl_s`
(default 6h) and never at boot when the last run is fresh -- Nominatim
and Realtor.com must not see a probe on every restart. Results go to a
`capabilities` ledger stream; a failed *free* probe degrades Execution's
health; a failed *network* probe is reported in `status` and in the
scaffold ("search_listings is currently failing: ..."), so the model
does not spend steps on a tool that is known to be down.

Acceptance: uninstall bandit -> `status` says so within one boot; block
the network -> `capabilities check` marks the three network probes
failed and the PATCH scaffold carries the warning.

## D5. Skill distillation (new)

Turn a solved multi-tool task into a reusable skill without a human
asking.

- **Trigger** (in Reflection's post-task review, which already reads
  the trajectory): a task completed with a passing verdict, kind
  `patch` or `research`, whose trajectory has >= 3 distinct tool calls
  and at least one `search_listings`/`web_fetch`/`render_page`/
  `run_container`/granted tool -- i.e. it *did* something a skill could
  encapsulate. Not for chat turns, not for pure code edits.
- **Proposal:** Reflection creates a `skill` task through Planning's
  intake with subject `simorgh_skills/<slug>.py` and description
  "Write a skill `<slug>(...)` that does <goal>; inputs: <the task's
  named inputs>; this is how it was done: <tool names and argument
  shapes from the trajectory, no outputs>". `intake._find_duplicate`
  with `subject=` already dedupes a repeat.
- **Budget:** counts against curiosity's budget, at most
  `learning.max_distillations_per_day` (default 3).
- **The skill task itself** runs the existing SKILL profile: draft,
  `run_python_sandboxed` it once with a real argument, commit. A skill
  that needs the network imports an installed library (allowed) and
  never `requests` directly (denied) -- the same rule the scaffold now
  states.
- **Use:** `_announce_skills_on_disk` already tells the model the skill
  exists next boot; `_on_skill_acquired` loads it the same session.

Acceptance: after the 95120 task completes, a `skill` task appears
within one reflection cycle; it produces `simorgh_skills/listings_map.py`
that takes `(location, zip_code)`; a second task "same map for 95125"
completes in fewer steps and its trajectory shows the skill call.

## D6. Revised phase order for the executing session

- **Phase A** (small, independent): WS10, WS9 (incl. the two trial-2
  findings), WS7, WS1, **D4**.
- **Phase B**: WS2, then **D1** (external grants first, MCP grants
  second), then **D2**. Review the D1 diff on the expensive model before
  merging -- it is the one change that widens what Sim can do to
  itself.
- **Phase C**: **D3**, WS4, WS8, WS11, **D5**.

Everything in Part II has an acceptance list; treat those as the tests
to write first.
