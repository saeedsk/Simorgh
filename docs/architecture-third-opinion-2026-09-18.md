# Simorgh Architecture: Independent Third-Opinion Audit
*2026-09-18 · Claude Opus 4.6 via Antigravity · Against `main` at commit `47753fa`*

---

## 0. Why This Document Exists

Two prior reviews exist:
- **Gemini/Antigravity** ([`architecture-audit-2026.md`](architecture-audit-2026.md)): Identified key structural gaps but carried several stale claims from EVOLUTION.md and the post-cutover review, mistaking documented history for current state.
- **Claude Code** ([`architecture-review-2026-09-18.html`](architecture-review-2026-09-18.html)): Fact-checked Gemini's claims against the code. Confirmed several findings, refuted others — but itself made a factual error on the tool count that materially weakens its central rebuttal.

This review was conducted independently by reading every subsystem's source code via four parallel research agents, then verifying disputed claims by direct inspection of [`profiles.py`](../simorgh/orchestration/profiles.py), [`config.py`](../simorgh/guardian/config.py), [`context.py`](../simorgh/orchestration/context.py), [`sim.sh`](../sim.sh), and [`architecture.md`](architecture.md).

---

## 1. Executive Summary

Simorgh is a genuinely impressive piece of engineering. The safety topology (proposal → Guardian → HMAC → Execution re-verification), the embedded-systems bootloader, the append-only ledger, and the worktree isolation for self-patching are all real, working, and architecturally sound. Very few hobbyist AI agents have anything close to this level of structural safety thinking.

However, the system has accumulated significant practical friction from three sources:
1. **Stateless chat turns** that force the agent to reconstruct conversation context via lossy semantic search.
2. **A tool surface of 72 tools per chat turn** that bloats every prompt and increases hallucination risk.
3. **Dead wires** where subsystem seams were spec'd on both sides but never connected in the middle.

These are not theoretical concerns — they are documented in the codebase's own comments with real failure transcripts.

---

## 2. Fact-Checking the Previous Reviews

### The Tool Count Dispute: Both Previous Reviews Were Wrong

| Reviewer | Claimed CHAT Tools | Actual Count | Error |
|---|---|---|---|
| Gemini/Antigravity | 65+ | 72 | Undercounted |
| Claude Code (fact-check) | **34** | **72** | **Undercounted by 53%** |
| This review (direct count) | **72** | **72** | Verified |

**Evidence:** Direct enumeration of the `tools` tuple in [`profiles.py` lines 19–69](../simorgh/orchestration/profiles.py#L19-L69). Python `len()` on the extracted tuple returns `72`. The VOICE_CHAT profile has `58` tools.

> [!IMPORTANT]
> Claude Code's fact-check claimed "the central number in its cognitive-overload argument is roughly double the real one" and pegged CHAT at 34 tools. This is the foundational claim upon which it downgraded the tool-routing recommendation from P1 to P3 ("measure first"). **That rebuttal was built on an incorrect number.** At 72 tools, the cognitive overload critique is not just directionally correct — it is more severe than Gemini originally stated.

### The Auto-Approve Situation: A Nuanced Truth

- **Claude Code's fact-check said:** "`sim.sh` exports exactly two variables... `SIMORGH_GUARDIAN_AUTO_APPROVE` appears nowhere in `sim.sh`."
- **This is technically true** — `sim.sh` does not contain that string.
- **But the project's own [`architecture.md` line 98](architecture.md#L98-L99) says:** *"`sim.sh`'s own default is auto-approve (`irreversible_requires_human = false`) — looser than `guardian.config.Config`'s own dataclass default (`true`)."*
- **The mechanism:** There is no `simorgh.toml` file in the repo (confirmed: `find` returns 0 results). The dataclass default in [`config.py` line 103](../simorgh/guardian/config.py#L103) is `True`. Without a `simorgh.toml` override and without the env var set, **the live default is `True` (human approval required)**.
- **Verdict:** The architecture documentation is misleading — it claims `sim.sh` defaults to auto-approve, but the actual runtime default (absent a config file or env var) requires human approval. This is a **documentation bug**, not a safety bug. The system is safer than its own docs claim.

### Other Disputed Claims

| Claim | Gemini | Claude Code | This Review |
|---|---|---|---|
| `store.py` `.add()` never called | Current bug | Fixed (`memory/service.py:185`) | **Claude correct** — fixed |
| 12 cameras transcoding continuously | Active problem | 4 dirs, on-demand | **Claude correct** — on-demand relay, not continuous |
| Bootloader neutered | Live danger | Cited file *is* the fix | **Claude correct** — the `PROTECTED` list in `config.py` is the remediation |
| Conversational amnesia | Wrong mechanism (UUID) | Right conclusion, wrong cause | **Both partially right** — the problem is real and documented in code comments; the UUID is a correlation key not a session ID |
| `self_patch.draft` missing | Found it | Confirmed | **Both correct** — still missing from tool registry |
| `capabilities["tools"]` empty | Not mentioned | Half-true | **Confirmed empty** — no mutator writes to it; tools live only in the `ToolsFacet` environment facet |

---

## 3. What Is Genuinely Excellent

### 3.1 The Safety Topology Is Real and Structural
The proposal → approval → execution firewall is not a bolt-on. It is enforced at three independent layers:
- **Bus topology enforcement** ([`contracts/topics.py`](../simorgh/contracts/topics.py)): Only Guardian may subscribe to `action.proposed`; only Guardian may publish `action.approved`. Checked at every `subscribe()` and `publish()` call against the client's verified `source` identity.
- **HMAC token binding** ([`guardian/tokens.py`](../simorgh/guardian/tokens.py)): Tokens are SHA-256 HMACs over `(action_id, tool, canonical_args_sha256, expires_at)` with a 120-second TTL.
- **Independent re-verification** ([`execution/verifier.py`](../simorgh/execution/verifier.py)): Execution recalculates the hash and verifies the HMAC before running any tool. Replay guard prevents token reuse.

All 12 Guardian rules run regardless of the auto-approve setting. Auto-approve only changes whether the *last* rule (`ReversibilityRule`) escalates to a human or allows.

### 3.2 The Bootloader Is a Genuine Embedded-Systems Pattern
[`simloader.py`](../simloader.py) is stdlib-only, never imports `simorgh`, and implements A/B-image rollback with `sim-good-*` tags. The `sim.sh` wrapper even pre-checks whether `simloader.py` itself compiles — and if not, restores it from the last known-good tag. This is defense-in-depth that most production systems lack.

### 3.3 The Ledger Is a Sound Event-Sourced Foundation
Append-only events with optimistic CAS, content-addressed blob storage, retention-based compaction, and four backend tiers (memory → jsonl → sqlite → dynamodb) give a clean upgrade path from local prototype to cloud deployment.

### 3.4 The Bus Design Is Thoughtful
Three interaction patterns (broadcast events, competing-consumer commands, request/reply with dynamic inboxes), per-partition-key ordering, priority preemption for system control messages, backpressure, and dead-letter queues. The in-process memory backend collapses all of this to direct function calls with zero serialization cost.

### 3.5 The Cognition Compaction Pipeline Is Sophisticated
The 5-layer graduated compaction in [`cognition/compaction.py`](../simorgh/cognition/compaction.py) — budget reduction → snip → microcompact → read-time collapse → auto-compact — is a well-thought-out approach to managing unbounded conversation histories within fixed token budgets.

---

## 4. What Is Wrong — Verified Against Code

### 4.1 Conversational Amnesia (Critical · Daily Impact)

**Files:** [`orchestration/context.py`](../simorgh/orchestration/context.py), [`interface/service.py`](../simorgh/interface/service.py)

Every CLI chat line mints a fresh UUID ([`service.py:943`](../simorgh/interface/service.py#L943)) and creates a throwaway `Session` with empty `messages`. The *only* mechanism for recalling what was said is a 250ms memory query returning the top 8 similar and 6 most recent episodic records.

The code itself documents the failure in [`context.py` lines 47–65](../simorgh/orchestration/context.py#L47-L65):
- Turn 2: User gave machine names "falcon" and "sparrow". Turns 14 and 19: "I don't have your two machines' names."
- Turn 9: User corrected a birthday from March 4th to March 6th. Turns 10, 12, 14: Agent volunteered "March 4th" because the superseded record had higher similarity.

**Root cause:** No sliding dialogue buffer exists. Each turn starts from zero and reconstructs context via lossy semantic search.

**Why the UUID must not be changed:** The per-turn UUID is a reply-correlation key. With a shared key, a second message sent before the first reply arrived would overwrite `_pending_turns[key]` and cross-wire responses (live bug, milestone 106).

### 4.2 Tool Surface Overload (High · Every Chat Turn)

**File:** [`orchestration/profiles.py`](../simorgh/orchestration/profiles.py)

The CHAT profile injects **72 tool schemas** into every single chat prompt. Even at a conservative 100 tokens per tool schema, that is ~7,200 tokens consumed before a single word of conversation or memory enters the context. Combined with the protected blocks (constitution, persona voice, self-summary, task rules), this creates severe pressure on the elastic conversation budget that the compaction pipeline must manage.

The VOICE_CHAT profile has 58 tools with only 6 max steps — meaning the model must select from 58 options and produce a useful result in at most 6 tool calls, for a spoken remark that should be answered in under 3 seconds.

### 4.3 Dead Wires in Self-Model and Learning Pipeline (Medium)

**Files:** [`worldmodel/selfmodel.py`](../simorgh/worldmodel/selfmodel.py), [`learning/pipeline.py`](../simorgh/learning/pipeline.py)

1. **`self_patch.draft` does not exist.** [`pipeline.py:74`](../simorgh/learning/pipeline.py#L74) dispatches `tool="self_patch.draft"`, but the tool is not registered in `execution/tools.py`. The self-improvement pipeline literally cannot execute.
2. **`capabilities["tools"]` is never populated.** The Self Model initializes `{"tools": [], "skills": [], "providers": [], "areas": []}`. While `skills`, `providers`, and `areas` have mutators, **no code anywhere writes to `capabilities["tools"]`**. Tool availability is tracked separately in `ToolsFacet` (an environment facet), but the Self Model's own summary renderer only outputs `areas` and `skills` — the agent literally does not know what tools it has when describing itself.

### 4.4 Camera Pipeline Violates Core Architectural Principle (Medium)

**Files:** [`execution/home/cameras.py`](../simorgh/execution/home/cameras.py), [`docs/plans/home-automation-design.md`](plans/home-automation-design.md)

The project's foundational rule is: *"Sim does not speak to devices. Sim speaks to Home Assistant."* The camera code directly connects to a Reolink NVR via `reolink_aio`, spawns `ffmpeg` subprocesses for RTSP-to-HLS transcoding, and serves segments from its own HTTP server.

**Mitigating context:** Home Assistant is not configured in this environment (no host, no token). The direct NVR path is currently the *only* path that works. This is a pragmatic shortcut, not an oversight — but it should be tracked as technical debt.

### 4.5 No Mid-Flight Steer Injection (Medium)

**File:** [`orchestration/session.py`](../simorgh/orchestration/session.py)

Once a multi-step session begins executing, the user cannot inject corrections or redirections. The session drives a fixed loop (GATHER → THINK → PROPOSE → ACT → VERIFY) with no mechanism to accept mid-trajectory user input. Any subsequent user typing is either blocked at readline (standard REPL) or queued as a separate, independent percept.

### 4.6 Compaction Layer 5 Disabled for Tasks (Low-Medium)

**File:** [`orchestration/session.py`](../simorgh/orchestration/session.py)

Auto-compaction (LLM summarization of older history) is only permitted for chat turns (`allow_summarize: is_chat`). Patch and research tasks that exceed the token budget will hit `ContextTooLarge` and fail unrecoverably. This is a deliberate tradeoff (protecting code diffs from lossy summarization), but it means long-running tasks have a hard ceiling.

### 4.7 Synchronous REPL Blocking (Low)

**File:** [`interface/service.py`](../simorgh/interface/service.py)

In standard readline mode, `_repl_main` blocks synchronously for the entire turn duration (up to 420 seconds). The user cannot run status or inspection commands while a turn is executing unless using the `prompt_toolkit` TUI mode.

---

## 5. Recommendations — Prioritized

### P0: Fix the Sliding Dialogue Buffer
**Target:** [`orchestration/context.py`](../simorgh/orchestration/context.py) and [`orchestration/worker.py`](../simorgh/orchestration/worker.py)

Introduce a per-channel rolling buffer (e.g., `deque(maxlen=10)`) that stores the last N `(user_text, assistant_reply)` pairs. Inject these as conversation history before the memory block in the context assembly. Leave the per-turn UUID correlation mechanism untouched.

This is the single highest-impact change. The codebase's own comments document exactly what's broken and why.

### P1: Implement Hierarchical Tool Routing
**Target:** [`orchestration/profiles.py`](../simorgh/orchestration/profiles.py)

At 72 tools, this is not a "measure first" situation — it is clearly excessive. Two approaches:

**Option A — Domain Router Pattern:** Replace the 72 flat tools with 5–6 domain routers (`home`, `media`, `cameras`, `productivity`, `workspace`, `system`). Each router exposes a single tool that accepts a sub-action parameter. The LLM picks a domain, then the router dispatches internally.

**Option B — Dynamic Profile Narrowing:** Keep the flat tool list but implement a lightweight intent classifier (keyword or small model) that selects a 10–15 tool subset based on the user's message before the main LLM call. This preserves the existing tool implementations while drastically reducing per-turn token cost.

### P1: Wire the Dead Ends
**Target:** [`worldmodel/selfmodel.py`](../simorgh/worldmodel/selfmodel.py), [`learning/pipeline.py`](../simorgh/learning/pipeline.py)

1. Add a `_sync_tools()` method to the Self Model that queries `ToolsFacet` and populates `capabilities["tools"]`. Call it on `tool.registered` and `tool.unavailable` events.
2. Either implement `self_patch.draft` as a registered tool, or update the learning pipeline to use the tools that actually exist (`apply_source_patch`, `replace_in_file`).

### P2: Implement Tiered Safety Scopes
**Target:** [`guardian/rules.py`](../simorgh/guardian/rules.py)

Replace the binary `irreversible_requires_human` with per-category gates:
- **Auto-approve:** Read-only queries, worktree-isolated code changes, media playback.
- **Human required:** Commits to main branch, physical device actions (locks, alarms), MCP server proposals.

This gives the creator the autonomy they asked for without the all-or-nothing risk.

### P2: Add Mid-Flight Steer Injection
**Target:** [`orchestration/session.py`](../simorgh/orchestration/session.py)

Allow a running session to receive a `steer` message via the bus that injects a user correction into `session.messages` before the next `cognition.think` call. This is especially important for multi-step patch tasks that are heading in the wrong direction.

### P3: Migrate Ledger Default to SQLite WAL
**Target:** [`ledger/backends/sqlite.py`](../simorgh/ledger/backends/sqlite.py) (already built), configuration defaults

The SQLite backend exists and works. The migration is operational (copy the data, switch the config default), not architectural. Do it after the higher-impact changes.

### P3: Stand Up Home Assistant and Offload Camera Streams
**Target:** [`execution/home/cameras.py`](../simorgh/execution/home/cameras.py)

This is blocked on infrastructure (HA must be configured first). Not a code change — a deployment prerequisite.

### P3: Subsystem Consolidation
**Target:** The 18 subsystem packages under `simorgh/`

The current separation is conceptually clean but practically expensive in cognitive overhead for a single developer. Consider:
- Merge `cognition/` assembler and `orchestration/` context into a unified reasoning layer.
- Merge `execution/home/` and `execution/media/` into `execution/environment/`.

**However:** The in-process memory bus makes this less urgent than it appears. When the bus backend is `memory`, inter-subsystem calls are direct function invocations with no serialization or network cost. The overhead is organizational complexity, not runtime performance.

---

## 6. Where This Review Disagrees with the Previous Two

| Topic | Gemini | Claude Code | This Review |
|---|---|---|---|
| CHAT tool count | 65+ | **34** | **72** (verified by direct `len()`) |
| Cognitive overload severity | Critical | P3 (measure first) | **P1** — 72 tools is unambiguously excessive |
| Auto-approve default | Set in `sim.sh` | Not set anywhere | **Documentation says auto-approve; code defaults to human-required. Documentation bug.** |
| Subsystem consolidation urgency | High (phantom architecture) | Fair but in-process bus mitigates | **Low priority** — in-process bus means zero runtime cost; the overhead is developer cognitive load |
| Conversational amnesia | Fix by stabilizing UUID | UUID is a correlation key | **Both right about the symptom, both wrong about a different detail** — the fix is a rolling buffer, not a UUID change |

---

## 7. Summary: The Three Things to Do First

1. **Add a sliding dialogue buffer** in `orchestration/context.py`. The codebase already documents exactly what's broken. This is the single change that will most improve daily usability.
2. **Reduce the CHAT tool surface from 72 to ~12–15** via domain routing or dynamic narrowing. At 72 tools, every chat turn wastes thousands of tokens on tool schemas that won't be used, and the model is more likely to hallucinate tool calls.
3. **Wire `capabilities["tools"]` and `self_patch.draft`**. The self-improvement pipeline cannot function, and the agent cannot describe its own capabilities. These are quick fixes with outsized impact on the system's self-awareness.

Everything else — tiered safety, camera offloading, ledger migration, subsystem consolidation — is worthwhile but lower priority. Fix the conversation, fix the tools, fix the dead wires. Then measure and iterate.
