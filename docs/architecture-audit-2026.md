# Simorgh Architectural Audit & Roadmap (2026)
*Revised 2026-09-18 · Incorporates fact-checks from three independent reviews (Gemini, Claude Code, Claude Opus).*

---

## 1. Executive Summary
Project Simorgh is an ambitious, self-healing AI agent built from the ground up with 87k lines of code across 18 asynchronous subsystems. The system demonstrates enterprise-grade safety design (HMAC proposal/approval firewall, embedded-systems bootloader, append-only event ledger) that very few hobbyist AI agents approach.

Three independent reviews converge on the same core findings: the architecture is structurally sound, but daily usability is held back by stateless chat turns, an oversized tool surface, and several unconnected subsystem seams.

---

## 2. Architectural Strengths & Merits

1. **Guardian's HMAC Verification:** The separation of proposal and execution via HMAC tokens is enforced at three independent layers — bus topology restrictions (`contracts/topics.py`), cryptographic token minting (`guardian/tokens.py`), and independent re-verification with replay guard (`execution/verifier.py`). All 12 Guardian rules run regardless of auto-approve settings.

2. **Worktree Isolation for Self-Patching:** Self-modifications work in isolated git worktrees, commit there, and land on main only after rebase and a full test gate. The live checkout is never edited by a task.

3. **Monotonic Bootloader (`simloader.py`):** A stdlib-only watchdog implementing A/B-image rollback with `sim-good-*` tags. `sim.sh` pre-checks whether `simloader.py` compiles and restores it from the last known-good tag if not. Defense-in-depth that most production systems lack. The bootloader was permanently added to Guardian's `PROTECTED` paths list after a historical incident.

4. **Decoupled Bus with Backend Parity:** Three interaction patterns (broadcast events, competing-consumer commands, request/reply), per-partition-key ordering, priority preemption, backpressure, and dead-letter queues. Four backend tiers (memory → jsonl → sqlite → dynamodb) give a clean upgrade path. The in-process memory backend collapses to direct function calls with zero serialization cost.

5. **Cognition Compaction Pipeline:** A 5-layer graduated pipeline (budget reduction → snip → microcompact → read-time collapse → auto-compact) manages unbounded conversation histories within fixed token budgets.

---

## 3. Verified Architectural Gaps & Anti-Patterns

### 3.1 Conversational Amnesia (Critical)
**Files:** `orchestration/context.py`, `interface/service.py`

Every CLI chat line mints a fresh UUID (`service.py:943`) and creates a throwaway `Session` with empty messages. Context is reconstructed via a 250ms memory query returning top-8 similar and 6 most recent episodic records.

The code itself documents the failures in `context.py` lines 47–65:
- Turn 2 gave machine names "falcon" and "sparrow". Turns 14 and 19: "I don't have your two machines' names."
- Turn 9 corrected a birthday from March 4th to March 6th. Turns 10, 12, 14: Agent volunteered "March 4th."

> **Note:** The per-message UUID is a necessary reply-correlation key (prevents cross-wiring when multiple messages are queued). The fix is a sliding dialogue buffer, not a UUID change.

### 3.2 Tool Surface Overload (High)
**File:** `orchestration/profiles.py`

| Profile | Tools | Max Steps |
|---|---|---|
| **CHAT** | **72** | 20 |
| **VOICE_CHAT** | **58** | 6 |
| RESEARCH | 31 | 14 |
| PATCH | 25 | 20 |
| PLAN | 9 | 8 |
| SKILL | 9 | 20 |

> **Fact-check note:** Gemini originally claimed 65+, Claude Code's fact-check claimed 34. Both were wrong. Direct `len()` on the profile tuple returns **72**. Claude Code's rebuttal that downgraded tool routing to P3 was built on an incorrect number.

At ~100 tokens per tool schema, the CHAT profile consumes ~7,200 tokens on tool definitions alone before any conversation or memory enters the context.

### 3.3 Dead Wires in Self-Model and Learning Pipeline (Medium)
**Files:** `worldmodel/selfmodel.py`, `learning/pipeline.py`

1. **`self_patch.draft`** is dispatched by the learning pipeline (`pipeline.py:74`) but does not exist in the tool registry. The self-improvement pipeline cannot execute.
2. **`capabilities["tools"]`** is initialized as an empty list and never populated. Tools are tracked in `ToolsFacet` (an environment facet), but the Self Model's summary renderer only outputs `areas` and `skills`. The agent cannot describe its own tool capabilities.

### 3.4 Camera Pipeline Architectural Violation (Medium)
**File:** `execution/home/cameras.py`

RTSP streams are pulled directly from a Reolink NVR via `reolink_aio`, transcoded to HLS via local `ffmpeg`, and served from Sim's HTTP server. This directly violates the project's foundational principle: "Sim does not speak to devices. Sim speaks to Home Assistant."

> **Context:** Home Assistant is not configured in this environment. The direct NVR path is currently the only functional path. This is a pragmatic shortcut tracked as tech debt, blocked on standing up HA.

### 3.5 No Mid-Flight Steer Injection (Medium)
**File:** `orchestration/session.py`

Once a multi-step session begins, the user cannot inject corrections. The session drives a fixed GATHER → THINK → PROPOSE → ACT → VERIFY loop with no mechanism for mid-trajectory user input.

### 3.6 Auto-Approve Documentation Bug (Low)
**Files:** `docs/architecture.md`, `guardian/config.py`, `sim.sh`

- `architecture.md` line 98 states: "`sim.sh`'s own default is auto-approve."
- `sim.sh` does not contain `SIMORGH_GUARDIAN_AUTO_APPROVE`.
- No `simorgh.toml` exists in the repo.
- The dataclass default in `config.py:103` is `irreversible_requires_human: bool = True`.
- **Actual runtime default: human approval required.** The documentation is misleading. The system is safer than its docs claim.

---

## 4. Prioritized Action Plan & Detailed Implementation Roadmap

### Phase 0: Critical Fixes (Highest Daily Impact)

**1. Implement Stateful Conversational Buffer**
- **Target:** `simorgh/orchestration/context.py` and `simorgh/orchestration/worker.py`
- **Action:** Introduce a per-channel rolling buffer (`deque(maxlen=10)`) storing the last N `(user_text, assistant_reply)` pairs. Inject these as conversation history before the memory block in context assembly. Leave the per-turn UUID correlation mechanism untouched.
- **Impact:** Fixes the most impactful daily-use problem, documented with real failure transcripts in the code itself.

**2. Implement Hierarchical Tool Routing**
- **Target:** `simorgh/orchestration/profiles.py` and `simorgh/execution/tools.py`
- **Action (Option A — Domain Router):** Replace the 72 flat tools with 5–6 domain routers (`home`, `media`, `cameras`, `productivity`, `workspace`, `system`). Each router exposes a single tool accepting a sub-action parameter. The LLM picks a domain; the router dispatches internally.
- **Action (Option B — Dynamic Narrowing):** Keep flat tool list but add a lightweight intent classifier that selects a 10–15 tool subset based on the user's message before the main LLM call.
- **Impact:** Reduces ~7,200 tokens of tool schema overhead per chat turn. Reduces tool hallucination risk.

**3. Fix Dead Wires**
- **Target:** `simorgh/worldmodel/selfmodel.py` and `simorgh/learning/pipeline.py`
- **Action:** Add a `_sync_tools()` method to the Self Model that queries `ToolsFacet` and populates `capabilities["tools"]` on `tool.registered`/`tool.unavailable` events. Either implement `self_patch.draft` as a registered tool, or update the learning pipeline to use existing tools (`apply_source_patch`, `replace_in_file`).
- **Impact:** Enables the self-improvement pipeline and gives the agent self-awareness of its capabilities.

### Phase 1: Safety & Reliability

**4. Implement Tiered Safety Scopes**
- **Target:** `simorgh/guardian/rules.py` and `guardian/config.py`
- **Action:** Replace the binary `irreversible_requires_human` with per-category gates:
  - Auto-approve: read-only queries, worktree-isolated code changes, media playback.
  - Human required: commits to main, physical device actions (locks, alarms), MCP server proposals.
- **Impact:** Gives the creator autonomy for safe operations while maintaining human oversight for irreversible physical actions.

**5. Add Mid-Flight Steer Injection**
- **Target:** `simorgh/orchestration/session.py`
- **Action:** Allow a running session to receive a `steer` message via the bus that injects a user correction into `session.messages` before the next `cognition.think` call.
- **Impact:** Prevents wasted compute on multi-step tasks heading in the wrong direction.

**6. Adopt Bug-Bounty TDD for Self-Patching**
- **Target:** `simorgh/learning/pipeline.py`
- **Action:** Require a reproducing, failing unit test before drafting a patch. This closes the Goodhart loop (documented by commit `36adc95`, which claimed to implement cartoon splash screens but only edited a docstring and added an unresolvable import).
- **Impact:** Ensures self-patches solve verified problems instead of gaming the test runner.

### Phase 2: Infrastructure & Migration

**7. Migrate Ledger Default to SQLite WAL**
- **Target:** `simorgh/ledger/backends/sqlite.py` (already built), configuration defaults
- **Action:** Execute a one-time data migration of the 1.4GB JSONL log. Switch the config default to `sqlite` with `PRAGMA journal_mode=WAL`. Note: `SqliteBackend` has an unimplemented `sweep_unreferenced_blobs()` that should be added before migration.
- **Impact:** Instantaneous startup scanning, zero disk fragmentation.

**8. Stand Up Home Assistant & Offload Camera Streams**
- **Target:** `simorgh/execution/home/cameras.py`
- **Action:** Deploy and configure Home Assistant with host and API token. Then deprecate the local ffmpeg pipeline and refactor casting tools to use HA's `camera.play_stream` and `go2rtc`.
- **Impact:** Eliminates CPU contention from video transcoding; aligns implementation with stated architecture.

**9. Subsystem Consolidation**
- **Target:** The 18 subsystem packages under `simorgh/`
- **Action:** Consider merging:
  - `cognition/` assembler + `orchestration/` context → unified `reasoning/` layer
  - `execution/home/` + `execution/media/` → `execution/environment/`
- **Note:** The in-process memory bus makes this less urgent than it appears — inter-subsystem calls are direct function invocations with no serialization cost. The overhead is organizational complexity for the developer, not runtime performance.

**10. Fix Auto-Approve Documentation**
- **Target:** `docs/architecture.md` line 98
- **Action:** Correct the statement "`sim.sh`'s own default is auto-approve" to reflect the actual runtime default (`irreversible_requires_human = True` when no config file or env var is set).

---

## 5. Cross-Reference: Three-Review Consensus

| Finding | Gemini | Claude Code | Claude Opus | Consensus |
|---|---|---|---|---|
| Conversational amnesia | ✅ Found | ✅ Confirmed (mechanism corrected) | ✅ Confirmed with code evidence | **Unanimous: P0 fix** |
| Tool overload | ✅ (65+ claimed) | ❌ Rebutted (34 claimed) | ✅ Verified at **72** | **2 of 3: P1 fix** |
| `self_patch.draft` missing | ✅ Found | ✅ Confirmed | ✅ Confirmed | **Unanimous** |
| `capabilities["tools"]` empty | ✅ Implied | ✅ Half-confirmed | ✅ Confirmed with code trace | **Unanimous** |
| Camera RTSP violation | ✅ Found | ✅ Confirmed | ✅ Confirmed (blocked on HA) | **Unanimous** |
| Safety architecture sound | ✅ Praised | ✅ Defended | ✅ Confirmed at 3 layers | **Unanimous** |
| Bootloader excellence | ✅ Praised | ✅ Confirmed (fixed) | ✅ Confirmed | **Unanimous** |
| Bus/Ledger architecture | ✅ Praised | ✅ Confirmed | ✅ Confirmed | **Unanimous** |
