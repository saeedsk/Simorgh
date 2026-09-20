# Simorgh: the architecture as it runs

*Describes `main` as of 2026-09-19, after the v1 tree was deleted. Written from the code, not from the original design; where the two disagreed, this says what runs. For what is wrong with it and why, read `reviews/2026-09-18/architecture-evaluation.md`; for what changes next, `plan/README.md`; for one module's interface, `simorgh/<module>/CONTRACT.md`.*

## 1. In one paragraph

Simorgh ("Sim") is a personal agent for one household, running as one Python process on one laptop. Nineteen packages under `simorgh/` (18 subsystems plus the shared `contracts`) are composed by a Kernel and talk only through typed messages on an in-process Bus; every message is also an event in an append-only Ledger, from which all state is a projection. Every effect on the world is *proposed*, and only Guardian can turn a proposal into an approval that Execution will act on; the Bus enforces that topology and the Kernel proves it at boot. A cloud model (Together, primary; the Claude Code CLI as failover; Gemini; Ollama for chat-only fallback) is the brain, reached through Cognition's router and budgets. Sim chats (CLI/TUI, HTTP dashboard, Telegram, WhatsApp), talks (a local voice pipeline), controls the house (Reolink cameras, Ring, a Cast/Android TV; Home Assistant support exists but is not configured), runs benchmarks (GAIA, BFCL, SWE-bench), and can change its own code in a git worktree that lands on `main` only after a test gate. A stdlib-only bootloader gates each boot on a core test set and rolls back to the last known-good tag.

## 2. Numbers

| | |
|---|---|
| Code | 86,996 lines in `simorgh/` (383 files), 19 packages |
| Tests | 5,771 collected after the 2026-09-19 cleanup (447 files under `tests/simorgh`, `tests/tools`) |
| Message types | 174 in `contracts/topics.py` (37 request/reply pairs), a JSON schema each |
| Tools | 104 classes, 98 registered at boot; the CHAT profile binds 72, VOICE_CHAT 58, PATCH 25, RESEARCH 31 |
| Providers | Together, Claude Code CLI, Gemini, Ollama, plus a deterministic floor |
| Backends built / in use | bus: memory, sqlite, aws / **memory**; ledger: jsonl, sqlite, dynamodb, memory / **jsonl**; mode `single`, one worker |
| Live data | `~/.simorgh/ledger` 1.4 GB (118k stream files, 88k of them per-message traces); `workspace/` 11 GB (voice recordings 6.4 GB, camera HLS 3.8 GB) |
| Boot gate | 3,348 tests, about 45 s on 12 cores |

## 3. The shape

```
People ── Interface (CLI · TUI · HTTP/dash · Telegram · WhatsApp) ── Voice (mic → STT → speaker id → TTS → speaker)
                                          │ percept.text.received
                                          ▼
                       Orchestration: 1 worker · Session runner · profiles · scaffolds
                                          │ cognition.think ─────────────▶ Cognition: router · budgets · compaction ──▶ provider
                                          │ action.proposed                          (tool calls parsed from text markers)
                                          ▼
                       Guardian: 12 rules in order · HMAC token ── action.approved ──▶ Execution: 98 tools · re-verifies token
                                          ▲                                                     │ action.result
     Learning · Reflection · Curiosity · World Model (Self Model) · Persona · Verification ◀────┘   observe and fold
                       Ledger: one JSONL file per stream, fsync per append          Bus: in-memory, 174 topics, traced
                       Kernel: config → secrets → Ledger → Bus → six layers in order → ticks → health → shutdown in reverse
```

### 3.1 Layers (`kernel/registry.py::LAYERS`, booted in this order, each waiting for the previous layer's health)

| Layer | Packages | Role |
|---|---|---|
| 0 substrate | `bus`, `ledger` | fabric and truth |
| 2 cognitive core | `cognition`, `memory`, `worldmodel` | thinking, remembering, the Self Model |
| 3 agency | `guardian`, `execution`, `verification`, `planning` | approving, doing, checking, decomposing |
| 4 growth | `growth` (parts `estimate`, `monitors`, `explore`) | outcomes, drift, exploration |
| 5 surfaces | `persona`, `benchmark`, `voice`, `interface` | mood, evals, speech, every human channel |
| X | `orchestration` | the worker that runs a session, booted last so nothing claims work before the gate is up |
| shared | `contracts`, `kernel` | the only shared import; the composition root |

### 3.2 The three invariants the code enforces

1. **Only `contracts` is shared.** No subsystem imports another; `tests/simorgh/test_module_boundaries.py` fails if one does. Only the Kernel imports every `Service` (`kernel/registry.py`).
2. **The action path is topology, not convention.** `contracts/topics.py` `SUBSCRIBE_ONLY_BY` and `PUBLISH_ONLY_BY`: only Guardian may subscribe to `action.proposed`; only Execution may subscribe to `action.approved`; only Guardian (or the Kernel's self-check) may publish it; Execution may publish `action.denied` only with `layer: "token"`. Guardian mints an HMAC over `(action_id, tool, sha256(args), expiry)`; Execution re-derives it from the ledger's own record and refuses a mismatch or a replay (`execution/verifier.py`). The Kernel's self-check proves a forged token is refused before any work runs.
3. **State is the Ledger.** Every subsystem's status, competence table, the Self Model and the task records are projections that can be rebuilt from streams. A crash loses process memory and nothing else; a task interrupted mid-step is resumed by another worker from its `task:<id>` stream without redoing the step (`orchestration/resume.py`).

Two things that are *not* enforced today and that the evaluation flags: the Ledger client is unbound (any subsystem may write any stream), and a topic may be declared with only one side (25 of 137 are).

## 4. A turn, end to end

**Typed or spoken input** arrives as `percept.text.received` (Interface mints a fresh session id per typed line as a reply-correlation key; Voice per spoken turn with the speaker's id and score). Orchestration's single worker claims it and builds a throwaway `Session` on the CHAT (or VOICE_CHAT) profile: 72 (58) tools, a 20-step budget, no worktree, no verification.

**Context** is assembled in two places: `orchestration/context.py` fetches a memory block (a similarity recall of 8 items plus a recency recall of 6, plus a per-person recall on voice) under a 0.25 s bus timeout, and `cognition/assembler.py` prepends the constitution, persona voice, self summary, user profile and task rules as protected blocks. There is no transcript across turns; continuity is whatever recall returns. The whole conversation is rendered as one `[role] content` string and sent as a single user message (`cognition/compaction.py:153`, `cognition/service.py:340`).

**The model** is called through Cognition's router: candidates in order (Together, Claude CLI, Gemini, Ollama, floor), per-provider rolling budgets replayed from the ledger, a shared deadline, cooldown on failure, a truncation retry. No provider is sent tool schemas; the model is asked to write `TOOL_NAME: argument` as the first line of its reply and `cognition/parser.py` extracts at most one call per reply (read-only calls may batch when enabled).

**A tool call** becomes `action.proposed` (`orchestration/session.py::_propose_and_await`) → Guardian runs twelve rules in order (paused, mode, protected, scope, denylist, static analysis, shellcheck, package, grant, immunity, budget, reversibility) → `action.approved` with a token → Execution verifies the token, runs the tool with a 60 s default timeout, and publishes `action.result` → the session appends the result as a user turn ("Result of read_file: ...", bounded at 8,000 chars) and asks the model again. The reversibility rule escalates irreversible actions to a human only if `irreversible_requires_human` is true; the Kernel sets it false unless `~/.simorgh/simorgh.toml` says otherwise (`kernel/service.py:203`), so the live system auto-approves. `run_shell` is on by default (`execution/config.py:193`).

**The reply** is checked by seven regex guards in `session.py` (invented tool markers, markers mid-sentence, fabricated results, claimed commits, promised behaviour, claimed TV actions, claimed pronunciation notes); a hit costs one correction turn. Then `turn.completed` goes to Memory (which stores chat turns as episodic memory), Learning (which records an outcome, typed `unknown` for chat), Persona, and the surface that asked. Voice plans the reply (pronunciation, chunking, tone), synthesises it (Kokoro, Piper, or the expressive engine), plays it, and tracks what was played so the microphone can tell Sim's voice from a person's.

**A code task** differs in three ways: the profile is PATCH (25 tools, verification on); the session opens a git worktree of the named repository and every edit lands there; on completion `worktree_land` rebases onto `main`, runs the suite as a gate, and fast-forwards. Ninety-four commits have landed this way. Retries carry a note of what earlier attempts did; a crash mid-task is resumed from the ledger.

Measured on 2026-09-18 for a spoken turn: STT 1.8 to 6.8 s, model 1.3 to 9.5 s, first audio 0.5 to 2.3 s after the reply, full response 4 to 17 s.

## 5. The modules

One paragraph each: what it owns and the one fact to know before touching it. The `CONTRACT.md` in each package has the topics, streams, config, invariants, tests and planned changes.

**Bus** (`simorgh/bus/`, 2.2k lines). Typed messages with trace and causation ids; wildcard subscriptions; consumer groups for the few command lanes (`action.proposed`, `action.approved`, `task.available`, verification, learning); priority preemption for `system.pause/stop/resume`. Three backends; only `memory` runs. Policy enforcement (`policy.py`, `enforcement.py`) is where the action-path invariant is refused. Delivery is at-least-once with ack, retry and dead-letter on the command lanes, and drop-on-error broadcast with unbounded queues on the other ~154 subscriptions, by design. Every message is written to a `trace:<trace_id>` ledger stream unless its type is on a short exclusion list; since most broadcasts mint a fresh trace id, most trace streams hold one event.

**Ledger** (`simorgh/ledger/`, 2.8k lines). One append-only JSONL file per stream plus an idempotency sidecar, fsync per append, compare-and-swap on sequence numbers, blobs stored separately, snapshots, and a compaction pass on the sleep tick. Retention today applies only to trace, dead-letter and activity streams; every other stream grows without bound (`metrics:history` 114 MB, `curiosity:ticks` 43 MB, `persona:state` 17 MB). SQLite and DynamoDB backends exist; neither runs.

**Kernel** (`simorgh/kernel/`, 4.0k lines). The composition root: loads config (`~/.simorgh/simorgh.toml`, with `./simorgh.toml` taking precedence if present) and secrets (a scoped, deny-by-default store), builds Ledger and Bus, boots the layers, owns the clock ticks (`second`, `idle` every 3 s, `sleep` every 6 h), the scheduler, `system.status`, and the structural self-check. A Supervisor with restart logic exists but has no production caller. Logging is never configured, so INFO-level logs are dropped.

**Contracts** (`simorgh/contracts/`, 6.4k lines). The message envelope, the topic catalogue with its policy tables, one dataclass and one JSON schema per message, the `Subsystem`, `Tool` and `ToolResult` protocols, stream names, settings, and shared vocabularies (household roster, places, tone, skills, home-device policy including `classify_call`). Five of its modules do I/O (git, a log file, `simorgh.toml`), which the evaluation lists as drift.

**Cognition** (`simorgh/cognition/`, 3.1k lines). The router described above, provider adapters, prompt assembly of the protected blocks, tokenisation, a five-layer compactor, and the marker parser. The `tools` argument every adapter accepts is never sent to a provider. `require_real` in the purposes table is dead; callers set it per request.

**Memory** (`simorgh/memory/`, 1.9k lines). Episodic turns and semantic items with embeddings, recall, contradiction flagging, consolidation at the sleep tick. The default embedder is a 256-bucket hashed bag of words (a local sentence-transformer costs 24.9 s on first call and is opt-in); recall scores every record on every call. Per-person tags exist only on voice turns. A `WorkingMemory` class exists and nothing feeds it.

**World Model** (`simorgh/worldmodel/`, 1.2k lines). Environment facets (tools, skills, providers, areas) and the Self Model: identity, competence, calibration, limitations, change history. It is the only publisher of `self.model.updated` and the only writer of `self:model`. The Self Model is built fresh at every boot and mutated in memory; `capabilities["tools"]` is never written.

**Planning** (`simorgh/planning/`, 3.1k lines). Goals to tasks: intake, a numbered-list decomposer over `simorgh/` paths, a dependency DAG, dedupe, plan mode (propose, approve), re-grounding, rollups, leases and a blocked-retry ladder. A project is marked complete when its children exist; none has yet produced a child that ran to completion.

**Guardian** (`simorgh/guardian/`, 1.8k lines). The twelve-rule pipeline, the token mint, posture (`guarded` by default; a lock is a circuit breaker that expires), the charter read from `docs/SOUL.md`, adaptive immunity (rejects proposals similar to a previously rejected one; it remembers code but not shell commands). Protected subjects: `docs/SOUL.md`, `simorgh/{guardian,execution,contracts,kernel}/`, `simorgh.toml`, `simloader.py`, `sim.sh`, matched as substrings of path-like tokens in the proposal. Guardian takes the reversibility label from the proposal and does not recompute it for house devices.

**Execution** (`simorgh/execution/`, 21.6k lines, a third of the code). The tool registry and protocol, the token verifier, files/code/git tools, sandboxes (Python, JS, container), tests and patches, web (fetch, search, render, browse), packages, remote, worktrees, path and network safety, write-watching, MCP proposals, and six domain packages: `knowledge/` (the creator's documents; index empty), `pim/` (calendar and mail, read-only), `security/` (advisory posture), `home/` (Home Assistant tools, unconfigured; Reolink cameras via RTSP → local ffmpeg → HLS; Ring), `energy/` (unconfigured), `media/` (Cast, Android TV, Music). Six call sites run tools directly without a proposal (camera and Ring watch autostart, TV charts, the camera watcher). 85% of all recorded actions are the dashboard's Ring WebRTC keepalives.

**Verification** (`simorgh/verification/`, 3.1k lines). Eleven mechanical checks run cheapest-first (syntax, JS syntax, docstring, invariants, denylist immunity, did-anything, full-suite-ran, isolated suite, sandbox smoke, render, trailing narration), a model checklist at higher rigor, trajectory scoring, plan review. Five of the eleven never run on the real path because the subject they need is not sent. It publishes only `verify.result`.

**Growth: estimate** (`simorgh/growth/estimate/`, 1.0k lines; was `learning` until the stage 8 merge). Outcome recording, a competence table per task type with calibration, strategy suggestion, and a self-patch pipeline. The pipeline's trigger topic is never published and its tool is not registered; the path that actually lands code (`orchestration/session.py::_land`) publishes nothing to Learning. 91% of outcomes are `unknown` because chat turns have no task type.

**Growth: monitors** (`simorgh/growth/monitors/`, 2.1k lines; was `reflection`). Drift, calibration, health findings, critique, denial analysis, pattern mining, distillation into draft skills, digests. Observer only; its critiques are stored as episodic memory without a person tag and so reach family chat prompts.

**Growth: explore** (`simorgh/growth/explore/`, 1.4k lines; was `curiosity`). Drives, a diversity sampler over inventories, idea and project proposals, interests, sharing pace. One exploration per idle tick; when paused it still writes a ledger event every 3 s. Its budget throttle reads fields Cognition does not send.

**Persona** (`simorgh/persona/`, 0.8k lines). Continuous mood with decay, a rule-based emotion floor, the voice line injected into every prompt via a bus request, a user model, proactive-share pacing. It publishes and ledgers a state change on 93% of its 5 s decay ticks.

**Benchmark** (`simorgh/benchmark/`, 2.8k lines). GAIA, BFCL, SWE-bench runners with per-model history and a dashboard chart; runs in a background task and narrates progress. Gates nothing.

**Voice** (`simorgh/voice/`, 10.2k lines). Energy plus Silero VAD with a barge-in gate, a turn-manager state machine, STT lanes (whisper server, sherpa streaming, faster-whisper), TitaNet speaker identification with a speaker book, the live `VoiceSession` (echo guard, bystander handling, per-turn state), a reply planner, TTS engines (Kokoro, Piper, the expressive engine, StyleTTS2), playback with an echo tracker. `VoiceSession` still reaches into the older `Pipeline` for plumbing; the echo canceller is wired only into the loop the live path does not run; barge-in is off in the live config; recordings are kept with no retention.

**Interface** (`simorgh/interface/`, 10.7k lines). The CLI REPL and TUI, a 2,234-line command dispatcher (29 verbs), narration sized from the real terminal width, an HTTP API and dashboard (bearer token when `SIM_API_TOKEN` is set; camera stills, HLS, wallpapers and media are served without it; the live bind is `0.0.0.0`), dashboard feeds that fetch markets, news and YouTube from inside the surfaces layer, Telegram (deny-by-default allow-list) and WhatsApp. The model can run any CLI verb through the `sim_command` tool.

**Orchestration** (`simorgh/orchestration/`, 5.6k lines). The worker (consumer group, claim, lease heartbeat), the 1,942-line session runner, context assembly, profiles (CHAT, VOICE_CHAT, PATCH, RESEARCH, PLAN, SKILL), scaffolds (the task rules, rendered with the clock to the minute as the first line), the tool policy table and marker-to-schema remapping, in-process delegation, progress-note re-grounding, resume. Delegation, parallel read batches, clean revisions, re-grounding and strong-tier escalation are built and default off.

## 6. Running it

```
./sim.sh                       # gate the checkout with the core tests, then boot (Ctrl-C to stop)
SIMORGH_NO_LOADER=1 ./sim.sh   # skip the gate (debugging the gate itself)
python simloader.py bless      # gate HEAD and tag it sim-good-N
./dash.sh                      # open the dashboard in Chrome
python -m simorgh status       # a one-shot snapshot (boots a second Kernel; do not rely on it)
python tools/trial.py ...      # run one watched task in a repository copy (the real behaviour test)
python tools/modtest.py <m>    # the module's tests (see docs/testing.md)
```

Configuration is `~/.simorgh/simorgh.toml` (sections per subsystem; each `simorgh/<m>/config.py` documents its keys) and `~/.simorgh/secrets.toml`. `sim.sh` exports `SIMORGH_EXECUTION_REPO_ROOT` (the repository tasks may branch) and the protobuf implementation the Android TV library needs. Live data is under `~/.simorgh/` (ledger, worktrees, benchmarks) and `workspace/` (scratch, recordings, HLS segments).

## 7. What is deliberately not built

- Multi-process and cloud deployment (`local-multi`, `aws`): the backends and a worker kernel exist and are unselected; the trust model for them is documented as unfinished.
- Home Assistant as the device hub: the tools exist; no host or token is configured; the house is driven device-direct.
- Native tool calling, a persisted conversation, real embeddings, a world state of the home, a people model, safety tiers, an evals gate, telemetry outside the decision log: these are the roadmap (`plan/`).
