# read:big-picture-proportionality

*Workflow: review · Phase: Read · Agent id: `a71f79ca69ea5355d` · Tool calls: 77*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  CONCERN: proportionality and coherence of the whole -- is this the right architecture for a personal agent that one person runs on one laptop for one family, and is it the right architecture for the stated goal of self-improvement?
  Do this differently from the other readers: first measure the shape of the codebase (lines per package; number of Service classes; number of topics vs. topics that have both a publisher and a subscriber -- write a small script that greps topics.X publish/subscribe usage and reports topics with only one side; number of message schemas; number of tools; number of provider adapters; number of bus/ledger backends; number of CLI commands; number of config keys defined vs. read). Then skim the top of each subsystem's service.py. Then read docs/blueprint/01-vision-and-principles.md and docs/blueprint/02-system-architecture.md to see what the design intended, and docs/blueprint/07-post-cutover-review.md for the project's own retrospective.
  Questions: Where is accidental complexity concentrated? What would a senior architect delete, merge, or freeze to make the system more improvable? Which abstractions have exactly one implementation and are paying an abstraction tax (backends, providers, protocols)? What is the ratio of infrastructure code to code that produces user-visible value? Which architectural decisions are load-bearing and correct (do not touch), and which are the ones the creator 'got wrong' -- be direct and specific, with evidence. Also assess: the project's docs are extremely elaborate (blueprint, EVOLUTION 5k lines, SOUL, BIOMIMICRY) -- is the docs:code:tests ratio itself a symptom?
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count lines per package in simorgh/ | __init__.py __main__.py __pycache__ benchmark big.py bus cognition contracts curiosity execution guardian interface kernel learning ledger memory orchestration  |
| 2 | Bash | Count files per package, tests, docs, tools lines | === files per package === 67 simorgh/execution/ 53 simorgh/contracts/ 46 simorgh/voice/ 23 simorgh/verification/ 20 simorgh/interface/ 17 simorgh/ledger/ 17 sim |
| 3 | Bash | Count Service classes and list contracts modules | === Service classes === 18 simorgh/benchmark/service.py: class Service simorgh/interface/service.py: class Service simorgh/ledger/service.py: class Service simo |
| 4 | Bash | Read the topics contract header | """The topic catalog: every domain, every message type (as a constant), subscription-pattern matching, reply naming, and the reserved-topology table the Kernel  |
| 5 | Bash | List remaining topic constants and sample publish/subscribe call sites | ACTION_RESULT = "action.result" TOOL_REGISTERED = "tool.registered" TOOL_PROBED = "tool.probed" TOOL_UNAVAILABLE = "tool.unavailable" TOOL_INVOKED = "tool.invok |
| 6 | Bash | Audit which topics have publishers and subscribers | TOTAL topic constants: 174 distinct values: 174 both pub+sub: 75 PUBLISH-ONLY (nobody subscribes by name; wildcard coverage shown): 74 benchmark.history.reply p |
| 7 | Bash | List every subscribe call site form | === subscribe call forms === simorgh/benchmark/runner.py:435 await self._bus.subscribe(topics.TASK_STARTED, _on_started), simorgh/benchmark/runner.py:436 await  |
| 8 | Bash | Count message schemas and list bus/ledger backends | === message schemas === 23 __init__.py __pycache__ action.py benchmark.py cognition.py curiosity.py guardian.py intent.py learn.py memory.py percept.py persona. |
| 9 | Bash | Read the live config and inspect the ledger directory | === config file === [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 barge_in_ratio = 2 |
| 10 | Bash | Inspect bus and ledger backend defaults and AWS usage | === bus config defaults === 3:field has a working default so the `memory` backend needs no config at 30: backend: str = "memory" # memory \| sqlite \| aws 33: def |
| 11 | Bash | Locate tool registry and profiles in execution | === execution layout === __init__.py __pycache__ capabilities.py config.py container.py doctext.py domainstatus.py energy external.py geocode.py home htmltext.p |
| 12 | Bash | Measure execution subpackages and find the tool definition form | === execution subdirs lines === 2379 simorgh/execution/home/ 2252 simorgh/execution/media/ 2087 simorgh/execution/pim/ 1995 simorgh/execution/knowledge/ 1085 si |
| 13 | Bash | Count tool classes and find profile/registry wiring | === tool classes === 104 === tool name attrs === 103 === CHAT profile === simorgh/memory/embedders.py:152: # exported for CHAT silently rerouted every memory em |
| 14 | Bash | Read the tool profiles module | """Per-kind Profiles (16 section 5). v1 kept its own per-agent step ceilings (`DEFAULT_MAX_TOOL_STEPS` in `self_patch.py`/`research_task.py`); these are the sam |
| 15 | Bash | Count tools per profile by importing the module | CHAT 72 max_steps 20 VOICE_CHAT 58 max_steps 6 PATCH 25 max_steps 20 RESEARCH 31 max_steps 14 PLAN 9 max_steps 8 SKILL 9 max_steps 20 distinct tools offered acr |
| 16 | Bash | List cognition provider adapters | === providers === simorgh/cognition/: __init__.py __pycache__ api.py assembler.py budget.py compaction.py config.py parser.py providers router.py service.py tok |
| 17 | Bash | Count CLI commands in the dispatch table | === dispatch.py command table === === count === 0 0 10747 total 2234 simorgh/interface/dispatch.py 1504 simorgh/interface/service.py 1264 simorgh/interface/http |
| 18 | Bash | Find the CLI command grammar and dispatch verbs | === parser.py commands === 22:COMMANDS: tuple[tuple[str, str, str], ...] = ( 84:SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = ( 92: "tasks": (("", "the ba |
| 19 | Bash | Read and count the CLI command grammar | COMMANDS: tuple[tuple[str, str, str], ...] = ( ("status", "", "health, vitals, posture and git in one panel"), ("domains", "[name]", "documents, mail, the house |
| 20 | Bash | Read settings contract and count config fields per subsystem | === settings.py head === """Where Sim's settings live, and the one-time hand-off of a secret from the terminal to a tool. A password typed on a command line bec |
| 21 | Bash | Audit config fields defined vs read anywhere in code | simorgh/interface/dispatch.py:1520: """The settings actually in force, and any that nothing reads. simorgh/interface/dispatch.py:1571: lines.append("\nsections  |
| 22 | Bash | Verify whether flagged config fields are read by other means | === execution config: how are home_timeout_s / cast_device declared & read === 351: knowledge_embedder: str = "auto" 407: home_timeout_s: float = 10.0 446: # `c |
| 23 | Bash | Re-run config audit counting getattr reads, and count getattr-on-config sites | benchmark fields= 15 unread-anywhere= 0 bus fields= 22 unread-anywhere= 0 cognition fields= 29 unread-anywhere= 0 curiosity fields= 24 unread-anywhere= 4 execut |
| 24 | Bash | List blueprint docs and the vision doc's headings | 00-README.md 01-vision-and-principles.md 02-system-architecture.md 03-contracts-and-messaging.md 04-build-plan-and-roadmap.md 05-agent-build-instructions.md 06- |
| 25 | Bash | Read the vision doc's what-we-are-building and non-goals | ## 2. What we are building The creator's stated goal, restated as engineering targets, each tied to the knowledge base that grounds it: \| Goal (creator's words) |
| 26 | Bash | List headings of the architecture and post-cutover review docs | 1:# 02 — System Architecture 11:## 1. The system in one picture 48:## 2. The sixteen subsystems 79:## 3. Structural safety: the action path 120:## 4. Package la |
| 27 | Bash | Read the project's own layer-by-layer verdict | ## 2. Architecture verdict, layer by layer **Substrate (bus, ledger, kernel, contracts) — sound; the most mature layer.** No correctness bugs in delivery or dur |
| 28 | Bash | Read the testing lesson and assessment sections | ## 4. The testing-strategy change (the real lesson) Three gaps let every finding above through a 2,200-test suite: 1. **No seam tests.** Nothing crosses Orchest |
| 29 | Bash | Read the Kernel service header and composition | """`Kernel`: the composition root itself, wired up (docs/blueprint/ subsystems/03-kernel.md section 5.1). Boots config -> secrets -> Ledger -> Bus(policy) -> la |
| 30 | Bash | Refined topic audit distinguishing replies, publishers and subscribers | topic constants: 174 {'both': 111, 'unreferenced': 5, 'pub-only': 10, 'reply': 37, 'ref-only': 1, 'sub-only': 10} == pub-only benchmark.run.completed pub: ['sim |
| 31 | Bash | Check whether one-sided topics are published or subscribed via string literals | == learn.pipeline.run == memory.forget simorgh/interface/dispatch.py:307: return await _run_tool(bus=bus, ledger=ledger, tool="memory_forget", session_id=sessio |
| 32 | Bash | Check memory_forget path, learning triggers, and self-patch topic use | === MemoryForgetTool bus path === 45: reply = await bus.request(_Message.new(_topics.MEMORY_FORGET, source="execution", payload={ === learning pipeline trigger  |
| 33 | Bash | Count aliased topics usages missed by the audit | === aliased topics imports === 27 1 VOICE_VOICES_REQUEST 1 VOICE_CONTROL_REQUEST 1 UI_COMMAND_REQUEST 1 TASK_LIST_REQUEST 1 TASK_CREATE 1 TASK_CANCEL 1 MEMORY_F |
| 34 | Bash | Read the learning pipeline and find who triggers it | """`PatchPipeline` / `SkillPipeline`: the self-patch and skill state machine (spec section 5.2/5.3) -- policy only. Every actual file read/write/test/commit/rel |
| 35 | Bash | Read Learning's own statement of its wiring status |  #: Two independent reasons, both verified 2026-09-09 (wave-21 #: observer W21-12), either of which alone is fatal: #: #: 1. Nothing anywhere publishes `learn.p |
| 36 | Bash | Find the real self-patch landing path and what it publishes | === orchestration landing === simorgh/orchestration/service.py:127: every `tool.registered` from boot landed on nobody and simorgh/orchestration/session.py:243: |
| 37 | Bash | Read the landing path and check whether task completion records self-patches |  tool="worktree_open", ok=False, denied=was_denied(detail)) session.record(step) await self._record_step(session, step) async def _land(self, session: Session,  |
| 38 | Bash | Read how World Model records a finished task | 382: async def _on_task_finished(self, message: Message) -> None: 383- p = message.payload 384- status = "completed" if message.type == topics.TASK_COMPLETED el |
| 39 | Bash | Check the live Self Model for recorded self-patches | self |
| 40 | Bash | Inspect the live Self Model and git authorship/velocity | total 8 drwxr-xr-x@ 3 saeed staff 96 Sep 9 21:27 . drwxr-xr-x@ 3 saeed staff 96 Sep 9 21:27 .. -rw-r--r--@ 1 saeed staff 734 Sep 18 17:09 SELF.md SELF.md lines  |
| 41 | Bash | Read the live SELF.md and sample Sim's own commits | # Simorgh — Self Model (v42, 2026-09-18 17:09) ## Who I am Simorgh: directives in order: Safety, Lawfulness, Loyalty, Corrigibility, Restraint, Stability, Growt |
| 42 | Bash | Count test lines per package | === test lines per package === 15098 tests/simorgh/execution/ 9177 tests/simorgh/integration/ 8962 tests/simorgh/interface/ 7176 tests/simorgh/voice/ 6561 tests |
| 43 | Bash | List the shared Protocol classes | === protocols === 20:class Subscription(Protocol): 27:class Clock(Protocol): 30: def now(self) -> float: ... 36:class Bus(Protocol): 53:class Ledger(Protocol):  |
| 44 | Bash | Read how Execution registers tools at boot |  # the same injection seam `extra_tools` already is. self._connectors: list = list(connectors or []) self._registry: dict[str, object] = {} self._subs: list = [ |
| 45 | Bash | Count tools registered by default config without booting | Exit code 127 (eval):1: command not found: timeout |
| 46 | Bash | Count tools registered by default config without booting | builtin_tools registered with default config: 98 read_only: 40 effectful: 58 [('cam', 11), ('ring', 8), ('cast', 7), ('run', 6), ('home', 5), ('kb', 5), ('sec', |
| 47 | Bash | Measure ledger stream sizes and retention defaults | === ledger streams === 118215 696M /Users/saeed/.simorgh/ledger/streams 325M /Users/saeed/.simorgh/ledger/blobs 108K /Users/saeed/.simorgh/ledger/snapshots 355M |
| 48 | Bash | Break down ledger stream names and idempotency store |  1 voice%3Aturns.jsonl 1 verify%3Afe1234ff5c0c.jsonl 1 verify%3Afd27f3be972a.jsonl 1 verify%3Afc892e053e59.jsonl 1 verify%3Afbf9066cdf23.jsonl 1 verify%3Afa2924 |
| 49 | Bash | Break down ledger stream names by prefix | 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian 2 execution 1 voice 1 system.jsonl 1 schedule.js |
| 50 | Bash | Check whether ledger retention is actually applied | trace files older than 2 days: 0 trace files total: 88356 action files older than 7d: 897 --- idem breakdown 88356 trace 2393 task 4 memory 1 learn 1 benchmark  |
| 51 | Bash | Map which subsystems import which others and the boundary test's exceptions | === cross-subsystem imports (excluding contracts/bus/ledger/kernel targets) === execution -> bus interface -> bus ledger learning -> ledger orchestration -> bus |
| 52 | Bash | Check curiosity drive config reads and assembler duplication | === curiosity drive_* === simorgh/curiosity/service.py:1:"""`Service`: wires drives, sampling, idea/project proposal, interests, simorgh/curiosity/service.py:23 |
| 53 | Bash | Read the blueprint's subsystem list and deployment model | ## 2. The sixteen subsystems \| # \| Subsystem \| Package \| Layer \| One-line job \| Spec \| \|---\|---\|---\|---\|---\|---\| \| 01 \| Bus \| `simorgh/bus/` \| 0 \| Typed, durabl |
| 54 | Bash | Skim the top docstring of every subsystem service | ##### simorgh/benchmark/service.py ( 428 lines) """The benchmark subsystem. Answers four requests on the bus: list the suites, start a run, read the history, re |
| 55 | Bash | Check which runtime mode is actually used | === runtime mode === 34: mode: str = "single" # single \| local-multi \| aws 56:# logger, data_dir, name, instance_id, mode, run_id, subsystem_token`. === sim.sh  |
| 56 | Bash | Read the Kernel's layer registry | === kernel layers === 4:15-reshuffle of this module's shape. A layer whose names are not (yet) in 18:40- ("bus", "ledger"), 19:41- ("cognition", "memory", "worl |
| 57 | Bash | Find where the competence kind 'unknown' comes from | === competence 'unknown' kind === simorgh/learning/outcomes.py:84: task_type = "unknown" simorgh/learning/outcomes.py:92: kind = p.get("kind", "unknown") simorg |
| 58 | Bash | Read how learning derives task_type from outcomes |  So the facts are read from the LAST RUN in the stream: the events after the previous terminal event, up to and including the last one. A stream with a single r |
| 59 | Bash | Measure docs volume and the prose share inside the code | === docs breakdown === 5254 docs/EVOLUTION.md 809 docs/SOUL.md 118 docs/BIOMIMICRY.md 150 docs/architecture.md 452 docs/module-map.md 87 docs/sourcebook.md 6870 |
| 60 | Bash | Sample Guardian verdict distribution from the ledger | === guardian verdicts (sample 3000 action streams) === 3000 "type":"received" 3000 "type":"decided" 2995 "type":"verified" |
| 61 | Bash | Inspect an action stream and count Guardian decisions | {"causation_id":null,"idempotency_key":null,"payload":{"proposal":{"action_id":"00058d0478bb","args":{"action":"offer","camera":"Garden","sdp":"blob:731ac8ac382 |
| 62 | Bash | Count Guardian decision kinds and which tools dominate the action ledger | 2995 "kind":"approved" 66 "kind":"patch" 58 "kind":"chat" 23 "kind":"research" 5 "kind":"denied" 2 "kind":"project" === tools proposed (all 26k action streams,  |
| 63 | Bash | Find the ring_live tool and the dashboard code that proposes it | === ring_live tool === simorgh/execution/home/ring.py:698: name = "ring_live" simorgh/execution/home/ring.py-699- description = ("Live view of a Ring camera for |
| 64 | Bash | Measure the ring_live proposal rate through Guardian | 8301 "action":"close" 5230 "action":"keepalive" 9318 "action":"offer" n=22849 span_hours=106.8 per_minute=3.6 |
| 65 | Bash | Check how message schemas are defined and generated | === schemagen === """Generate the checked-in JSON Schema files from the registry. python -m simorgh.contracts.schemagen # (re)write schema/*.json python -m simo |
| 66 | Bash | Check curiosity defaults, the retired v1 tree, and the compat module | === curiosity enabled / auto === 34: # Start with self-directed work held. `auto on` releases it for the 36: # begins. The creator, 2026-09-07: "stop sim's auto |
| 67 | Bash | Read the bus trace writer and sampling config | === trace === """The trace writer: every message -> Ledger stream `trace:<trace_id>`, sampled per type (docs/blueprint/subsystems/01-bus.md section 5.6; 03 sect |
| 68 | Bash | Measure verify verdicts, task kinds, and which message types root the traces | === verify verdicts === 220 "verdict":"fail" 109 "verdict":"pass" 21 "verdict":"insufficient_evidence" === task kinds (2431 task streams) === 73 "kind":"patch"  |
| 69 | Bash | Check channels, SOUL enforcement, Guardian rules, and the worker subcommand | === channels === simorgh/interface/config.py simorgh/interface/service.py simorgh/interface/whatsapp.py simorgh/interface/telegram.py simorgh/contracts/channels |
| 70 | Bash | Count ledger append sites, contracts DSL size, publish-time validation, and v1 imports | === ledger.append sites per package === 11 execution 10 guardian 8 planning 7 kernel 7 interface 3 memory 3 cognition 3 bus 2 voice 2 orchestration 2 learning 1 |
| 71 | Bash | Measure bus events per chat turn and task outcome distribution | === events per chat-turn trace (root percept.text.received, sample) === n=29 min=1 median=1 max=1 mean=1.0 === task terminal outcomes across task streams === 10 |
| 72 | Bash | Check trace depth, task stream events, planning state and the learning outcomes stream | === trace files with >1 events (sample 6000) === 1108 2 292 3 1 12 22 14 1 15 1 30 1 54 1 67 === task stream event types === 4386 "type":"task.step" 3008 "type" |
| 73 | Bash | Gather remaining measurements on Guardian classifier, channels, tests, cadence, routes, and the loader | Exit code 1 === classifier === === telegram/whatsapp === 241 simorgh/interface/telegram.py 267 simorgh/interface/whatsapp.py 508 total === integration tests boo |
| 74 | Bash | Gather the remaining measurements with each step guarded | === boots === 746 "type":"system.state" === http routes === simorgh/interface/dashfeeds.py:0 simorgh/interface/httpapi.py:28 === chat TASK_COMPLETED === simorgh |
| 75 | Bash | Final batch: chat-turn completion path, gate selection, repo sprawl, plan review wiring | === worker chat completion === logger.warning("orchestration.plan_artifact_failed", task_id=session.task_id, error=repr(exc)) async def _report(self, session: S |
| 76 | Bash | Check whether getattr fallback defaults drift from the dataclass defaults, and TASK_PROGRESS wiring | getattr reads matched to a dataclass field: 118 getattr default differs from the dataclass default: 20 ('voice', 'conversation_window_s', 180.0, 0.0, 'voice/ses |
| 77 | Bash | Confirm three getattr-default drift sites against their dataclass defaults | simorgh/execution/config.py:466: tv_show_on_start: bool = False simorgh/execution/service.py:238: # The dashboard on the TV, by itself, when a TV is remembered  |

## Structured reply

**concern:** Proportionality and coherence of the whole: is this the right architecture for one person, one laptop, one family, and for the stated goal of self-improvement?

**summary of what is actually there:** simorgh/ is 86,996 lines in 18 subsystem packages plus contracts, each exposing one `Service` (simorgh/*/service.py; kernel/registry.py:40-46 boots them in six health-gated layers). Subsystems really do talk only over the bus: a grep of `from simorgh.X` across every package finds no subsystem importing another besides the bus/ledger client packages, and tests/simorgh/test_module_boundaries.py enforces it. The bus is in-process (`memory` backend; ~/.simorgh/simorgh.toml has no [bus] or [ledger] section, so bus/config.py:30 `memory` and ledger/config.py:18 `jsonl` are in force, mode `single` per kernel/api.py:34), yet it ships three bus backends (memory/sqlite/aws) and four ledger backends (jsonl/sqlite/dynamodb/memory), a WorkerKernel for a `local-multi` mode, a schema-version translator registry with zero translators (contracts/compat.py), and a JSON-schema projection of all 174 message types "for a non-Python subsystem one day" (contracts/schemagen.py:8). Every effect goes through Guardian: guardian/service.py:171 is the only subscriber to action.proposed, execution/service.py re-verifies the HMAC token, and 26,737 `action:<id>` ledger streams show no bypass -- but 22,849 of them (85%) are the dashboard's Ring WebRTC `offer/keepalive/close` signalling (httpapi.py:476-487 -> `ring_live`), at 3.6 proposals/minute over 107 hours. The Ledger is a directory of one JSONL file per stream plus one idempotency index file per stream: 118,215 stream files and 90,755 idem files, 1.4 GB, of which 88,356 are bus trace streams less than two days old (bus/trace.py writes one stream per trace_id; retention is 2d, compaction runs). The self-improvement loop that actually works is `improve` -> TASK_CREATE -> Orchestration PATCH-profile session in a git worktree -> `worktree_land` (orchestration/session.py:790) -> simloader gate; Sim has authored 94 commits this way (git log --author=Simorgh: 96 files, +8,069/-512). The subsystems that are supposed to learn from that -- World Model change history, Curiosity growth events, Reflection, Planning -- all subscribe to `learn.self_patch.applied`, which is published only by learning/pipeline.py, which runs only on `learn.pipeline.run`, which nothing publishes (learning/service.py:98-116 documents this and reports itself degraded). The live Self Model (~/.simorgh/worldmodel/self/SELF.md, v42) therefore says "What I've changed about myself: (none recorded yet)" and "How well I do it: unknown 97% (2466)", because learning/outcomes.py:84-94 types every chat turn as `unknown` (2,466 of 2,714 rows in learn:outcomes.jsonl). The user-visible surface is large and growing by anecdote: 104 Tool classes, 98 registered under default config (58 effectful), CHAT profile binds 72 tools and VOICE_CHAT 58 (orchestration/profiles.py), 29 CLI commands with 35 verb branches in a 2,234-line dispatch.py, 28 HTTP routes, five house/PIM/knowledge/security/energy "domains" living inside simorgh/execution (10.5k lines). Tests are 90,203 lines (larger than the code), docs 26,150 Markdown lines (EVOLUTION.md 5,254; blueprint 9,095; plans 5,923), and 28.5% of the non-blank lines inside simorgh/ are docstrings or comments, most written as dated changelog entries quoting the creator.

### strengths

- Module boundaries are real, not aspirational: `for p in <15 packages>; grep -rhoE '^(from|import) simorgh\.[a-z_]+' simorgh/$p` finds only bus/ledger client imports outside each package's own name and contracts; tests/simorgh/test_module_boundaries.py:55-128 enforces it. This is the single decision that makes the codebase deletable in pieces -- keep it.
- The action path is genuinely structural: contracts/topics.py:295-313 SUBSCRIBE_ONLY_BY/PUBLISH_ONLY_BY reserve action.proposed to guardian and action.approved to execution; guardian/service.py:171 is the sole subscriber; execution/service.py:139-143 refuses to start without the HMAC secret and re-verifies every approval. A 3,000-stream sample of action:<id> shows received/decided/verified on every one, 5 denied (3 denylist, 2 paused), no bypass.
- Worktree landing plus the loader gate is the right shape for self-modification on a live checkout: orchestration/session.py:790-810 lands via `worktree_land` and returns `blocked` on failure; simloader.py:547-575 gates each boot on the core tests and rolls back. 94 Sim-authored commits landed without bricking the system -- that is measured proof the isolation design works.
- The lesson about silent handler failure was actually institutionalised: bus/factory.py:24-56 `default_handler_error` prints unconditionally to stderr with the three dated incidents that justify it, and is wired by default in make_backend.
- Honest health is a real pattern, not a slogan: learning/service.py:117-125 reports `degraded` with the exact reason its purpose is unreachable; ledger/service.py reports `down` when it cannot persist.
- The two-assembler duplication called out in docs/blueprint/07 is fixed: orchestration/context.py:2-3,133 deliberately excludes persona.voice/self.summary, and cognition/assembler.py:54-60 is the single owner.
- Boot-time config self-check exists (kernel/configcheck.py) and the strict audit confirms it: of 542 dataclass config fields only 10 are unread anywhere in simorgh/ (config_audit.py output: 'TOTAL fields 542 unread anywhere 10').
- The infrastructure share is not the problem: substrate (bus 2,157 + ledger 2,764 + kernel 4,045 + contracts 6,443) is 17.7% of the code; user-facing packages (execution, voice, interface, cognition, orchestration, memory, benchmark) are 65.5%. The proportion is fine; the incoherence is that the 14.7% growth layer is wired to the wrong events.

### findings

##### 1. The self-improvement feedback loop listens on a topic the real self-patch path never publishes

- **kind:** right-design-undermined
- **severity:** critical
- **claim:** World Model, Curiosity, Reflection and Planning all subscribe to `learn.self_patch.applied`, which is published only by learning/pipeline.py's PatchPipeline, which only runs on `learn.pipeline.run`, which nothing publishes; the path that actually lands Sim's code (orchestration/session.py `_land` via `worktree_land`) emits only a generic `task.completed`, so 94 real self-modifications are invisible to the subsystems whose job is to learn from them.
- **evidence:**
  - simorgh/learning/service.py:98-116 -- "Nothing anywhere publishes `learn.pipeline.run` ... The real `improve <path> <description>` path goes through `TASK_CREATE` to Orchestration's ordinary agent loop and never touches Learning at all."
  - grep -rn LEARN_SELF_PATCH_APPLIED simorgh --include='*.py' | grep -v contracts/ -> the only publisher is simorgh/learning/pipeline.py:196; subscribers: simorgh/worldmodel/service.py:121, simorgh/planning/service.py:179, simorgh/curiosity/service.py:159, simorgh/reflection/service.py:193
  - simorgh/orchestration/session.py:790-810 `_land` -> Outcome("completed") only; simorgh/orchestration/worker.py:456-460 maps that to topics.TASK_COMPLETED; simorgh/worldmodel/service.py:382-388 `_on_task_finished` only calls update_goals, never add_change
  - git log --format=%an | sort | uniq -c -> "94 Simorgh"; git log --author=Simorgh --shortstat -> "files 96 ins 8069 del 512"
  - cat ~/.simorgh/worldmodel/self/SELF.md (v42, 2026-09-18 17:09) -> "## What I've changed about myself (last 10)\n(none recorded yet)"
  - tests/simorgh/learning/test_service.py:5 asserts the gap as documented behaviour ("nothing anywhere publishes `learn.pipeline.run`") rather than failing on it
- **why it matters:** This is the stated purpose of the system. The Self Model's change history, Curiosity's growth events, Reflection's self-patch counters and Planning's follow-ups are all built and tested, and all fed by a pipeline that was superseded by the worktree loop. The architecture's growth layer is a spec'd machine bolted next to the machine that runs.
- **recommendation:** Delete learning/pipeline.py and correlator.py (the superseded pipeline) and the `draft_candidate`-shaped topics with them. Have orchestration's `_land` (session.py:790) publish `learn.self_patch.applied` (or rename it `self.patch.landed`, owned by orchestration) with subject, commit sha and test counts on success and `...reverted` on a gate rollback (simloader already knows the rollback; worldmodel/service.py:133 `_ingest_loader_rollback` shows the seam). Add one seam test: run a fake patch task through Orchestration with a stub Execution and assert SELF.md gains a change_history entry.
- **confidence:** 0.95

##### 2. Competence learning records every chat turn as `unknown`, so 91% of the learning signal is noise

- **kind:** bug
- **severity:** high
- **claim:** learning/outcomes.py derives task_type from the first event of `task:<task_id>`; chat turns get a task_id and a `task.completed` but no created event in a task stream, so 2,466 of 2,714 outcome rows are `unknown` with `succeeded=True`, and the Self Model's competence section reports 'unknown 97%'.
- **evidence:**
  - simorgh/learning/outcomes.py:84-94 -- `task_type = "unknown"` then `kind = p.get("kind", "unknown")` from `self._ledger.read(f"task:{task_id}")`; :119-124 on_task_completed records `succeeded=True, weight=1.0` regardless
  - grep -o '"task_type":"[a-z_:]*"' ~/.simorgh/ledger/streams/learn%3Aoutcomes.jsonl | sort | uniq -c -> "2466 unknown / 125 research / 81 patch / 3 skill / 1 project" of 2714 rows
  - task streams: 103 `created` events vs 2334 `task.completed` events (ls | grep '^task%3A' | xargs cat | grep -o '"type":"..."') -- the difference is chat turns
  - ~/.simorgh/worldmodel/self/SELF.md -> "## How well I do it\n- unknown 97% (2466)"
  - docs/blueprint/07-post-cutover-review.md:100-103 named the same defect on 2026-09-06 ("a floor reply and a great reply score identically"); it is still current
- **why it matters:** Curiosity's competence-gap drive, Reflection's calibration and the Self Model's 'how well I do it' all read this table. With 91% of rows typed `unknown` and always successful, every downstream 'learned' number is arithmetic on noise, and the creator cannot tell whether Sim is getting better.
- **recommendation:** Do not record chat turns as competence outcomes at all (they have no verdict), or record them under kind `chat` only when a `verify.result` exists for the turn. Make OutcomeRecorder refuse to write a row whose task_type is `unknown` and count refusals in health. One assertion in the existing integration suite: after a chat turn, learn:outcomes gains no `unknown` row.
- **confidence:** 0.9

##### 3. The Guardian action path is being used as the RPC channel for dashboard video signalling

- **kind:** wrong-design
- **severity:** high
- **claim:** 85% of all Guardian proposals ever made (22,849 of 26,737 action streams) are `ring_live` offer/keepalive/close calls from the dashboard page at 3.6 per minute, each minting an HMAC token, three ledger events and a stream file; the safety audit trail is dominated by UI plumbing that carries no decision.
- **evidence:**
  - ls ~/.simorgh/ledger/streams | grep '^action%3A' | xargs -I{} head -1 {} | grep -o '"tool":"[a-z_]*"' | sort | uniq -c -> "22849 ring_live / 721 cam_stream / 570 run_shell / 473 read_file ..."; proposed_by -> "23560 interface:dash / 2979 orchestration / 18 verification"
  - ring_live actions: "8301 close / 5230 keepalive / 9318 offer"; ts span -> "n=22849 span_hours=106.8 per_minute=3.6"
  - simorgh/interface/httpapi.py:476-487 `_ring_live` -> `_run_for_page("ring_live", args, 30.0)`, route POST /api/dash/ring/live rate=(120, 60.0); :815 `_ACTIVITY_SILENT_TOOLS = frozenset({"ring_live"})` -- the code already knows this traffic is not activity
  - simorgh/execution/home/ring.py:698-703 -- ring_live is WebRTC signalling (`sdp`, `session`), not an effect on the house
  - Guardian decision sample over 3,000 streams: "2995 approved / 5 denied"
- **why it matters:** 'Every effect goes through Guardian' is the right principle for effects; applying it to a keepalive turns the decision log into noise (a human reading `action:*` to answer 'what did Sim do to my house' has to skip 22k rows), costs a ledger stream per call, and trains everyone -- including the model -- to see approval as free. It also inflates the ledger the creator already flagged as 1.4 GB.
- **recommendation:** Classify tools: a session-scoped, read-only signalling call (ring_live keepalive/close, cam_stream renegotiation) should be a `world.*` query or a direct HTTP handler, gated once per session by a single `ring_live offer` proposal whose token authorises the follow-ups. Add `action:` retention for read-only tools (ledger/compaction.py:36 DEFAULT_RETENTION currently keeps action:* forever) and a test that the dashboard's steady state produces zero action.proposed per minute.
- **confidence:** 0.9

##### 4. The per-stream JSONL ledger plus bus tracing produces ~44k files a day for a single-process laptop

- **kind:** wrong-design
- **severity:** high
- **claim:** The Ledger's default backend writes one JSONL file and one idempotency index file per stream, and the bus writes one trace stream per trace_id; the result is 118,215 stream files + 90,755 idem files (1.4 GB) of which 88,356 are traces under two days old, most rooted at broadcast events and containing one event, so the cost is paid and the trace answers nothing.
- **evidence:**
  - du -sh ~/.simorgh/ledger -> "1.4G"; ls streams | wc -l -> 118215; ls idem | wc -l -> 90755 (355M); streams by prefix: "88356 trace / 26737 action / 2431 task / 350 verify"
  - find streams -name 'trace*' -mtime +2 | wc -l -> 0 (retention IS running; the volume is the steady state, ~44k trace streams/day)
  - trace root types (sample 800): "216 ui.hook.received / 196 world.camera.event / 194 persona.state.changed / 192 ui.notice / 120 system.status.request / 102 tool.registered ..." -- bus/config.py:60-63 zeroes only system.tick.*, metrics, health, provider.status
  - trace depth (sample 6000): most streams 1 event; 1108 have 2, 292 have 3; 29 traces rooted at percept.text.received had exactly 1 event each ("n=29 min=1 median=1 max=1") -- a user's message does not root the chain that answers it
  - simorgh/ledger/backends/jsonl.py is 815 lines; simorgh/ledger/backends/sqlite.py is 275 lines and already exists; ~/.simorgh/simorgh.toml has no [ledger] section, so ledger/config.py:18 `backend = "jsonl"` is in force
  - simorgh/bus/trace.py:1-2 "every message -> Ledger stream `trace:<trace_id>`"
- **why it matters:** For one process on one disk the file-per-stream layout is the worst of both worlds: it has SQLite's write amplification without its indexes, it makes `ls` and backups slow, and it makes the append-only-Ledger principle (which is right) look expensive. Tracing that produces one-event chains is pure cost.
- **recommendation:** Make sqlite the default ledger backend (the code exists; migrate_v1.py shows a migration is a known shape). Stop writing traces into the Ledger: either propagate trace_id through request/reply so a percept roots the whole turn (then trace only percept.*, task.*, action.*), or write traces to one rotating file outside the Ledger. Zero-sample `ui.hook.received`, `world.camera.event`, `persona.state.changed`, `ui.notice`, `tool.registered` today as a one-line config change.
- **confidence:** 0.85

##### 5. Three deployment modes and seven backends for a system whose only deployment is one process on one laptop

- **kind:** over-engineering
- **severity:** medium
- **claim:** aws/dynamodb backends, the WorkerKernel/local-multi mode, a schema-version translator registry with no translators, and a JSON-schema projection of 174 message types are all built, tested and documented, and none is in force or on the roadmap the creator is actually executing.
- **evidence:**
  - ls simorgh/bus/backends -> aws.py (269 lines), memory.py, sqlite.py; ls simorgh/ledger/backends -> dynamodb.py (282), jsonl.py, memory.py, sqlite.py
  - cat ~/.simorgh/simorgh.toml -> no [bus], [ledger] or [runtime] section; bus/config.py:30 `backend: str = "memory"`; kernel/api.py:34 `mode: str = "single"`; sim.sh:57 `exec python3 simloader.py run` (no worker processes)
  - simorgh/contracts/compat.py:10-12 "The catalog is at v1 for every type, so this module is currently a registry with no translators"
  - simorgh/contracts/schemagen.py:6-10 "what other tooling -- or a non-Python subsystem one day -- can consume"; ls simorgh/contracts/schema | wc -l -> 174; contracts DSL (fields/registry/validation/schemagen/envelope/compat) -> 810 lines + 1,163 lines of message declarations
  - docs/blueprint/01-vision-and-principles.md:75-79 "Not a distributed system on day one ... reference deployment is one host, one process" -- the blueprint's own non-goal
  - tests referencing aws/dynamodb: tests/simorgh/bus/test_aws_fake.py, tests/simorgh/ledger/test_backends.py -- tested against fakes, never run for real
- **why it matters:** Every one of these is a surface a self-patching agent can wander into, a test the loader gate has to run, and a doc that has to stay true. The cloud modes are the clearest case of a creator constraint ('host anywhere') that costs real weight for zero present value.
- **recommendation:** Freeze, then delete: bus/backends/aws.py, ledger/backends/dynamodb.py, WorkerKernel and the `worker` CLI subcommand, contracts/compat.py, and the schema/*.json projection (keep the in-process validation the DSL gives you; it is cheap and catches real payload mistakes). If 'host anywhere' ever returns, the boundary discipline means the backends can be re-added behind the same Protocols without touching subsystems -- that is the abstraction actually worth keeping.
- **confidence:** 0.85

##### 6. Typed config is read stringly: 123 `getattr(config, "x", default)` sites, 20 with a fallback that contradicts the dataclass default

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** Execution and Voice read their own typed Config dataclasses via getattr with a second, hand-typed default; in 20 sites that default is the opposite of the dataclass's, so behaviour silently flips whenever a test or tool passes a partial config, and the pattern is exactly what lets a 'designed slot nobody reads' hide from kernel/configcheck.py.
- **evidence:**
  - grep -rnE 'getattr\((self\._config|self\.config|config|cfg|self\._cfg), *["\']' simorgh --include='*.py' | wc -l -> 123 (execution 83, voice 37)
  - audit script output: "getattr reads matched to a dataclass field: 118; getattr default differs from the dataclass default: 20"
  - simorgh/execution/config.py:466 `tv_show_on_start: bool = False` vs simorgh/execution/service.py:530 `getattr(self._config, "tv_show_on_start", True)`
  - simorgh/execution/config.py:193 `shell: bool = True` vs simorgh/execution/tools.py:3113 `getattr(config, "shell", False)`
  - simorgh/voice/config.py:192 `conversation_window_s: float = 180.0` vs voice/session.py getattr fallback 0.0; `unplaced_follows_conversation` True vs False
  - kernel/configcheck.py:55-80 KNOWN_DEAD_FIELDS is a hand-maintained list precisely because data-flow dead fields cannot be discovered from the parsed Config
- **why it matters:** The dataclass Config was the right design: one typed source of truth per subsystem. getattr-with-default turns it into a stringly-typed dict with two defaults, which is how the project's dominant bug shape (a wire with one end) reproduces at the config level and how tests can pass against behaviour production never has.
- **recommendation:** Add a boundary-style test that forbids `getattr(<config>, "..."` in simorgh/ (the 5 legitimate cases can be allow-listed), then replace the 123 sites with direct attribute reads. It is a mechanical afternoon and it retires a class of bug.
- **confidence:** 0.9

##### 7. 25 of 137 non-reply topics have only one side (or none), each with a schema file, a declaration and tests

- **kind:** over-engineering
- **severity:** medium
- **claim:** The catalogue is 174 types; after excluding the 37 `.reply` types, 10 are published and never consumed, 9 are subscribed and never published, 5 are declared and never referenced, and 1 is referenced only in a comment -- the 'unconnected wire' shape exists at the contract level and nothing fails on it.
- **evidence:**
  - topics_audit2.py over simorgh/ (excluding contracts/): "{'both': 111, 'unreferenced': 5, 'pub-only': 10, 'reply': 37, 'ref-only': 1, 'sub-only': 10}" (memory.forget was a false positive via an aliased import, so sub-only is 9)
  - pub-only: benchmark.run.completed, curiosity.interest.updated, plan.approved, reflect.alert.cleared, reflect.alert.raised, self.model.updated, system.schedule.added, task.dependency.satisfied, tool.invoked, world.env.observed
  - sub-only: cognition.compact.request, curiosity.discover.request, curiosity.interest.follow_up.request, curiosity.share.request, learn.pipeline.run, learn.strategy.suggest, reflect.review.request, research.finding.recorded (plus task.progress, which is a ledger-only event read by orchestration/resume.py:58 -- not a bus defect)
  - unreferenced: learn.experiment.result, percept.file.changed, plan.reground, plan.reground.reply, system.reload, ui.rendered
  - ls simorgh/contracts/schema | wc -l -> 174; contracts/topics.py:1-8 "CATALOG is the authoritative list ... messages/ must define exactly this set (tests/simorgh/contracts/test_catalog.py proves it)" -- the test proves the catalogue matches itself, not that it is used
- **why it matters:** A catalogue that is 18% one-sided teaches the model (and the next reader) that a topic existing means a capability exists. Three of the sub-only requests are the whole public surface of Curiosity and Reflection review, so those subsystems are partly unreachable by design rather than by bug.
- **recommendation:** Turn the audit script into a test: fail on any CATALOG type that is neither published nor consumed in simorgh/, with a short allow-list of externally-triggered types. Delete the 6 unreferenced types and the dead-pipeline types (learn.pipeline.run, learn.strategy.suggest, learn.experiment.result) with finding 1; decide per remaining item whether to wire or remove.
- **confidence:** 0.8

##### 8. The chat profile now binds 72 tools (58 by voice) and grows by dated anecdote

- **kind:** wrong-design
- **severity:** medium
- **claim:** orchestration/profiles.py CHAT offers 72 tools on every typed turn and VOICE_CHAT 58 on every spoken one (up from the 34 recorded by earlier reviews), including file writes, package installs and script execution with a 20-step budget; every addition in the file is justified by a quoted creator complaint, so the surface only ever grows.
- **evidence:**
  - python3 -c 'from simorgh.orchestration import profiles as p; ...' -> "CHAT 72 max_steps 20 / VOICE_CHAT 58 max_steps 6 / PATCH 25 / RESEARCH 31 / PLAN 9 / SKILL 9; distinct tools offered across profiles 88"
  - builtin_tools(Config()) -> "98 registered ... read_only: 40 effectful: 58"
  - simorgh/orchestration/profiles.py:12-104 -- CHAT's tuple is interleaved with 14 dated comments of the form "(the creator, 2026-09-16)" each adding tools; :55-66 adds apply_source_patch/install_package/run_script to chat
  - simorgh/orchestration/profiles.py:150-170 VOICE_CHAT docstring: "the same drift was found once before, for the Music tools, and patched for those alone"
- **why it matters:** Tool lists are prompt weight and error surface on every turn; a 72-tool chat profile is a task profile with a shorter name. The growth mechanism (add whatever the last complaint lacked) has no counter-pressure, which is the same shape as the config and topic findings.
- **recommendation:** Route by intent instead of by channel: a cheap classifier (or the model's first step) picks one domain bundle (house / cameras+tv / files+code / knowledge+mail / self), each 10-20 tools, with a `more_tools` escape. Keep CHAT itself read-only plus `start_task`; anything that writes becomes a task, which the worktree/gate path already handles well.
- **confidence:** 0.85

##### 9. Docs and tests each outweigh the code, and both certify shape rather than the loop

- **kind:** over-engineering
- **severity:** medium
- **claim:** 26,150 lines of Markdown, 9,095 of them blueprint specs written before the subsystems ran, plus a test suite larger than the code (90k vs 87k lines, 447 files, 33 kernel-booting integration tests) and 28.5% prose inside the source, coexist with the two critical wires above being unasserted -- the volume is a symptom of specifying and narrating instead of driving the one flow that matters.
- **evidence:**
  - find docs -name '*.md' | xargs cat | wc -l -> 26150; EVOLUTION.md 5254; blueprint 9095 across 8 top docs + 17 subsystem specs; docs/plans 5923; READMEs inside simorgh/ 1357
  - tests: 90,203 lines / 447 test files; integration: 44 files, 33 construct a Kernel
  - in-code prose: "code=54320 docstring=11751 comment=9906 ... prose share=28.5%"
  - git rev-list --count HEAD -> 856 commits between 2026-09-03 and 2026-09-18 (16 days)
  - docs/blueprint/07-post-cutover-review.md:310-330 diagnosed exactly this on 2026-09-06 ("No seam tests ... 'built on both sides, connected on neither' is invisible"); finding 1 shows the same shape survived 12 more days and ~600 commits
  - tests/simorgh/learning/test_service.py:5-51 -- a test that pins the broken wiring as expected behaviour
- **why it matters:** For a one-person project the docs:code:tests ratio is a maintenance liability on its own (every self-patch has to keep 26k lines of prose true), but the deeper cost is that certainty is being manufactured in the wrong place: the system reads as thoroughly verified while its purpose is unverified.
- **recommendation:** Freeze EVOLUTION.md (docs/findings/ already exists for dated results) and collapse each subsystem spec to a one-page contract of topics in / topics out / streams owned. Write three end-to-end assertions that drive real subsystems with only the provider faked: (1) a landed patch appears in SELF.md change history, (2) a chat turn adds no `unknown` competence row, (3) a dashboard steady state creates no action streams. Let those three replace a proportional amount of shape-level unit tests.
- **confidence:** 0.75

##### 10. Execution is a 21.6k-line God package holding five product domains, next to a retired 16k-line v1 tree and 11 GB of workspace in the repo

- **kind:** over-engineering
- **severity:** low
- **claim:** Home, media, PIM, knowledge, security and energy (10.5k lines) live inside simorgh/execution rather than as domain packages behind the `extra_tools` seam the service already has, so the subsystem that must stay smallest and most trusted (it holds the HMAC verifier) is 25% of the code and 27% of the tests; src/ (v1) is still in the tree and imported by nothing.
- **evidence:**
  - lines per package: execution 21,590 of 86,996 (24.8%); tests/simorgh/execution 15,098 of 90,203
  - execution subdirs: home 2379, media 2252, pim 2087, knowledge 1995, security 1085, energy 686
  - simorgh/execution/service.py:118-119 `extra_tools`/`connectors` injection seam already exists; :4-7 "Registry and dispatch are kept in this one module for this build (the spec's registry.py/runner.py split is a natural follow-up once the tool count grows past what fits in one screenful)" -- the count is now 104 classes
  - du -sh src -> 2.4M, 16,441 Python lines; grep -rn 'from src\|import src' simorgh tools simloader.py -> none
  - du -sh workspace papers -> 11G, 109M inside the repository root
- **why it matters:** Guardian's ProtectedRule keeps execution/ off-limits to self-patching, which means every house/media/PIM improvement Sim might make to itself is blocked because it shares a package with the token verifier. Splitting domains out makes them patchable and keeps the trusted core small.
- **recommendation:** Move the six domain subpackages to simorgh/domains/<name> registered through `extra_tools` (or a `domains` layer in kernel/registry.py LAYERS), keeping only registry, verifier, sandboxes and worktree in execution; protect only that. Delete src/ (git history keeps it) and move workspace/ and papers/ out of the checkout the loader gates.
- **confidence:** 0.8


### measurements

- Lines per package (find simorgh/<pkg> -name '*.py' | xargs cat | wc -l): execution 21590, voice 11233, interface 10747, contracts 6443, orchestration 5600, kernel 4045, verification 3129, cognition 3119, planning 3064, benchmark 2813, ledger 2764, bus 2157, reflection 2145, memory 1880, guardian 1825, curiosity 1402, worldmodel 1218, learning 992, persona 797; total 86996
- Service classes: 18 `service.py` files, `grep -rn '^class .*Service' simorgh` -> 18 (17 named Service + VerificationService) plus InterestService
- Topics: 174 constants in contracts/topics.py; audit -> both-sided 111, reply 37, pub-only 10, sub-only 9 (after correcting memory.forget), unreferenced 5, ref-only 1
- Message schemas: 174 JSON files in contracts/schema; 1163 lines of declarations in contracts/messages; DSL 810 lines (fields/registry/validation/schemagen/envelope/compat)
- Tools: 104 `class *Tool` in simorgh/execution; builtin_tools(Config()) registers 98 (40 read_only, 58 effectful); profiles CHAT 72, VOICE_CHAT 58, PATCH 25, RESEARCH 31, PLAN 9, SKILL 9; 88 distinct
- Provider adapters: 4 real (claude_code, gemini, ollama, together) + FloorProvider, 822 lines
- Backends: bus 3 (memory 315, sqlite 422, aws 269 lines); ledger 4 (jsonl 815, sqlite 275, dynamodb 282, memory 118); in force: memory bus, jsonl ledger, mode single (no [bus]/[ledger]/[runtime] in ~/.simorgh/simorgh.toml)
- CLI: parser.COMMANDS 29 top-level, 29 documented subcommand groups, 35 `if verb ==` branches in dispatch.py (2234 lines); httpapi.py 28 register_route calls
- Config: 542 dataclass fields across simorgh/*/config.py; strict audit unread-anywhere 10; getattr(config,"x",default) sites 123 (execution 83, voice 37); 20 fallbacks differ from the dataclass default
- Ledger: 1.4G; streams 118215 files (696M); idem 90755 files (355M); blobs 325M; trace streams 88356 (0 older than 2d); action 26737; task 2431; verify 350; reflect 310
- Actions: 22849/26737 are ring_live (8301 close, 5230 keepalive, 9318 offer) from interface:dash, span 106.8h, 3.6/min; Guardian sample of 3000: 2995 approved, 5 denied (3 denylist, 2 paused)
- learn:outcomes.jsonl 2714 rows: task_type unknown 2466, research 125, patch 81, skill 3, project 1; SELF.md v42: 'unknown 97% (2466)', change history '(none recorded yet)'
- Task streams: created 103 (patch 73, research 26, skill 3, project 1; origin benchmark 50, assistant 32, curiosity 9, reflection 5, human 3); task.completed 2334, blocked 69, failed 39; verify verdicts fail 220, pass 109, insufficient_evidence 21
- Git: 856 commits 2026-09-03..2026-09-18; authors Saeed 761, Simorgh 94 (96 files, +8069/-512), iSK 1
- Tests 90203 lines / 447 test_*.py; integration 44 files, 33 construct Kernel(; docs 26150 md lines (EVOLUTION 5254, blueprint 9095, plans 5923, KnowledgeBase 2288); in-code prose 28.5% (docstring 11751, comment 9906 of 76k non-blank)
- Cross-subsystem imports: none outside bus/ledger clients for all 15 non-substrate packages; src/ (v1) 16441 lines, imported by nothing; workspace/ 11G, papers/ 109M in the checkout
- Chat-turn traces: 29 trace streams rooted at percept.text.received, each exactly 1 event; trace depth sample of 6000: 1108 with 2 events, 292 with 3, 27 with >=12

