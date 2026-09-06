# 08 — Execution (`simorgh/execution/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 2 Agency
**Owner (build):** unassigned
**Status:** draft
**Depends on (contracts only):** `action.approved` (exclusive), `system.state.changed`, `system.tick.second`, `learn.skill.acquired`
**v1 code that migrates here:** `src/orchestrator/apply.py`, `src/orchestrator/git_ops.py`, `src/sandboxing/sandbox.py`, `src/tools/web_fetch.py`, `src/cognition/tool_protocol.py` (`safe_read_file`, `safe_list_dir`, `read_file_for_patch`, `_resolve_safe_path`, `ToolCapabilities`), `src/orchestrator/self_patch.py` (`relaunch`, `run_isolated_test_suite`), `src/orchestrator/deployment.py`, `src/main.py` (`_run_shell_passthrough`, `run_skill_code`, `use_skill`), `src/agents/skills/registry.py` (loading applied skills as tools)

## 1. Purpose and responsibilities

Execution is the only part of Simorgh that touches the world. It owns
the tool registry, runs exactly the actions Guardian has approved — and
proves each approval is genuine before running it — under the
constraints the approval carries, and reports what actually happened.
It decides nothing about *whether* an action should happen
(`02` §3: "Execution never decides anything. It only does."). Every
side effect the system ever has passes through one function in this
package, which is what makes the action path auditable and the safety
topology structural rather than procedural.

**Responsibilities (owns):**
- The `Tool` protocol and the registry (builtin tools, applied skills
  registered as tools, later MCP adapters), with `tool.registered` /
  `tool.unavailable` announcements.
- Approval-token verification, one-time use, expiry — fail closed.
- Running tools with timeouts, output caps, per-tool concurrency and
  rate limits; writing large outputs to the blob store and returning refs.
- The v1 tools, ported: file read/list with the path-safety boundary,
  web fetch with SSRF protection, sandboxed Python, creator-only shell,
  applying source patches and skills with tool-level scope re-checks,
  git commit/revert (never push), relaunch with self-check and rollback,
  hot-swap trials, the isolated test-suite runner.
- `action.result` and `tool.invoked` telemetry; the `action:<id>` result
  record.

**Explicit non-responsibilities (belongs elsewhere):**
- Approving, denying, or escalating an action — **Guardian**.
- Deciding what tools a task may use in a mode — **Guardian** (Execution
  enforces the approval's `constraints`, nothing more).
- Drafting code, choosing what to patch — **Learning** / **Orchestration**.
- Judging a result — **Verification** (Execution reports facts: exit
  code, output, diff, duration).
- Provider calls — **Cognition** (an LLM call is not an "action"; it has
  no side effect on the world).

**Principles this subsystem is the primary enforcer of** (`01` §4):
4.3 (structural safety — the token check), 4.10 (reversibility metadata
on every tool), 4.14 (stdlib core; adapters optional), and defense in
depth for scope (`apply.py`'s independent boundary, kept).

## 2. Position in the architecture

Layer 2, terminal node of the action path. Participates in every flow
that has a side effect: 1 (turn tools), 2 (task actions), 3 (read-only
exploration in plan mode), 4 (self-patch apply/commit/relaunch), 5
(finishing the current approved action on pause), 6 (read-only research
tools), 7 (nothing in flight survives a crash: an approved-but-unfinished
action is reported `ok:false, error:interrupted` on restart from the
`execution:inflight` stream). Imports only `simorgh.contracts`, bus/ledger
clients, stdlib; optional adapters (`boto3`, an MCP client) are guarded.

## 3. Interfaces

### 3.1 Messages consumed

| Type | Pattern | Semantics | What Execution does with it |
|---|---|---|---|
| `action.approved` | command (group `execution`) — reserved: only Execution may subscribe | work | verify token → run tool → `action.result` |
| `system.state.changed` | event | fact | `paused`: finish in-flight actions, refuse new ones (`ok:false, error:paused` — should not happen, Guardian stops approving); `stopping`: cancel non-reversible-safe in-flight actions after grace |
| `system.tick.second` | event | tick | rate-limit windows, in-flight timeout accounting, expired-approval sweep |
| `learn.skill.acquired` | event | fact | load the skill module in a sandbox-backed `SkillTool`, register it, emit `tool.registered` |

### 3.2 Messages produced

| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `action.result` | event | `{action_id, ok, output_ref, stdout_preview, error?, duration_ms, side_effects: [ref]}` | orchestration, learning, verification, reflection, interface |
| `action.denied` (`layer: token`) | event | emitted by Execution only when an `action.approved` fails verification — a forged, expired, replayed, or args-mismatched approval | guardian (audit), reflection, interface |
| `tool.registered` | event | `{name, version, description, read_only, reversibility, schema_ref, provider}` | guardian (policy tables), cognition (tool descriptions), worldmodel, interface |
| `tool.unavailable` | event | `{name, reason}` | same |
| `tool.invoked` | event | `{name, action_id, duration_ms, ok}` | reflection, interface (metrics) |
| `percept.file.changed` | event | after any write tool | worldmodel, memory |
| `percept.web.fetched` | event | after `web_fetch` | memory, curiosity |
| `system.health` | event | degraded on repeated tool failures or missing adapters | kernel |

### 3.3 Request/reply APIs served

None over the bus. Execution is deliberately command-only: a requester
that wants a result subscribes to `action.result` on its task's
partition. (Verification's need for test-suite runs is also an
`action.proposed` → approval → `action.result` round trip; there is no
side door.)

### 3.4 Python protocol (`api.py`)

```python
class Tool(Protocol):                     # declared in contracts.protocols; restated here
    name: str; version: str; description: str
    read_only: bool
    reversibility: Literal["read_only", "reversible", "irreversible"]
    args_schema: dict                     # JSON Schema; validated before run
    provider: Literal["builtin", "skill", "mcp"]
    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult

@dataclass(frozen=True)
class ToolContext:
    action_id: str; task_id: str | None; trace_id: str
    repo_root: Path; data_dir: Path
    clock: Clock; logger: Logger
    blobs: BlobStore                      # put(bytes) -> ref
    constraints: Constraints              # {timeout_s, max_output_bytes, allowed_paths?, network: bool}
    channel: str | None                   # "creator" for the shell passthrough; from approval
    kernel_control: KernelControl         # request_restart(), reload(subsystem) — injected by the Kernel (see §12 Q1)

@dataclass(frozen=True)
class ToolResult:
    ok: bool; output: bytes | str; error: str | None = None
    side_effects: tuple[SideEffect, ...] = ()     # {kind: file_write|git_commit|network|process, ref}
    metadata: dict = field(default_factory=dict)  # e.g. {"exit_code": 0, "tests": {...}}

class Registry(Protocol):
    def register(self, tool: Tool) -> None
    def get(self, name: str) -> Tool | None
    def list(self) -> list[Tool]

class ApprovalVerifier(Protocol):
    def verify(self, approved: ActionApprovedPayload, *, now: float) -> VerifyOutcome   # ok | expired | replayed | mismatch | bad_signature
```

### 3.5 Configuration (`[execution]`)

| Key | Type | Default | Controls |
|---|---|---|---|
| `max_concurrent_actions` | int | 4 | global semaphore |
| `per_tool_concurrency` | table | `{isolated_test_suite: 1, relaunch: 1, shell: 1}` | per-tool semaphores |
| `default_timeout_s` | float | 60 | when the approval carries none |
| `max_output_bytes` | int | 65536 | preview cap; full output goes to a blob |
| `blob_inline_threshold_bytes` | int | 4096 | outputs above this are blob refs |
| `approval_max_age_s` | float | 120 | mirrors Guardian's expiry; a token older than this is rejected even if unexpired (clock-skew guard) |
| `repo_root` | path | cwd | confinement root for file tools |
| `readable_roots` | list | `["src", "docs", "tests", "simorgh"]` | v1 boundary, extended for v2 |
| `write_scopes.skills` | path | `src/agents/skills/` | `apply_skill` confinement |
| `write_scopes.source` | list | `["src/", "simorgh/"]` | `apply_source_patch` confinement (Guardian's protected list still applies first) |
| `web_fetch.allow_private_networks` | bool | false | SSRF guard |
| `sandbox.cpu_seconds` / `memory_mb` / `timeout_s` | ints | 5 / 256 / 10 | `run_python_sandboxed` |
| `test_suite.timeout_s` | float | 180 | isolated suite runs |
| `rate_limits` | table | `{web_fetch: "30/min", shell: "10/min"}` | token buckets |
| `SIMORGH_EXECUTION_REPO_ROOT` | env | — | override |

## 4. Data model and Ledger streams

- `action:<id>` — Execution appends `verified {outcome}`, `started {tool,
  constraints}`, `finished {ok, duration_ms, output_ref, side_effects}` after
  Guardian's `decided` event on the same stream. The stream is the audit
  trail for one action.
- `execution:executed` — one `executed {action_id, token_hash}` per run;
  the replay guard reads its projection (`ExecutedSet`, a bounded LRU
  over the last `approval_max_age_s × 10` seconds, rebuilt from the
  tail).
- `execution:inflight` — `started`/`finished` pairs; on restart, any
  `started` without `finished` yields a synthetic `action.result{ok:false,
  error:"interrupted by restart"}` so Workers never wait forever.
- `execution:tools` — `registered`/`unavailable` history; projection is
  the live registry state.
- Blob area `blobs/<sha256>` for outputs, diffs, test logs.

No mutable state outside these except semaphores and rate-limit buckets.

## 5. Internal design

```
execution/
  service.py          subscribe action.approved; dispatch pipeline; health
  verifier.py         HMAC recompute, expiry, replay, args-hash match
  registry.py         Registry, discovery of builtins + skills, tool.registered
  runner.py           semaphores, timeouts, output capture, blob refs, action.result
  pathsafety.py       _resolve_safe_path port; readable/writable scope checks
  tools/
    read_file.py  list_dir.py  web_fetch.py  run_python_sandboxed.py  shell.py
    apply_source_patch.py  apply_skill.py  git_commit.py  git_revert.py
    relaunch.py  hot_swap.py  isolated_test_suite.py  skill_tool.py
```

### 5.1 The dispatch pipeline (one `action.approved`)

```
receive ─▶ schema validate ─▶ verifier.verify
   │  bad_signature | expired | replayed | mismatch ─▶ action.denied{layer:token} ; ledger action:<id> verified{outcome} ; STOP (nack? no: ack — a bad approval must not be retried)
   ▼ ok
lookup tool ─▶ unknown ─▶ action.result{ok:false, error:"unknown tool"} ; STOP
   ▼
validate args against args_schema ─▶ invalid ─▶ action.result{ok:false, error:"args"} ; STOP
   ▼
acquire global + per-tool semaphore ; rate bucket ─▶ over limit ─▶ nack{retry_after} (command redelivery)
   ▼
ledger action:<id> started ; execution:inflight started
run tool under asyncio.wait_for(timeout) in a task (subprocess-heavy tools use asyncio.to_thread)
   ▼
capture: output ≤ inline threshold → inline, else blobs.put → ref ; preview = first max_output_bytes
ledger finished ; execution:inflight finished ; execution:executed
publish action.result ; tool.invoked ; percept.* side-effect events ; ack
```

Token verification (`verifier.py`), exactly:

```python
expected = hmac.new(secret, f"{action_id}|{tool}|{args_sha256}|{expires_at}".encode(), "sha256").hexdigest()
ok = hmac.compare_digest(expected, approval_token) and now < expires_at and (now - (expires_at - guardian_ttl)) <= approval_max_age_s \
     and args_sha256 == sha256(canonical_json(args)) and action_id not in ExecutedSet
```

`args_sha256` is recomputed from the `args` actually about to run — an
approval cannot be transferred to different arguments. The secret comes
from `ctx.secrets["guardian_hmac"]`, handed by the Kernel only to Guardian
and Execution.

### 5.2 Tools (ported, with reversibility)

| Tool | read_only | reversibility | Notes (v1 origin) |
|---|---|---|---|
| `read_file {path}` | yes | read_only | `safe_read_file` boundary: inside `repo_root`, under `readable_roots`, no `..`, no credential-shaped names, bounded by `max_read_chars`; `read_file_for_patch` variant via `{full: true}` (300K cap) |
| `list_dir {path}` | yes | read_only | `safe_list_dir` |
| `web_fetch {url}` | yes (network) | read_only | `WebFetchTool` with SSRF guard (private/link-local/metadata IPs refused after DNS resolution), size and redirect caps; emits `percept.web.fetched` |
| `run_python_sandboxed {code}` | yes* | reversible | `SubprocessSandbox`: `python -I`, empty env, temp cwd, CPU/mem/time limits; *no repo access by design (milestone 84) |
| `shell {command}` | no | irreversible | v1 `!` passthrough; runs only when `ctx.channel == "creator"` (Execution re-checks; Guardian already required it) |
| `apply_source_patch {subject, code, test_summary}` | no | reversible | port of `apply.apply_source_patch`; tool-level scope check (`write_scopes.source`, no traversal) independent of Guardian; emits `percept.file.changed` |
| `apply_skill {subject, code}` | no | reversible | `apply.apply_proposal`; confined to `write_scopes.skills` |
| `git_commit {path, message}` | no | reversible (revertible) | `commit_applied_change`: stages exactly one path, Simorgh identity via `-c`, no hooks bypass, **never push**. New pre-check: `git diff --quiet HEAD -- path`; if no diff → `ok:false, error:"nothing_to_commit", metadata:{head_sha, path_sha}` so milestone 93's anomaly is *reported with evidence* instead of buried in a success message |
| `git_revert {commit|since}` | no | reversible | `revert_last_commit` / `revert_commits_since` |
| `relaunch {}` | no | irreversible (process) | port of `relaunch()`: self-check subprocess `python -m simorgh --self-check` (the `-m` reconstruction lesson, milestone 85); on pass → `ctx.kernel_control.request_restart()`; on fail → `ok:false` with the self-check output so Learning can `git_revert` |
| `hot_swap {subsystem, module}` | no | reversible | port of `DeploymentManager` trial-then-promote; in v2 the unit is a subsystem module: `ctx.kernel_control.reload(subsystem, trial=True)` |
| `isolated_test_suite {subject, code}` | yes | read_only (temp copy) | `run_isolated_test_suite`: repo copy (ignoring `.git`, `__pycache__`), baseline run, write candidate, patched run; returns `{baseline, patched, passed, tail}`; `per_tool_concurrency: 1` |
| `skill:<name> {…}` | per skill | per skill (declared in the skill's docstring header, default reversible) | applied skills loaded from `write_scopes.skills`, executed via the sandbox with the skill's own invocation code (`build_invocation_code`) |

### 5.3 Concurrency and limits

A global `asyncio.Semaphore(max_concurrent_actions)`, one per tool from
`per_tool_concurrency`, and token-bucket rate limits keyed by tool. A
rate-limited command is nacked with `retry_after`, letting the Bus
redeliver later without Execution holding state. Long subprocess tools
run via `asyncio.to_thread` so the event loop keeps serving other
actions.

### 5.4 Start, stop, health

`start()` builds the registry (builtins always; each skill file in the
skills scope → `SkillTool`; MCP adapters only if their client imports),
emits `tool.registered` for each, replays `execution:inflight` for
interrupted actions, subscribes. `stop()` waits up to `grace_s` for
in-flight actions, then cancels reversible ones and lets irreversible
ones (`relaunch`, `shell`) finish. `health()` is `degraded` when any
builtin failed to register or when the last N runs of a tool all failed.

## 6. Key behaviors — worked scenarios

**S1 — Read in plan mode (Flow 3).** `action.approved{tool:read_file,
args:{path:"simorgh/planning/dag.py"}, constraints:{timeout_s:5}}` → token
ok → path resolves under `readable_roots` → run → 3.1 KB output inline →
`action.result{ok:true, stdout_preview}` → `tool.invoked`.

**S2 — Self-patch apply and commit (Flow 4).** `action.approved{tool:
apply_source_patch, args:{subject:"simorgh/memory/retrieval.py", code,
test_summary}}` → token ok → scope check: under `simorgh/` ✓, not
protected (Guardian already checked; Execution re-checks
`write_scopes.source`) → write → `percept.file.changed` → `action.result{
ok:true, side_effects:[{file_write, ref}]}`. Then `action.approved{tool:
git_commit, args:{path, message}}` → pre-check `git diff --quiet` shows a
diff → stage + commit → `action.result{ok:true, metadata:{commit:"a1b2…"}}`.

**S3 — Forged approval (failure).** A message on `action.approved` whose
`approval_token` does not verify (wrong secret, or `args` edited after
approval so `args_sha256` mismatches) → `action.denied{layer:token,
reasons:["signature mismatch"]}` → `action:<id> verified{bad_signature}` →
ack (never retried) → `system.health{degraded, detail:"token failure"}`
so the Kernel and Reflection notice a possible integrity problem. Nothing
runs.

**S4 — "Nothing to commit" made visible.** `git_commit` after a write
whose bytes equal HEAD (or after a concurrent commit already captured
them) → pre-check finds no diff → `action.result{ok:false,
error:"nothing_to_commit", metadata:{path_sha, head_sha}}`. Learning
records the anomaly with evidence instead of the task claiming success;
the milestone 93 pattern becomes a queryable event.

**S5 — Timeout and blob.** `isolated_test_suite` exceeds `test_suite.timeout_s`
→ subprocess killed → `action.result{ok:false, error:"timeout", output_ref:
blobs/…}` with the partial log preserved for Verification.

## 7. Design considerations and tradeoffs

- **Token verification at the executor, not only at the approver.** A
  Guardian that only *emits* approvals is bypassable by any process that
  can publish `action.approved`; verifying the HMAC where the side effect
  happens makes the guarantee end-to-end (`AGI-04` §9: separation must be
  structural). Cost: one HMAC per action — negligible.
- **Fail closed, ack the bad message.** A rejected approval is acked, not
  nacked: redelivery cannot make a forged token valid, and retry loops
  are how a bug becomes a denial-of-service (`harness-05` §5 on gates
  that add friction without safety).
- **Reversibility as tool metadata.** Guardian's reversibility-weighted
  policy (`harness-01`) needs a truthful classification per tool;
  declaring it at the tool is the only place it can be kept honest.
- **Tool-level scope re-checks are kept** even though Guardian checks
  scope first — v1's "two boundaries, not one" (`apply.py` docstring).
- **Sandbox isolation matched to the class of code** (`harness-05` §3):
  `run_python_sandboxed` stays fully isolated (new skills never import
  project internals); self-patches are verified by the isolated *test
  suite* on a real repo copy instead (milestone 84).
- **Blob refs over inline output.** Keeps `action.result` small on every
  backend and gives Verification the full log without bloating Workers'
  context (`harness-01` budget-reduction layer, applied at the source).

Alternatives rejected: a request/reply "run tool" API (would create a
second path around Guardian); running tools in-process with `exec`
(no isolation); per-action OS processes for everything (too slow for
`read_file`).

## 8. Safety, degradation, and failure modes

- **Provider/budget:** not applicable — Execution never calls a model.
- **Malformed approval:** schema failure at receive → `action.denied{layer:
  token, reasons:["schema"]}`; ack.
- **Tool crash:** caught in `runner.py` → `action.result{ok:false,
  error:repr}`; the tool's failure counter feeds `health()`.
- **Restart mid-action:** `execution:inflight` replay emits interrupted
  results; a write that completed before the crash is visible via
  `percept.file.changed` replay from the Ledger; git state is checked by
  `git_commit`'s pre-check next time.
- **Duplicate `action.approved`:** `ExecutedSet` replay guard → denied
  `replayed`; the original result stands.
- **Ledger unavailable:** Execution refuses to run (nack with
  `retry_after`) — an unaudited side effect is worse than a delayed one.
- **Corrigibility:** `system.pause` → in-flight actions finish, new ones
  are refused with `error:paused` (defense in depth: Guardian should
  already have stopped approving); `system.stop` → grace, then cancel
  reversible in-flight actions; `relaunch` and `shell` are never
  cancelled mid-way. `relaunch` cannot run while `stopping`.
- **Floor:** every tool has a deterministic behavior with no model in the
  loop; if a builtin's dependency is missing (e.g. `git` binary absent),
  it registers as `tool.unavailable` and Guardian will never approve it.

## 9. Testing strategy

- Contract tests: `action.result`, `action.denied(token)`, `tool.registered`,
  `tool.invoked`, `percept.file.changed`, `percept.web.fetched`.
- Unit: `verifier` (valid; wrong secret; expired; too old; args edited;
  replay), `pathsafety` (ported v1 boundary tests: traversal, `/etc/passwd`,
  `.env`, outside roots, absolute paths), each tool's ported tests
  (`test_apply.py`, `test_git_ops.py`, `test_sandbox.py`, `test_web_fetch.py`,
  the relaunch `-m` reconstruction test, `run_isolated_test_suite` toy-repo
  test), `git_commit` pre-check (no diff → `nothing_to_commit`), rate limit
  → nack, timeout → partial blob.
- Integration: `test_flow_4_self_patch_apply_commit.py` (S2 with Guardian
  fake issuing real tokens), `test_action_path_forged_token.py` (S3 — the
  system-level invariant "an unapproved action never reaches a tool"),
  `test_restart_interrupted_action.py`.
- Invariants: every `action.result` has a preceding `verified{ok}` on its
  stream; no tool runs twice for one `action_id`.
- Mocks: `FakeClock`, a `FakeGuardian` helper that signs with the test
  secret, temp git repos, a local HTTP server for `web_fetch`.

## 10. Build steps (an agent picks this up here)

Size: **L**. Parallelizable after step 3: tools can be ported by
different agents one file each.

1. Skeleton + `Service` (reserved subscription to `action.approved`),
   boundary/contract tests. *Accept:* Kernel accepts the reserved
   subscription only from `execution`.
2. `verifier.py` + `execution:executed` projection. *Accept:* all six
   verifier cases; S3 integration.
3. `registry.py` + `runner.py` (semaphores, timeouts, blobs,
   `action.result`), one trivial `echo` tool. *Accept:* S1-shaped test;
   timeout test; blob threshold test.
4. `pathsafety.py` + `read_file`/`list_dir`. *Accept:* ported boundary tests.
5. `web_fetch`, `run_python_sandboxed`, `shell`. *Accept:* ported tests; channel check.
6. `apply_source_patch`, `apply_skill`, `git_commit` (with pre-check),
   `git_revert`. *Accept:* S2, S4.
7. `isolated_test_suite`, `relaunch`, `hot_swap` (needs `KernelControl`;
   see §12). *Accept:* toy-repo suite test; `-m` reconstruction test.
8. `skill_tool.py` + `learn.skill.acquired` handling. *Accept:* an applied
   skill from `src/agents/skills/` runs via the sandbox as a tool.
9. Inflight replay, health, `system.state.changed` handling. *Accept:*
   restart test.
10. v1 adapters (`apply.py`, `git_ops.py`, `sandbox.py`, `web_fetch.py`
    re-export); both suites green. Docs + EVOLUTION milestone.

## 11. Migration notes

- `apply_proposal`/`apply_source_patch` → `tools/apply_skill.py`,
  `tools/apply_source_patch.py`; the `store.remember(APPLIED_*_KIND)`
  side effect becomes the `action.result` + `percept.file.changed` events
  (Learning writes its own `learn.*` record).
- `commit_applied_change`, `revert_last_commit`, `revert_commits_since`,
  `current_commit_hash` → `tools/git_*.py`; the new pre-check is the only
  behavior change.
- `SubprocessSandbox` → `tools/run_python_sandboxed.py` (unchanged
  isolation).
- `WebFetchTool` → `tools/web_fetch.py`.
- `relaunch`, `run_isolated_test_suite` → tools; `DeploymentManager` →
  `tools/hot_swap.py` with `KernelControl`.
- `safe_read_file`, `safe_list_dir`, `read_file_for_patch`,
  `_resolve_safe_path`, `ToolCapabilities` → `pathsafety.py` (Cognition
  keeps `parse_marker`/`first_line_argument`/`preview`).
- `_run_shell_passthrough` → `tools/shell.py` (channel-gated).
- v1 tests move under `tests/simorgh/execution/`.

## 12. Open questions

1. **`KernelControl` for `relaunch`/`hot_swap`.** The catalog has no
   `system.restart`/`system.reload` messages; in `local-multi` mode
   Execution may not be the Kernel's process. *Default:* the Kernel
   injects a `KernelControl` object into `ToolContext` (in-process) and,
   for multi-process, implements it over new messages `system.restart
   {reason, self_check_passed}` and `system.reload {subsystem, trial}` —
   file a contracts change adding both (kernel-owned, publishable only by
   `execution` and `interface`).
2. **Who owns `percept.file.changed` for changes made outside Execution**
   (a human editing files)? *Default:* World Model's file index diffs on
   `system.tick.idle`; Execution emits only for its own writes.
3. **Skill reversibility metadata.** Skills are LLM-drafted; their
   declared reversibility may be wrong. *Default:* treat every skill as
   `reversible` at best and never `read_only`, so Guardian applies at
   least the reversible policy.
4. **MCP adapters.** Out of scope for Phase 1–3; the `provider: mcp` slot
   exists so tool discovery can be deferred (`harness-01` extensibility
   layering).
