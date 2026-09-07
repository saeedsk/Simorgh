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

**Enabling a server is three small, deliberate edits** (each one is a
real capability grant, not something to automate away):

1. **Register the server.** `execution.Config`'s zero-arg construction in
   `kernel/registry.py` (`"execution": lambda: ExecutionService()`) is
   deliberate -- richer wiring for *any* subsystem is "a later, separate
   configuration change" per that file's own docstring, not something
   `simorgh.toml` reaches yet for `execution` specifically (unlike
   `bus`/`ledger`/`orchestration`, which already have that wiring). Until
   that generalization happens, enabling a server means editing that one
   lambda directly, e.g.:
   ```python
   "execution": lambda: ExecutionService(config=Config(mcp_servers=(
       McpServerConfig(
           name="brave_search", command="npx",
           args=("-y", "@modelcontextprotocol/server-brave-search"),
           env={"BRAVE_API_KEY": "..."},  # the human's own key -- never Sim's to fetch or store
           read_only_tools=frozenset({"brave_web_search", "brave_local_search"}),
       ),
   ))),
   ```
2. **Tell `orchestration/tools.py` how to route it.** Add the server's
   real registered tool name (`mcp_<server>_<tool>`, e.g.
   `mcp_brave_search_brave_web_search`) to `_TOOL_POLICY` (reversibility,
   network) and, if the tool has exactly one required argument, to
   `_MARKER_ARG_KEY` -- both already have this one example wired in as a
   worked template. A tool with more than one required argument isn't
   reachable through the current single-argument marker path yet (the
   same ceiling `08-execution.md`'s open-questions entry below names).
3. **Add it to a `Profile.tools` tuple** (`orchestration/profiles.py`) so
   Cognition actually offers the marker to the model. Deliberately not
   done for the one wired example (`mcp_brave_search_brave_web_search`)
   by default: `mcp_servers` defaults to empty, and a profile is shared
   by every session regardless of what's actually configured -- adding an
   unconfigured server's tool name here would offer the model a marker
   that always fails with "unknown tool" everywhere the server isn't
   set up. Add it once the server from step 1 is actually running.

**Known-good servers worth knowing about**, from the official
`modelcontextprotocol/servers` catalog -- none auto-installed, none
wired past step 1 above: `server-brave-search` (real web search, needs
`BRAVE_API_KEY` -- the concrete fix for "Sim can't search the web," and
the one example above); `server-sequential-thinking` (no key, no
filesystem/network access, but its one tool takes 4+ required fields --
not reachable via markers without the structured-calling upgrade in the
open question below). `server-filesystem`/`server-git`/`server-memory`
are NOT recommended here -- Simorgh already has native, more-trusted
equivalents (`read_file`/`list_dir`/`apply_source_patch`,
`git_commit`/`git_revert`, and the real Memory subsystem); running a
third-party subprocess for the same job would be strictly worse.

## Deliberate scope cuts (see 08-execution.md section 12 for the full list)

- `shell`, `relaunch`, and `hot_swap` are NOT built this pass -- they
  need a `KernelControl` contract that doesn't exist yet.
  `isolated_test_suite` and the `skill.draft`/`self_patch.draft`
  Cognition-backed drafting-loop tools are also not built -- Learning's
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
