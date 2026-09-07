# `simorgh/execution/`

The only subsystem the Bus/Kernel enforcement lets subscribe to
`action.approved`. Independently re-verifies every approval
(`verifier.ApprovalVerifier`) before dispatching to the tool registry --
defense in depth, since the Bus's own topic restriction is not a
cryptographic identity check in single-process mode. See
`docs/blueprint/subsystems/08-execution.md` for the full spec.

## Why re-verification fetches args from the Ledger, not the message

`action.approved` carries only `args_sha256`, never the original `args`
(`contracts/messages/action.py`). `_fetch_proposed_args` reads the real
args back from the durable `action:<action_id>` stream's own `received`
event -- the record Guardian appended before deciding -- and the verifier
recomputes the hash against those, not against anything a forger might
attach directly to a fabricated `action.approved`. This is the actual
mechanism that makes "an approval cannot be transferred to different
arguments" true; see `verifier.py`'s own docstring.

## Tools built this pass (ported from v1)

`read_file`, `list_dir` (path-safety bounded, `pathsafety.py`, ported from
`src/cognition/tool_protocol.py`), `run_python_sandboxed` (ported from
`src/sandboxing/sandbox.py`: `python -I`, empty env, temp cwd, rlimits --
deliberately no repo access), `apply_source_patch`, `git_commit` (ported
from `src/orchestrator/git_ops.py`, plus a `git status --porcelain`
pre-check that reports an explicit `nothing_to_commit` instead of a
buried edge case -- and, unlike a naive `git diff --quiet HEAD`, correctly
catches brand-new untracked files too), `git_revert`. Never pushes.

## Skill acquisition as procedural memory (Phase 4 roadmap item 4.7)

`apply_skill` (writes a drafted skill's module source, confined to
`write_scopes_skills`/`simorgh_skills/` -- the write half `apply_source_
patch` already had, scoped to the skill directory instead of the source
tree) and `skill:<name>` tools (`SkillTool`) are built this pass.
`SkillTool` runs the acquired module's own source inside the same
throwaway subprocess sandbox `run_python_sandboxed` uses, invoking its
`run(**args)` entrypoint (imported under a name other than `__main__` so
a drafted skill's own `if __name__ == "__main__":` footer never fires a
second time).

Never registered at boot -- `Service` subscribes to `learn.skill.
acquired` and loads exactly the one newly-acquired skill (`_load_skill`),
which is what makes this "on demand" rather than a directory scan of
`simorgh_skills/` at `start()`. A second path lives in `_on_approved`:
an approved action naming an as-yet-unregistered `skill:<name>` tool
(e.g. a skill acquired in a previous process) triggers the same
`_load_skill` lazily, reconstructing its path from the `skill_dir/
<name>.py` convention `apply_skill`/`SkillPipeline` both already use --
no fresh `learn.skill.acquired` required. Either path best-effort
enriches the registered tool's `description` via a `memory.retrieve
{kinds:[procedural]}` request against the procedural record Learning
writes on acquisition (`learning/pipeline.py`) -- the "discoverable by
description" half of the roadmap item; a Memory that never answers (not
booted, or nothing stored yet) degrades to a synthesized description
rather than blocking the load.

## Web fetch (built later this session -- 07-post-cutover-review.md, "essential toolset")

`WebFetchTool` (`tools.py`) is the one reviewed path for real outbound
network access -- Guardian's own denylist (`guardian/config.py`) already
refuses `urllib`/`requests`/`socket` in drafted code specifically so this
hand-built tool is the only way in. Ported from v1's `src/tools/
web_fetch.py`: http/https GET only, SSRF-guarded (private/loopback/
link-local/reserved/multicast addresses refused after DNS resolution),
size/time-bounded, rate-limited over a rolling window (in-process, not
durable across restarts like v1's `MemoryStore`-backed limiter -- see the
tool's own docstring). A successful fetch also publishes `percept.web.
fetched` (`execution/service.py`'s `_on_approved`, after `ACTION_RESULT`)
with a blob-stored `content_ref`, closing the contract 08-execution.md
section 4.2 already specified (`memory`, `curiosity` are its documented
consumers; neither reads it yet this session). Live-caught while wiring
this in: two bugs in the *existing* tool-calls pipeline meant no tool --
not just `web_fetch` -- actually worked from a real chat turn once a
model tried to call one; see `orchestration/tools.py` and `cognition/
parser.py`'s own docstrings for the fixes.

## MCP servers (the creator: "let's build MCP support and establish
famous MCP servers and make them available for Sim")

`mcp.py`'s own module docstring has the full design and the two
deliberate rejections (no autonomous registry discovery at runtime, no
`langchain-community`/`composio-core` dependency -- both were suggested
by a second model the creator consulted; both conflict with this
codebase's own rules, see the docstring). Short version: a human adds a
server to `execution.Config.mcp_servers`; every tool it declares
registers through the same `tool.registered` path a skill uses and flows
through the exact same Guardian pipeline as any builtin tool. Sim cannot
add a server to itself.

No paid API key anywhere in this pass -- the creator was explicit ("I
don't like the idea to pay for MCP access, sim should be able to put
together its need from open source mcp servers"), so every server named
below was checked (`npm view <pkg>`, live, this session -- not recalled
from training data, which can be stale or simply wrong about exact
package names) to confirm it's free, real, and needs no key before it
went in this file.

### Two ways to add a server: a human directly, or Sim proposes one

**Path A -- a human adds it directly**, the three steps below. Fastest,
no review step, appropriate when the human is the one who decided a
server is needed.

**Path B -- Sim proposes, a human approves or rejects once**
(`ProposeMcpServerTool`, `tools.py`; the creator, live, having just
watched Sim tell them "no MCP servers connected" for the third time:
"where is the autonomy? ... I'd like sim to move fast evolve fast,
autonomously add this kind of feature"). Sim calls `propose_mcp_server`
with its reasoning; the tool validates (name shape, `command` restricted
to a small allowlist -- `npx`/`uvx`/`node`/`python`/`python3` -- args,
`env_keys` as variable *names* only, never values) and records a
pending proposal in the Ledger (`mcp:proposals`), then Interface prints
a `ui.notice` so the human sees it live. The human reviews with `mcp`
(lists pending proposals and currently active `mcp_*` tools), then `mcp
approve <id>` (appends a real `[[execution.mcp_servers]]` block to
`simorgh.toml` -- text-appended, never a parse-and-rewrite of the whole
file, so nothing already there, comments included, is ever touched) or
`mcp reject <id> [reason]`.

This is the actual answer to "where is the autonomy": Sim can express
intent and reasoning on its own, fast, with no human drafting the
proposal for it -- but the file write itself is structurally
human-only. `propose_mcp_server`'s own `run()` never touches
`simorgh.toml`; only `interface/dispatch.py`'s `mcp approve` does, and
nothing in the tool-calling pipeline can reach that code path. That's
deliberate and not just a Guardian policy a trusted posture could
loosen (`orchestration/tools.py`'s `_TOOL_POLICY` comment on this tool
has the same point) -- a new external subprocess with new network reach
is a capability grant serious enough to keep outside Guardian's
mode-dependent trust levels entirely.

**Enabling a server directly (Path A) is three small, deliberate
edits** (each one is a real capability grant, not something to automate
away):

1. **Register the server**, in `simorgh.toml`:
   ```toml
   [[execution.mcp_servers]]
   name = "ddg_search"
   command = "npx"
   args = ["-y", "ddg-search-mcp"]
   read_only_tools = ["ddg_search", "ddg_get_answer", "ddg_search_news", "ddg_fetch_content"]
   ```
   `Kernel.boot` now reads `simorgh.toml`'s `[execution]` section into a
   real `execution.Config` (`kernel/service.py`, via `registry.
   build_factories`'s new `execution_config` parameter) -- the same
   pattern `bus`/`ledger`/`orchestration` already had; `execution` did
   not, until this pass (`08-execution.md` section 12 Q4 names it as a
   pre-existing gap, closed here rather than left for later). No Python
   edit needed for this step anymore.
2. **Tell `orchestration/tools.py` how to route it.** Add the server's
   real registered tool name (`mcp_<server>_<tool>`, e.g.
   `mcp_ddg_search_ddg_search`) to `_TOOL_POLICY` (reversibility,
   network) and, if the tool has exactly one required argument, to
   `_MARKER_ARG_KEY` -- both already have `ddg_search`/`ddg_get_answer`
   wired in as a worked template. A tool with more than one required
   argument isn't reachable through the current single-argument marker
   path yet (the same ceiling `08-execution.md`'s open-questions entry
   below names).
3. **Add it to a `Profile.tools` tuple** (`orchestration/profiles.py`) so
   Cognition actually offers the marker to the model. Deliberately not
   done for the wired examples by default: `mcp_servers` defaults to
   empty, and a profile is shared by every session regardless of what's
   actually configured -- adding an unconfigured server's tool name here
   would offer the model a marker that always fails with "unknown tool"
   everywhere the server isn't set up. Add it once the server from step 1
   is actually running.

**Free, no-key servers verified this session** (`npm view <pkg>`,
2026-09-06 -- re-verify before relying on any of these again, since npm
packages can be renamed, deprecated, or go stale):

- **`ddg-search-mcp`** (npm, MIT, v1.4.1 at verification, "no API key
  needed" in its own description) -- the concrete fix for "Sim can't
  search the web," and the two tools wired end-to-end above:
  `ddg_search` (general web search) and `ddg_get_answer` (an
  instant-answer/QnA tool), both single-required-argument (`query`).
  Also exposes `ddg_search_news`, `ddg_search_images`,
  `ddg_search_videos`, `ddg_fetch_content`, `ddg_get_suggestions`,
  `ddg_get_definition`, `ddg_convert_currency` -- registrable via step 1
  the same way, not yet routed past that (most take more than one
  required argument).
- **`@modelcontextprotocol/server-sequential-thinking`** (npm, official
  `modelcontextprotocol` org, no key, no filesystem/network access) --
  structured step-by-step reasoning. Its one tool,
  `sequential_thinking`, takes 4 required fields (`thought`,
  `nextThoughtNeeded`, `thoughtNumber`, `totalThoughts`) -- registrable,
  but not reachable via markers without the structured-calling upgrade
  the open question below names.

**`server-filesystem`/`server-git`/`server-memory`** (also official,
also free) are NOT recommended here -- Simorgh already has native,
more-trusted equivalents (`read_file`/`list_dir`/`apply_source_patch`,
`git_commit`/`git_revert`, and the real Memory subsystem); running a
third-party subprocess for the same job would be strictly worse.

## Deliberate scope cuts (see 08-execution.md section 12 for the full list)

- `shell`, `relaunch`, and `hot_swap` are NOT built this pass -- they
  need a `KernelControl` contract that doesn't exist yet.
  `isolated_test_suite` landed later as the standalone `run_tests` tool
  (pytest against a throwaway copy of the repo, never the live tree;
  `tools.py::RunTestsTool`), alongside `search_code` (regex search across
  `readable_roots`, accelerated by `ripgrep` when it's on `PATH`, pure
  stdlib otherwise -- the same optional-external-binary pattern as the
  `claude` CLI). What is still NOT built is the full read/draft/test
  *loop* around it: the `skill.draft`/`self_patch.draft`
  Cognition-backed drafting-loop tools -- Learning's
  `PatchPipeline` proposes them, but they depend on Cognition composing
  a multi-step read/draft/test loop, which is out of this build's scope
  (see `simorgh/learning/README.md`'s own open questions for the
  consequence: a skill/patch pipeline run against a real Guardian +
  Execution currently rejects at the first draft attempt with "unknown
  tool", since nothing in this build implements `*.draft`).
- The spec's suggested `registry.py`/`runner.py` split was not done;
  registry and dispatch are merged into `service.py` for this build. A
  natural follow-up once the tool count grows past what fits on one
  screen.
- The real, built `ToolContext` (`contracts/protocols.py`) has fields
  `action_id, task_id, scope, constraints, data_dir, clock, logger,
  ledger, bus`. The spec doc describes additional fields (`repo_root`,
  `blobs: BlobStore`, `channel`, `kernel_control: KernelControl`) that do
  not exist in the built contracts yet -- this package is built against
  the real contract, not the aspirational one; the gap is noted in
  08-execution.md section 12 rather than resolved by editing
  `simorgh/contracts/` unilaterally.
