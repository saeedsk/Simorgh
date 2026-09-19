# propose:embodied

*Workflow: panel · Phase: Propose · Agent id: `a1ed85cc6b6584f61` · Tool calls: 31*

## Task given to the agent

```text
You are on a design panel for Simorgh, a from-scratch personal AI agent. The creator's ask, verbatim: "as a very professional top of the line AI and AI agent scientist and the most expert in this domain, look at the high level architecture of Simorgh, and suggest where we went right and how we should re-architect Sim to make sure Sim is aligned on where the AI agent future lies and be highly performing, highly sophisticated, advanced agent that we can continue investing in, adding features and make more and more intelligent -- and how we can improve its reasoning, ability to perform long tasks, better interact with environment and user, and how building blocks and modules can get improved both in terms of merging modules or adding new modules or algorithms or methods to make sure Sim is a state of the art and cutting edge AI agent and at some point it can be considered AGI."
  
  
  ESTABLISHED FACTS ABOUT SIMORGH TODAY (verified against the code at /Users/saeed/ws/Simorgh on 2026-09-18; do not re-derive, but do read the cited files to understand them):
  - ~87k lines in simorgh/, 18 subsystem packages composed by a Kernel (kernel/registry.py LAYERS), talking only through a typed async Bus (in-memory by default; sqlite and AWS SNS/SQS backends exist), 175 topic constants, 174 JSON schemas. The import rule "only contracts is shared" genuinely holds (only kernel imports other subsystems).
  - All state is an append-only Ledger of events (ledger/backends/jsonl.py, fsync per append). Live ledger: 1.4 GB, 118,215 stream files (88,356 trace:<id>, 26,737 action:<id>, 2,431 task:<id>); biggest single streams are metrics:history 114 MB, curiosity:ticks 43 MB, persona:state 17 MB.
  - Every effect is action.proposed -> Guardian (12 rules, HMAC token) -> action.approved -> Execution (re-verifies token) -> action.result. Structural, bus-enforced, proved at boot.
  - THE MODEL DOES NOT USE NATIVE TOOL CALLING. Every provider adapter (cognition/providers/together.py, claude_code.py, ollama.py, gemini.py) accepts a tools= argument and ignores it. Tool calls are parsed out of free text by a home-grown marker protocol (cognition/parser.py: one string argument per MARKER: line, plus a JSON second-line hack for multi-arg tools; orchestration/tools.py maps markers to tools). One action per step, except batches of read-only calls. Consequently orchestration/session.py (1,942 lines) carries a family of regex police for model text: invented_markers, unhonoured_marker, _transcript_echo (fabricated results), claimed_to_commit, promised_behaviour, claimed_tv_act, claimed_to_note_a_pronunciation -- each a live-caught incident turned into a heuristic.
  - Tool results reach the model bounded at 8,000 chars (session.py _MODEL_RESULT_CHARS) with an explicit "cut" note; ledger detail at 2,000 chars.
  - A CLI chat turn is a THROWAWAY Session: interface mints a fresh session_id per typed line; there is no transcript; continuity = memory recall (orchestration/context.py). Memory recall = hashed bag-of-words embeddings by default (memory/embed.py, sha256 token buckets, 256 dims; "hashing" is the configured default because sentence-transformers cost 24.9 s on first call), scoring EVERY record on every recall (memory/store.py retrieve), under a 0.25 s timeout -- so the memory block silently vanishes once the store is large or the machine is loaded.
  - Cognition: router over five providers (Together primary, Claude CLI, Gemini, Ollama, a deterministic "floor"), per-provider rolling budgets, purpose filters, compaction. Prompt assembly is split between cognition/assembler.py (persona voice + self summary as protected blocks) and orchestration/context.py (memory block + task + carried attempt notes + messages).
  - Growth layer: Learning (outcomes, competence table, self-patch pipeline that names a tool self_patch.draft that does not exist), Reflection (observer only), Curiosity (idle-tick exploration). World Model holds the Self Model; capabilities["tools"] is never written.
  - Self-modification: patch/skill tasks work in a git worktree of the named repo and land on main via rebase + whole-suite gate + fast-forward (docs/plans/worktree-landing-design.md). Boot goes through simloader.py which runs a curated core test set and rolls back to the last sim-good-N tag on failure. Guardian protects docs/SOUL.md, simorgh/{guardian,execution,contracts,kernel}/, simloader.py, sim.sh; tests/ is NOT protected.
  - Voice: 10.2k lines (vad, turns, stt/, tts/, speakers with TitaNet, session.py 1,961 lines, planner, playback, echo tracker). Measured live 2026-09-18: stt 1.8-6.8 s, llm 1.3-9.5 s, full response 4-17 s.
  - Interface: 10.7k lines (CLI/TUI, dispatch.py 2,234 lines of command dispatch, httpapi.py, dashfeeds, Telegram, WhatsApp); subscribes to 30 topics. Live config binds http to 0.0.0.0; auth only if SIM_API_TOKEN is set.
  - Execution: 21.6k lines, 98 tools at runtime across files/code/git, sandboxes, web, packages + domains knowledge/pim/security/home/energy/media. Home Assistant is NOT configured; cameras are RTSP -> local ffmpeg -> HLS on disk; workspace/ is 11 GB (voice 6.4 GB, cameras 3.8 GB).
  - v1 (src/, 16.4k lines, 39 test files) is retired but still in the tree. No pyproject.toml, no ruff/mypy config. 1,118 comments in simorgh/ are dated incident notes ("live-caught 2026-09-07 ...").
  - Test suite: 447 test files / 90k lines (larger than the code); the project's own retrospective (docs/blueprint/07-post-cutover-review.md section 4) concluded unit tests assert code shape and missed every real blocker; real bugs were found by running single watched tasks (tools/trial.py) and observer waves.
  - The creator is one person, hands-free style (delegates heavily to coding agents), runs Sim on one laptop for one family; cloud model is the primary brain, Ollama is fallback only. Stated purpose (docs/SOUL.md): a capable, trustworthy, continuously improving assistant that grows more skilled without growing less safe; corrigibility and restraint are directives.
  
  
  Rules:
  - Read to confirm, do not re-audit: docs/module-map.md, docs/blueprint/01-vision-and-principles.md, docs/blueprint/02-system-architecture.md, and the code paths named above (orchestration/session.py _run and _think, orchestration/context.py, cognition/router.py, cognition/parser.py, memory/store.py, worldmodel/selfmodel.py, guardian/rules.py, learning/service.py, reflection/service.py, curiosity/service.py, voice/session.py top). Do not modify files, do not boot the system, do not run the suite, do not call paid models.
  - Think at the level of architecture, algorithms and methods, not bug fixes. Be specific: name the module, what it becomes, what algorithm/method/data structure replaces what, and what measurable capability it unlocks.
  - Ground every claim about "where agents are going" in patterns that are well established by 2026 and that you are confident about (native structured tool use; single-loop agent harnesses with context management and compaction; sub-agent delegation with isolated contexts; skills/procedural memory; hierarchical planning with verification and critic loops; tiered memory (working/episodic/semantic/procedural) with real embeddings and retrieval indexes; MCP as the tool-integration standard; computer-use/browser agents; eval-driven development; model routing by task; long-horizon agents that checkpoint and resume). If you cite a specific paper or system, only do so when you are sure it exists; otherwise describe the pattern generically. Flag uncertainty explicitly.
  - On "AGI": be honest and precise. Say what an architecture like this can and cannot deliver, what "more general" concretely means for a household agent, and which investments compound.
  - Proportionality: one developer, one laptop, one family, cloud model as brain. Every recommendation must be achievable incrementally without a rewrite from zero, and must preserve the proposal->approval->effect safety invariant and corrigibility.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  LENS: EMBODIED HOUSEHOLD AGENT and human interaction. You design agents that live in a home: voice, presence, multiple people, cameras, devices, proactive behaviour. Re-architect the environment interface (Home Assistant as the single device hub, cameras/events as perception streams, a proper world state of the home, entity/identity model across voice/chat/Telegram/WhatsApp, per-person memory and permissions), the interaction model (turn taking, barge-in, latency targets, when to speak unprompted, when to ask), and how Sim should learn household routines. Say what Voice (10k lines) and Interface (10.7k lines) should become, and how the physical-world action tier should be gated differently from code changes.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Count lines of cited files and list voice/interface/execution packages |  452 docs/module-map.md 241 docs/blueprint/01-vision-and-principles.md 494 docs/blueprint/02-system-architecture.md 1942 simorgh/orchestration/session.py 327 si |
| 2 | Bash | Read the module map | # Simorgh — Module Map and System Blocks **What this is.** One picture of every major building block, what each one owns, and how they interact — written so a s |
| 3 | Bash | Read the vision and principles blueprint | # 01 — Vision and Principles > Part of the Simorgh v2 blueprint. Read `00-README.md` first for how this > set fits together. This file states *what we are build |
| 4 | Bash | Read system architecture blueprint, first half | # 02 — System Architecture > Part of the Simorgh v2 blueprint. Governing principles are in > `01-vision-and-principles.md`; the exact message envelope, topic ca |
| 5 | Bash | Read system architecture blueprint, second half | persona ─persona.state.changed─▶ (emotion agent reacts; mood nudged) [floor: rule-based lexicon] orchestration: opens a TURN session (a lightweight task, kind=c |
| 6 | Bash | Read the top of voice session | """The spoken conversation: microphone frames in, speech out, with the floor changing hands the way it does between people. frames -> FrameVad -> TurnManager -> |
| 7 | Bash | Read orchestration context assembly | """ContextAssembler (16 section 5): gathers the memory block and the session transcript for one `cognition.think` call. The persona voice and the self summary a |
| 8 | Bash | Read session _run loop | 875: async def _run(self, session: Session, *, user_text: str = "") -> Outcome: 1219: async def _think(self, session: Session, user_text: str, *, last_step: boo |
| 9 | Bash | Read session _think |  async def _think(self, session: Session, user_text: str, *, last_step: bool, no_tools: bool = False) -> Message \| None: steps_left = session.budget.steps_left  |
| 10 | Bash | Read router and parser headers | """Provider failover and selection (docs/blueprint/subsystems/04- cognition.md section 5). Ported from v1 `CognitionRouter`'s failover shape: try each candidate |
| 11 | Bash | Read memory retrieve | 4:lexical+embedding similarity times confidence plus a recency term, 106:class MemoryEngine: 238: async def retrieve(self, *, query: str, kinds: list[str], k: i |
| 12 | Bash | Read selfmodel header and world model facets | """The Self Model. Identity is real, loaded and hashed from `docs/SOUL.md`. As of Phase 4 Wave 2 the other sections (competence, limitations, change_history, ca |
| 13 | Bash | Scan guardian rules for reversibility and scope logic | 29:# used by the protected/scope rules to find "the path" in an otherwise 42:def _existing_text(subject: str) -> str \| None: 62:def _added_or_changed_lines(old: |
| 14 | Bash | Read growth-layer service headers | """`Service`: wires `OutcomeRecorder`, `CompetenceTable`, strategy suggestion, and the patch/skill pipeline runner into the real Bus/Ledger (spec section 5). Sc |
| 15 | Bash | List home/media domains and household contracts | Exit code 1 simorgh/execution/energy: __init__.py __pycache__ api.py meters.py tools.py simorgh/execution/home: __init__.py __pycache__ cameras.py registry.py r |
| 16 | Bash | Read home domain tools and registry | """`home_find`, `home_state`, `home_describe`, `home_call`, `home_undo`. `home_call` is the one that matters, and its shape is set by two rules from the design: |
| 17 | Bash | Scan topics for perception/home/presence and list contracts | 48:PERCEPT_TEXT_RECEIVED = "percept.text.received" 49:PERCEPT_FILE_CHANGED = "percept.file.changed" 50:PERCEPT_WEB_FETCHED = "percept.web.fetched" 51:PERCEPT_TI |
| 18 | Bash | Read turn manager and speaker book headers | """The turn manager: who has the floor, and when it changes hands. A voice session is a small state machine -- idle -> listening -> user_speaking -> thinking -> |
| 19 | Bash | Read persona user model and curiosity sharing shape | __init__.py __pycache__ api.py config.py emotion.py mood.py service.py sharing.py user_model.py voice.py simorgh/persona/user_model.py:61:class UserModel: ---SH |
| 20 | Bash | Scan interface for identity across channels | 162: self.session_id = str(uuid.uuid4()) 166: self._turn_started: dict[str, float] = {} # session_id -> monotonic start, for narration timing 200: self._telegra |
| 21 | Bash | Read reversibility rule and physical tools' reversibility declarations | class ReversibilityRule: name = "reversibility" layer = "reversibility" async def evaluate(self, proposal: Proposal, ctx: DecisionContext) -> Decision: r = prop |
| 22 | Bash | Read the home policy classifier and camera event usage | __init__.py __pycache__ api.py client.py fakes.py policy.py """How dangerous is this service call? A pure function, in contracts, so Guardian and the tool that  |
| 23 | Bash | Read the persona user model and overheard contract | """The user model (theory of mind) -- a confidence-weighted facet store (spec section 4's `UserModelProjection`: last-write-wins per facet, confidence merged as |
| 24 | Bash | Read voice chat profile tools and scaffold person rules | 12:CHAT = Profile( 19: tools=("self_map", "read_file", "list_dir", "search_code", "web_search", "web_fetch", 102: tools=("read_file", "list_dir", "search_code", |
| 25 | Bash | Scan voice session for room, bystander and unprompted speech paths | 33:from .backchannel import GREETING, Backchannel, addressed, classify, is_quiet, strip_lead 189: # What the room said lately: (speaker, text, when, asked?) --  |
| 26 | Bash | Read scheduler, cameras and dashboard feeds for perception paths | 14:`ScheduleView` + `parse_duration` port `src/orchestrator/reminders.py`, 15:made durable: a v1 reminder was a `threading.Timer` that a restart 16:simply forgo |
| 27 | Bash | Read vision on camera events, guardian home classification, and design docs list | """What the cameras saw. A camera event says "channel 3, person". That is a fact, and it is not what happened: a person at the side gate at two in the afternoon |
| 28 | Bash | Read home automation design doc and proactive sharing path | # Sim as the brain of the house Design pass, 2026-09-09 (Fable). Implementation is handed to Opus; this document is written so that nothing below needs a design |
| 29 | Bash | Check channel and per-person tagging across orchestration and memory | simorgh/orchestration/profiles.py:227:def for_percept(channel: str) -> Profile: simorgh/orchestration/profiles.py:229: return VOICE_CHAT if channel == "voice" e |
| 30 | Bash | Check whether the home safety classifier reaches Guardian and what the design doc planned | simorgh/contracts/home/policy.py:65:def classify_call(service: str, entity_id: str, *, device_class: str = "", simorgh/contracts/home/policy.py:119: "UNATTENDED |
| 31 | Bash | Check whether proposals carry the requesting person and how home reversibility is set | simorgh/guardian/api.py:56: budgets: Mapping[str, BudgetStatus] = field(default_factory=dict) simorgh/guardian/api.py:73: constraints: dict = field(default_fact |

## Structured reply

**lens:** Embodied household agent and human interaction: voice, presence, several people, cameras and devices, proactive behaviour. Reviewed against the code at /Users/saeed/ws/Simorgh on 2026-09-18 (docs/module-map.md, docs/blueprint/01 and 02, docs/plans/home-automation-design.md, orchestration/session.py _run/_think, orchestration/context.py, orchestration/tools.py, orchestration/profiles.py VOICE_CHAT, orchestration/scaffolds.py who_is_here, cognition/router.py, cognition/parser.py, memory/store.py retrieve, worldmodel/selfmodel.py + service.py facets, guardian/rules.py, contracts/home/policy.py, contracts/household.py, contracts/places.py, contracts/overheard.py, execution/home/{tools,registry,cameras}.py, execution/vision.py, persona/user_model.py, voice/{session,turns,speakers,config}.py, interface/{service,telegram}.py).

### what sim got right

##### 1. One bus-enforced action path: action.proposed -> Guardian (only subscriber) -> HMAC-bound action.approved -> Execution (only subscriber, re-verifies). Every camera siren, light, cast and door call already goes through it (execution/home/cameras.py docstring: 'Every call is a tool call, so Guardian sees it -- the siren above all').

- **decision:** One bus-enforced action path: action.proposed -> Guardian (only subscriber) -> HMAC-bound action.approved -> Execution (only subscriber, re-verifies). Every camera siren, light, cast and door call already goes through it (execution/home/cameras.py docstring: 'Every call is a tool call, so Guardian sees it -- the siren above all').
- **why it matters for the future:** A home agent's failure mode is not a bad answer, it is a bad actuation at 3am. The chokepoint is the one thing that lets presence-aware, person-aware and time-aware rules be added in a single place without any reasoning path being able to route around them. It is also what makes a future 'Home Assistant creates the automation, Sim only proposes it' split enforceable.
- **keep or strengthen:** Keep verbatim. Strengthen by carrying the requesting person and channel on every proposal (today Proposal has no requester field; guardian/api.py) so rules can be per person, and by making Guardian recompute physical safety itself (see divergences).

##### 2. 'Sim does not speak to devices. Sim speaks to Home Assistant.' and 'hard safety automations live in HA, not Sim' (docs/plans/home-automation-design.md section 0), with a pure classify_call in contracts/home/policy.py that is pessimistic by default (unknown domain => human).

- **decision:** 'Sim does not speak to devices. Sim speaks to Home Assistant.' and 'hard safety automations live in HA, not Sim' (docs/plans/home-automation-design.md section 0), with a pure classify_call in contracts/home/policy.py that is pessimistic by default (unknown domain => human).
- **why it matters for the future:** This is the well-established shape for household agents: one device hub with a uniform entity model (entity_id, state, attributes, domain.service), a local rules engine that survives the agent being down, and an agent that owns judgment rather than drivers. Every serious home-agent stack in 2026 sits on HA or an equivalent hub, not on per-vendor code.
- **keep or strengthen:** Keep the decision; actually execute it. HA is not configured today and the designed simorgh/home/ subsystem (bridge, trigger engine, monitors, HomeRule) was never built; only the five home_* tools exist. Section 2.4 (HA events -> percepts) and section 7 (Guardian HomeRule) are the two halves to land first.

##### 3. Honesty rules in the physical layer: 'ambiguity is refused, never guessed' (execution/home/registry.py), 'report what the house did, not what HA accepted' (home_call snapshots before/after), 'unknown is a real answer' with scores travelling on every identification (voice/speakers.py), and may_refine never learning a voice from a shared or guessed turn.

- **decision:** Honesty rules in the physical layer: 'ambiguity is refused, never guessed' (execution/home/registry.py), 'report what the house did, not what HA accepted' (home_call snapshots before/after), 'unknown is a real answer' with scores travelling on every identification (voice/speakers.py), and may_refine never learning a voice from a shared or guessed turn.
- **why it matters for the future:** Trust in a household agent is lost by one confident wrong act: naming the wrong child, turning on the wrong light and saying it was the right one. These rules are the asymmetry a home agent needs: silence and 'I am not sure' are cheap, a wrong actuation is not.
- **keep or strengthen:** Keep and generalise into a single contract for perception claims: every percept (speaker, presence, camera description, entity state) carries a confidence and a source, and the prompt renders the confidence rather than the bare claim.

##### 4. Turn taking as a pure state machine (voice/turns.py: idle/listening/user_speaking/thinking/agent_speaking/interrupted; hybrid end-of-turn with semantic shortening; monotonic turn and response ids so stale audio is dropped) and barge-in gated by an echo tracker fed from what was actually played.

- **decision:** Turn taking as a pure state machine (voice/turns.py: idle/listening/user_speaking/thinking/agent_speaking/interrupted; hybrid end-of-turn with semantic shortening; monotonic turn and response ids so stale audio is dropped) and barge-in gated by an echo tracker fed from what was actually played.
- **why it matters for the future:** Full-duplex, interruptible conversation is the floor for a voice agent in 2026 and the state machine is exactly the piece that must stay testable without a microphone as latency work (streaming STT, sentence-chunked TTS) lands around it.
- **keep or strengthen:** Keep. Strengthen by making the manager consume streaming partials and a streaming reply (so 'agent_speaking' can begin at the first sentence while the model is still generating) and by adding an explicit HOLD state for a proactive utterance waiting for the floor.

##### 5. Household roster and places in contracts (contracts/household.py with names, sexes, ages, IPA; contracts/places.py house name and network->place map; contracts/overheard.py 48-hour store with purge), so the write side (tools) and the read side (prompt) share one source without importing each other.

- **decision:** Household roster and places in contracts (contracts/household.py with names, sexes, ages, IPA; contracts/places.py house name and network->place map; contracts/overheard.py 48-hour store with purge), so the write side (tools) and the read side (prompt) share one source without importing each other.
- **why it matters for the future:** The home agent's most valuable state is small, durable, per-person and per-place. Putting it in contracts is the right instinct for an entity model that every channel and subsystem must agree on.
- **keep or strengthen:** Strengthen into a real people/entity model (person_id with per-channel identities, role tier, per-person permissions and memory namespace) instead of a frozen tuple plus a voice book plus a Telegram allow-list.

##### 6. Per-person memory tags (memory/service.py tags person:<name> on voice turns; orchestration/context.py third recall filtered by person and _theirs() so a child's lines are not shown to a stranger) and scaffolds.who_is_here rendering who is speaking, who spoke before, and the room's asides as 'context, not questions'.

- **decision:** Per-person memory tags (memory/service.py tags person:<name> on voice turns; orchestration/context.py third recall filtered by person and _theirs() so a child's lines are not shown to a stranger) and scaffolds.who_is_here rendering who is speaking, who spoke before, and the room's asides as 'context, not questions'.
- **why it matters for the future:** Multi-person households need memory partitioning and addressee awareness; most agent frameworks assume one user. Sim already has the seeds of both.
- **keep or strengthen:** Keep; extend the person tag to every channel (Telegram/WhatsApp/CLI turns carry no person today) and move the addressee decision out of regexes into a structured percept field.

##### 7. Measuring from the Ledger (voice:turns carries stt/llm/first_audio/response per turn; docs/module-map.md section 8) rather than from unit tests; durable reminders in kernel/scheduler.py rebuilt from the schedule stream.

- **decision:** Measuring from the Ledger (voice:turns carries stt/llm/first_audio/response per turn; docs/module-map.md section 8) rather than from unit tests; durable reminders in kernel/scheduler.py rebuilt from the schedule stream.
- **why it matters for the future:** Latency, addressee accuracy, presence accuracy and false-announcement rate are the handles that decide whether a family keeps using a voice agent. They are only measurable if every turn is recorded with its timings and outcome, which is already true.
- **keep or strengthen:** Keep; add labelled ground truth (who was actually speaking, was it addressed to Sim, who was home) as a small ledger stream the family can correct from the phone, so the handles become precision/recall rather than counts.


### where it diverges from the future

##### 1. There is no perception subsystem. Percept topics are text/file/web/time only (contracts/topics.py PERCEPT_*). Camera events (world.camera.event) are published by Execution's own camera and Ring watchers and consumed by execution/vision.py, which calls Cognition with images and then speaks via voice.speak.request, all inside Execution. The HA event bridge (design section 2.4) does not exist; HA is not configured.

- **current:** There is no perception subsystem. Percept topics are text/file/web/time only (contracts/topics.py PERCEPT_*). Camera events (world.camera.event) are published by Execution's own camera and Ring watchers and consumed by execution/vision.py, which calls Cognition with images and then speaks via voice.speak.request, all inside Execution. The HA event bridge (design section 2.4) does not exist; HA is not configured.
- **future pattern:** Embodied agents have a perception layer that turns sensors into typed, timestamped, confidence-bearing percepts (speech with speaker and room, entity state changes, presence evidence, detections with descriptions) that a world model folds and the policy layer consumes. Actuation and perception are separate subsystems.
- **gap:** Execution is both hands and eyes; nothing can subscribe to 'someone arrived at the front door' as a percept, only to a camera channel number. The intelligent layer the design reserved for Sim ('lights on when motion unless it is 3am and someone just went to bed') cannot be written because the 'someone just went to bed' fact exists nowhere.

##### 2. There is no world state of the home. The only 'room' is a 16-line deque in voice/session.py (self._room), per voice session, lost on restart. World Model facets are codebase-shaped (file_index, git_state, capability_map, tools, user_profile). Presence is not modelled at all; contracts/places.py stores a house name and a network->place map that is TOLD, not detected.

- **current:** There is no world state of the home. The only 'room' is a 16-line deque in voice/session.py (self._room), per voice session, lost on restart. World Model facets are codebase-shaped (file_index, git_state, capability_map, tools, user_profile). Presence is not modelled at all; contracts/places.py stores a house name and a network->place map that is TOLD, not detected.
- **future pattern:** A home world state: HA's area/device/entity registry mirrored locally, live entity states via the HA websocket, a presence belief per person per area fused from evidence (speaker id, device trackers, motion, camera person detections) with decay, and derived situation facts (nobody home, quiet hours, TV playing, a child alone). Rendered as a compact block in every prompt and queryable by rules.
- **gap:** The model reasons about the house from the last 16 spoken lines. Proactive behaviour, routine learning and person-aware safety all need this state and none of them can be built without it.

##### 3. Identity is per channel and never joined: voice -> SpeakerBook name; Telegram -> allow-list by username, then a session per chat_id (interface/telegram.py); WhatsApp similar; CLI -> implicitly the creator; HA person entities unused. action.proposed carries no requester (guardian/api.py Proposal has no person field), so Guardian cannot know whether a 9-year-old or the owner asked for the siren. Persona's user model extracts two regex facets ('I prefer', 'call me') and is one model, not one per person.

- **current:** Identity is per channel and never joined: voice -> SpeakerBook name; Telegram -> allow-list by username, then a session per chat_id (interface/telegram.py); WhatsApp similar; CLI -> implicitly the creator; HA person entities unused. action.proposed carries no requester (guardian/api.py Proposal has no person field), so Guardian cannot know whether a 9-year-old or the owner asked for the siren. Persona's user model extracts two regex facets ('I prefer', 'call me') and is one model, not one per person.
- **future pattern:** A person/entity model: one person_id with linked identities (voice embedding set, Telegram id, WhatsApp number, HA person, CLI), a role tier (owner, adult, child, guest, unknown), per-person permissions on tool groups, a per-person memory namespace and a per-person preference model updated from what they actually do, not only from what they say.
- **gap:** Per-person permissions and step-up verification for dangerous requests are impossible today; per-person memory only works for voice; the same family member is three different strangers across channels.

##### 4. Guardian trusts the proposer's physical safety label. orchestration/tools.py line 700 computes reversibility from classify_call and the comment says 'Guardian recomputes the same answer from the same pure function rather than trusting this', but nothing under simorgh/guardian/ imports classify_call (grep confirms). ReversibilityRule only reads proposal.reversibility. One knob (SIMORGH_GUARDIAN_AUTO_APPROVE, on by default since 2026-09-07) auto-approves irreversible actions for code and for the house alike; policy.py's own docstring says 'for the house that default is wrong'.

- **current:** Guardian trusts the proposer's physical safety label. orchestration/tools.py line 700 computes reversibility from classify_call and the comment says 'Guardian recomputes the same answer from the same pure function rather than trusting this', but nothing under simorgh/guardian/ imports classify_call (grep confirms). ReversibilityRule only reads proposal.reversibility. One knob (SIMORGH_GUARDIAN_AUTO_APPROVE, on by default since 2026-09-07) auto-approves irreversible actions for code and for the house alike; policy.py's own docstring says 'for the house that default is wrong'.
- **future pattern:** Physical actions are gated on a separate axis from code changes: reversibility recomputed at the gate from the arguments, plus who asked, who is present, what time it is, what the alarm state is, per-entity rate limits and safe ranges, with hard safety living in HA. Code changes are gated by tests, worktrees and rollback; a house is gated by people and presence.
- **gap:** The safety invariant is structurally sound but the house-specific rule was designed (home-automation-design.md section 7 HomeRule) and not built; today a forged or mislabelled reversibility from any proposer path other than orchestration/tools.py would be honoured, and the default posture treats a door like a docstring.

##### 5. Proactive behaviour is scattered and uncoordinated: curiosity.sharing -> persona.sharing -> ui.notice (text, hourly cap); execution/vision.py speaks camera descriptions on its own; kernel reminders fire; voice/session.py backchannels. None of them knows who is present, whether someone is asleep, or whether Sim is already mid-conversation.

- **current:** Proactive behaviour is scattered and uncoordinated: curiosity.sharing -> persona.sharing -> ui.notice (text, hourly cap); execution/vision.py speaks camera descriptions on its own; kernel reminders fire; voice/session.py backchannels. None of them knows who is present, whether someone is asleep, or whether Sim is already mid-conversation.
- **future pattern:** A single initiative policy: every unprompted utterance is a proposal scored by urgency and relevance against an interruption cost derived from the world state (who is here, activity, time, channel), with class-specific thresholds (safety alerts always, FYI only when idle, growth notes only in a digest) and channel selection by presence (voice if in the room, phone if away).
- **gap:** Sim can wake a sleeping child to describe the postman, and cannot decide to text the owner instead of speaking to an empty room.

##### 6. Spoken latency is 4-17 s end to end (stt 1.8-6.8 s with whisper large-v3-turbo finalising after end of turn, llm 1.3-9.5 s awaited to completion, then planner, then TTS). The voice profile (orchestration/profiles.py VOICE_CHAT) offers ~60 tools by name in free text with a 6-step marker loop and a 0.25 s memory timeout that silently drops the memory block under load.

- **current:** Spoken latency is 4-17 s end to end (stt 1.8-6.8 s with whisper large-v3-turbo finalising after end of turn, llm 1.3-9.5 s awaited to completion, then planner, then TTS). The voice profile (orchestration/profiles.py VOICE_CHAT) offers ~60 tools by name in free text with a 6-step marker loop and a 0.25 s memory timeout that silently drops the memory block under load.
- **future pattern:** Streaming end to end: streaming STT with early finalisation, token streaming from the model into sentence-boundary TTS, a fast lane (small or local model) for acknowledgements and simple intents, and native structured tool calls so a spoken 'turn the kitchen light off' is one function call, not a parsed marker. First-audio p50 near 1 s is the established bar.
- **gap:** Every second past ~1.5 s is a turn the family will not take. The marker protocol and the 8 regex police in orchestration/session.py exist because tool use is parsed from prose; native tool calling removes the class of bug and most of the latency in the tool path.

##### 7. Dialogue policy is regexes and prompt prose: _WHO_SAID, _WHO_IS_SPEAKING, _I_AM, _TO_SIM in voice/session.py; addressed() heuristics in voice/backchannel.py; exchange windows and bystander logic inside the session; who_is_here prose in scaffolds.py. It lives in Voice only, so a Telegram message from the same person has none of it.

- **current:** Dialogue policy is regexes and prompt prose: _WHO_SAID, _WHO_IS_SPEAKING, _I_AM, _TO_SIM in voice/session.py; addressed() heuristics in voice/backchannel.py; exchange windows and bystander logic inside the session; who_is_here prose in scaffolds.py. It lives in Voice only, so a Telegram message from the same person has none of it.
- **future pattern:** A structured dialogue state shared across channels: each percept carries addressee (to_sim, aside, to_person X) with confidence from a small classifier, the conversation state per person (open thread, last exchange, pending question from Sim), and the model reads it as data. The same policy answers 'who said that' from the world state rather than a regex.
- **gap:** Every new incident becomes another regex in a 1,961-line session file; the policy cannot be measured (no labelled addressee set) or reused across channels.

##### 8. No routine learning. HA history is not read (HA not configured), no trigger engine (design section 4 never built), no procedural memory of household patterns; the persona user model learns from explicit statements only.

- **current:** No routine learning. HA history is not read (HA not configured), no trigger engine (design section 4 never built), no procedural memory of household patterns; the persona user model learns from explicit statements only.
- **future pattern:** Routines mined from the hub's state history and presence: per (entity, service) time-of-day x weekday distributions, co-occurrence within windows (frequent-episode mining), person-conditioned preferences (temperature, brightness, volume) learnt from actual actions; proposed as suggestions, confirmed by a person, then installed as HA automations that run without Sim.
- **gap:** Sim cannot notice that the kitchen lights go off at 22:30 on school nights, so it cannot offer to do it, and cannot know that 23:30 with lights on is unusual.

##### 9. Cameras are RTSP -> local ffmpeg -> HLS segments on disk, with stills and event JSON under workspace/cameras (3.8 GB); detection comes from the NVR's own AI kinds. Ring is a second bespoke path.

- **current:** Cameras are RTSP -> local ffmpeg -> HLS segments on disk, with stills and event JSON under workspace/cameras (3.8 GB); detection comes from the NVR's own AI kinds. Ring is a second bespoke path.
- **future pattern:** An open-source detection and NVR layer (Frigate with go2rtc, as the design's section 1 already chose) publishes person/car/package detections with snapshots and clips over MQTT/HA; the agent consumes events and asks a vision model only about the event crop, not the whole scene.
- **gap:** Sim carries streaming plumbing and retention it should not own, and the 'describe the event not the scene' problem (execution/vision.py, live 2026-09-16) is what Frigate's zones and object tracking already solve.

##### 10. Interface is a 10.7k-line monolith: CLI/TUI, 2,234-line command dispatch, HTTP API + dashboard + dashfeeds, Telegram, WhatsApp, TV page, benchmark views. Voice is a separate 10-11k-line subsystem that also carries dialogue policy, room memory and pronunciation. Chat sessions are throwaway (one session_id per typed line).

- **current:** Interface is a 10.7k-line monolith: CLI/TUI, 2,234-line command dispatch, HTTP API + dashboard + dashfeeds, Telegram, WhatsApp, TV page, benchmark views. Voice is a separate 10-11k-line subsystem that also carries dialogue policy, room memory and pronunciation. Chat sessions are throwaway (one session_id per typed line).
- **future pattern:** Thin channel adapters (audio, CLI, Telegram, WhatsApp, web/WS, TV as an output device) that all produce the same person-resolved percept and consume the same delivery request; a separate admin/observability plane; persistent per-person conversations with a transcript and compaction.
- **gap:** Channel logic and admin logic change for different reasons and are tested differently; the household 'conversation' has no home because each surface owns its own.

##### 11. Memory recall is hashed bag-of-words, scores every record on every call under a 0.25 s timeout; per-person filtering exists only for voice; there is no procedural/routine kind in use by the house.

- **current:** Memory recall is hashed bag-of-words, scores every record on every call under a 0.25 s timeout; per-person filtering exists only for voice; there is no procedural/routine kind in use by the house.
- **future pattern:** Tiered memory (working transcript, episodic per person, semantic facts about people and places, procedural routines) with a real embedding index and hybrid lexical+vector retrieval; recall budgeted in tokens, not by a wall-clock race.
- **gap:** The memory block that carries 'which machine is falcon' or 'Ira's bedtime' vanishes exactly when the house is busy.


### target architecture

**one paragraph:** Keep the substrate exactly as it is (Bus with reserved topology, append-only Ledger, Kernel layers, Guardian as sole approver with HMAC tokens, Execution as sole actor, worktree landing for self-patches). Around it, add the three things a home agent needs and Sim lacks: a Perception subsystem that turns microphones, cameras and the Home Assistant event stream into typed, confidence-bearing percepts; a Home World State inside World Model (entity/area registry, live states, a presence belief per person per area, derived situation facts) that every prompt and every rule reads; and a People model in contracts with one person_id per family member joined across voice, Telegram, WhatsApp, CLI and HA, carrying a role tier, permissions and a memory namespace. Move the conversational policy out of voice/session.py into a cross-channel Attention and Dialogue component that labels each percept with an addressee and keeps one conversation per person; merge the four sources of unprompted speech into one Initiative policy scored against interruption cost and presence. Split the physical-action tier in Guardian onto its own axis (HomeRule recomputing classify_call, PersonRule, PresenceRule, its own auto-approve setting) while code changes keep the test-and-rollback gate. Shrink Voice to audio I/O (VAD, turns, streaming STT, sentence-chunked TTS, speaker embeddings, echo) and shrink Interface to channel adapters plus an admin plane. Replace the marker protocol with native tool calling and add a fast lane so a spoken turn answers in about a second. Learning gains a routine miner over HA history that proposes automations a person confirms and HA runs without Sim. Everything is additive to the existing packages; nothing bypasses proposal -> approval -> effect.

#### modules

###### 1. Perception

- **name:** Perception
- **from:** new package simorgh/perception/, built from execution/vision.py, the cam_watch/ring_watch event loops in execution/home/cameras.py and ring.py, the designed-but-unbuilt HA bridge (docs/plans/home-automation-design.md section 2.4), and Voice's transcript publication
- **responsibility:** Sensors in, typed percepts out. Owns the HA websocket subscription (state_changed, automation_triggered), camera/detection events (from the NVR today, Frigate/MQTT when adopted), the vision look at an event's frames, and the enrichment of a spoken turn (speaker, room/device, addressee guess) before it is published. Never actuates.
- **key algorithms or methods:**
  - HA websocket client with subscribe_events(state_changed) and periodic full-state resync; each change -> percept.home.state_changed{entity_id, old, new, attributes, area, ts}
  - Camera event -> two stills a moment apart -> cognition.think with images and the camera's known static-scene words excluded -> percept.home.detection{camera, area, kinds, description, confidence, snapshot_ref}; move to Frigate's tracked-object events when installed so only the object crop is described
  - Speaker attribution as a percept field: {person_id or unknown, score, margin} from Voice's SpeakerBook, plus room/device id of the microphone
  - Percept dedupe and rate limits per source (a motion sensor flapping is one percept with a count, not forty)
- **interfaces:** Consumes: audio transcripts from Voice (voice.transcript), world.camera.event, HA websocket. Publishes: percept.text.received (unchanged schema plus person_id, channel, device, addressee), percept.home.state_changed, percept.home.detection, percept.presence.evidence. Requests: cognition.think (images).

###### 2. Home World State (World Model facet 'home')

- **name:** Home World State (World Model facet 'home')
- **from:** extends simorgh/worldmodel/ (new facets/home.py, facets/presence.py); absorbs voice/session.py's _room deque and contracts/places.py
- **responsibility:** The single, durable, queryable picture of the house: entity/area/device registry mirrored from HA, current entity states, per-person per-area presence belief, the last N minutes of what was said in each room, and derived situation facts (nobody_home, quiet_hours, someone_asleep, tv_playing, child_alone, alarm_state). Rendered as a compact prompt block and answered as world.env.query{what:'home'}.
- **key algorithms or methods:**
  - Entity state table as a Ledger projection of percept.home.state_changed (rebuildable; snapshot on sleep tick), keyed by entity_id with area from HA's registry
  - Presence: per (person, area) belief updated by evidence likelihoods (speaker id score, HA device_tracker/router presence, motion in an area, camera person detection, a phone message from outside) with exponential time decay; report a distribution and 'unknown', never a bare name
  - Situation facts as small pure rules over states + presence + clock (quiet hours per household config; asleep = bedroom motion silent for T after lights off; child_alone = only child presences above threshold)
  - Room transcript ring per area (replaces the in-session deque) with a 3-minute horizon for asides and 48-hour overheard store from contracts/overheard.py
- **interfaces:** Consumes: percept.home.*, percept.presence.evidence, percept.text.received, voice.spoken. Replies: world.env.query{what: home|presence|room}. Publishes: world.home.situation_changed{fact, value, confidence} for rules and Initiative. Only writer of the home:state projection.

###### 3. People (identity, roles, permissions, per-person memory)

- **name:** People (identity, roles, permissions, per-person memory)
- **from:** merge of contracts/household.py + voice/speakers.py's SpeakerBook identities + interface/telegram.py and whatsapp.py allow-lists (contracts/channels.py) + persona/user_model.py, as a contracts/people.py schema with the store owned by World Model
- **responsibility:** One person_id per household member and per known guest, with linked identities (voice embedding set, Telegram id, WhatsApp number, HA person entity, CLI/owner), a role tier (owner, adult, child, guest, unknown), a permission table over tool groups and home safety classes, a memory namespace, and a preference model updated from actions as well as words.
- **key algorithms or methods:**
  - Identity resolution at the channel edge: every adapter resolves sender -> person_id before publishing a percept; unresolved stays 'unknown' with the raw handle kept for the owner to link
  - Permission matrix: role x {read_only, media, reversible_home, human_home, code, memory_forget} -> allow | ask(owner) | deny; children default to media + read_only + reversible lights in their own area
  - Step-up verification for human-class requests by voice: speaker score >= 0.70 and margin >= 0.10 required, otherwise confirm on the person's phone channel; never from an unknown voice
  - Preference learning per person: exponential moving estimates of chosen brightness/temperature/volume per area from confirmed home_call results; explicit statements still via the existing facet store, now keyed by person_id
- **interfaces:** Readers: Guardian (PersonRule), Orchestration (scaffold who_is_here, memory filters), Initiative (channel selection), Memory (namespace). Writers: the owner via a people_* tool set (link identity, set role, forget person), all through Guardian.

###### 4. Attention and Dialogue Policy

- **name:** Attention and Dialogue Policy
- **from:** extracted from voice/session.py (_bystander, addressed/exchange window, _room_lines, _WHO_SAID/_WHO_IS_SPEAKING/_I_AM answers, backchannel) and orchestration/scaffolds.py who_is_here; new package simorgh/dialogue/ or a sub-package of orchestration
- **responsibility:** Decide, for every percept from any channel, whether it is addressed to Sim, an aside, a command, a question, or a reply to Sim's pending question; keep one open conversation per person with a bounded transcript; answer identity questions from the world state; hand a turn to Orchestration with the right profile, speaker and situation.
- **key algorithms or methods:**
  - Addressee classification as a scored decision: name/wake mention, question shape, speaker continuity within an exchange window, whether Sim asked something of this person, gaze-less heuristics from the room record, and a fast-lane model call for ambiguous cases; output {label, confidence}, below threshold -> record as aside, never answer
  - Per-person conversation state (open thread id, last exchange ts, pending_question) persisted as a Ledger projection so a Telegram reply continues the kitchen conversation
  - Clarification policy: ask exactly when an ambiguity would change an actuation (registry Ambiguous) or when the addressee score is mid-band and the utterance is a command; otherwise stay silent
  - Labelled-set evaluation: the owner marks 'that was for Sim / not for Sim / wrong person' from the phone; precision/recall on that set is the module's handle
- **interfaces:** Consumes: percept.text.received (enriched). Publishes: turn.requested{person_id, channel, profile, situation} to Orchestration, dialogue.aside.recorded to World State. Replies: dialogue.who_said, dialogue.state for prompts.

###### 5. Initiative (unprompted behaviour)

- **name:** Initiative (unprompted behaviour)
- **from:** merge of curiosity/sharing.py + persona/sharing.py + execution/vision.py's announce step + delivery of kernel/scheduler.py reminders + voice backchannel greetings
- **responsibility:** The only path by which Sim speaks or messages without being asked. Scores each candidate utterance against the interruption cost implied by the home world state, picks the channel by presence, and proposes the delivery as an action so Guardian and the Ledger see it.
- **key algorithms or methods:**
  - Utility = urgency(class) x relevance(person) - cost(activity, time, channel); classes: safety_alert (always, all channels), event_fyi (only when someone is present and not asleep, else to the owner's phone), reminder (to its person, wherever they are), growth/news (only in a requested digest or when idle with an adult present)
  - Presence-aware routing: voice in the area where the person is (belief > 0.6), else phone channel, else queue for the next time they address Sim
  - Per-person do-not-disturb windows, per-class cooldowns, and a hard daily cap; every delivery is action.proposed{tool: speak|notify, reversibility: 'attention'} so 'Sim talks too much' is a Guardian posture, not a code change
  - Floor coordination with the turn manager: a proactive utterance waits for LISTENING/idle and yields to any person speaking
- **interfaces:** Consumes: world.home.situation_changed, percept.home.detection, schedule.fired, curiosity.share.proposed, persona.share.proposed. Publishes: action.proposed (deliveries), initiative.suppressed{why} for measurement. Executes via existing voice.speak.request and channel send tools.

###### 6. Voice (audio I/O only)

- **name:** Voice (audio I/O only)
- **from:** keep simorgh/voice/ but shrink: vad.py, turns.py, stt/, tts/, speakers.py (embeddings only), playback.py, aec.py, delivery.py, pronounce.py stay; session.py loses room memory, bystander, identity regexes and who-said answers
- **responsibility:** Microphone frames to text with speaker vectors and timing; text to speech with streaming, barge-in and echo suppression; nothing about who the person is beyond the embedding, nothing about what to say.
- **key algorithms or methods:**
  - Streaming STT as the primary path (stt/sherpa_stream.py zipformer) with the hybrid end-of-turn using its partials; large-v3-turbo only as an offline rescoring lane for kept audio
  - Reply streaming: accept a token stream from Cognition, split at sentence boundaries through the planner, synthesise sentence n+1 while n plays; first audio target < 1.0 s after the reply starts
  - Fast lane: a canned/cached acknowledgement or a small-model one-liner when the main model is expected to exceed 2 s (predicted from the tool set requested), spoken as a bridge, never as the answer
  - Per-device sessions (several microphones/rooms) each with its own TurnManager, echo tracker and calibration; a device id travels on every transcript
- **interfaces:** Publishes: voice.transcript{device, text, partial|final, speaker_vector_ref, score}, voice.spoken. Consumes: voice.speak.request (now with priority and 'may_interrupt' from Initiative). Metrics per turn unchanged in voice:turns.

###### 7. Channels (thin adapters) and Admin plane

- **name:** Channels (thin adapters) and Admin plane
- **from:** split of simorgh/interface/: cli/tui + telegram.py + whatsapp.py + httpapi WS chat + tv page become simorgh/channels/; httpapi dashboard, dashfeeds.py, vitals.py, benchmarkview.py, panel.py become simorgh/admin/; dispatch.py becomes a command registry
- **responsibility:** Channels: resolve sender to person_id, publish the same enriched percept as voice, deliver replies and initiative messages, keep one conversation per person per channel. Admin: observe-then-control plane behind auth, where every control is itself a guarded action.
- **key algorithms or methods:**
  - Command registry: each 'sim command' is a declared tool with a schema, callable from CLI, Telegram or voice through the same path (dispatch.py's 2,234 lines become data plus small handlers)
  - Persistent conversations: a session_id per (person, channel) that survives lines and restarts, with a transcript projection and compaction, replacing the throwaway session per typed line
  - HTTP: bind 127.0.0.1 by default, require SIM_API_TOKEN for anything but the LAN TV page; WhatsApp/Telegram webhooks verified as today
  - TV and Cast as output devices registered in the world state (area, capabilities) so Initiative can choose them
- **interfaces:** Publishes percept.text.received (person-resolved). Consumes turn.completed, initiative deliveries. Admin reads Ledger projections and proposes control actions through Guardian.

###### 8. Guardian (physical tier on its own axis)

- **name:** Guardian (physical tier on its own axis)
- **from:** keep simorgh/guardian/; add rules from home-automation-design.md section 7 plus person and presence rules; split config
- **responsibility:** Unchanged as the sole approver. Adds a physical-action axis whose posture, auto-approve setting and rules are separate from the code-change axis.
- **key algorithms or methods:**
  - HomeRule: for home_call, cam_*, ring_*, media/cast and any tool tagged physical, recompute classify_call from the proposal's args (never trust proposal.reversibility), apply CLIMATE_HARD_LIMITS, ALWAYS_HUMAN_SERVICES, alarm state from the world state, per-entity rate limits (no more than N toggles per minute), and 'nobody home => no unlock, no disarm'
  - PersonRule: requester person_id and role from the proposal against the People permission matrix; unknown or child requesting human-class -> deny with a spoken reason; adult requesting human-class -> escalate to the owner's phone with a one-tap approve that mints the token
  - PresenceRule: a human-class approval by voice requires the approving person to be present (belief > 0.8) and speaker-verified; otherwise the phone path
  - Config: [guardian.physical] auto_approve = false, irreversible_requires_human = true, independent of [guardian] used by sim.sh's SIMORGH_GUARDIAN_AUTO_APPROVE; tightening automatic (a denied unlock attempt raises posture for an hour), loosening only by the owner
- **interfaces:** Same topics; Proposal gains requester{person_id, role, channel, verified} and physical{service, entity_id, area} fields in contracts/messages/action.py.

###### 9. Execution home actuation (kept, narrowed)

- **name:** Execution home actuation (kept, narrowed)
- **from:** keep simorgh/execution/home/, media/, energy/; remove watchers and vision (to Perception); add automation and scene tools
- **responsibility:** Do exactly what was approved against HA and the media devices, and report what the house actually did.
- **key algorithms or methods:**
  - home_call unchanged (before/after snapshot, undo table); add home_scene_apply and home_automation_create/enable/disable (all human class; YAML rendered from a Sim routine proposal) so learnt routines run inside HA
  - Registry seeded from HA's area/device registry rather than name fuzzing alone; ambiguity still refused
  - Camera actuation (siren, PTZ, lights) stays; streaming to the TV moves to go2rtc/Frigate URLs when adopted
  - Workspace retention: snapshots and HLS bounded by age and size; clips belong to the NVR
- **interfaces:** Unchanged action.approved -> action.result; new tool schemas registered as native tool definitions.

###### 10. Routine Learning (in Learning)

- **name:** Routine Learning (in Learning)
- **from:** new module simorgh/learning/routines.py; reads HA history via Perception's state projection; writes procedural memory
- **responsibility:** Find recurring household patterns and per-person preferences, propose them as suggestions, and hand a confirmed one to HA as an automation.
- **key algorithms or methods:**
  - Per (entity, action) time-of-day x weekday histograms with kernel smoothing; a routine candidate when a mode has support >= 4 weeks and concentration >= 0.6 of occurrences within a 30-minute window
  - Episode mining: co-occurrences within a 10-minute window across entities and presence changes (arrive_home -> hallway light + thermostat) with minimum support and confidence; person-conditioned when presence attribution is confident
  - Anomaly flag: an expected routine that did not happen (lights still on past the learnt window with someone_asleep) becomes an Initiative candidate of class event_fyi
  - Suggestion lifecycle in the Ledger: proposed -> shown -> accepted|declined|snoozed; declined twice is never proposed again; accepted -> home_automation_create (human class) with the person's confirmation as the approval
- **interfaces:** Consumes home:state projection and presence history on system.tick.sleep. Publishes learn.routine.proposed to Initiative, memory.store{kind: procedural}. Proposes actions only through Guardian.

###### 11. Memory (tiered, per person)

- **name:** Memory (tiered, per person)
- **from:** keep simorgh/memory/; replace the default embedder and add namespaces
- **responsibility:** Working transcript per conversation, episodic per person, semantic facts about people/places/devices, procedural routines and skills; retrieval budgeted in tokens.
- **key algorithms or methods:**
  - Real sentence embeddings (the existing sentence-transformers adapter, warmed at boot in a thread so the 24.9 s first call never lands on a turn) with an on-disk vector index; hybrid score = lexical BM25 + cosine + recency + confidence
  - Namespaces: person:<id> tag on every channel's turns (not only voice), household-shared facts explicit; recall filters by the requester and by role (a child's diary lines never surface to a guest)
  - Retrieval budget in tokens with a hard floor that always includes the last K working turns; the 0.25 s race replaced by an index that answers in tens of ms
  - Consolidation on sleep writes people/place/device facts to semantic memory and routines to procedural memory
- **interfaces:** Unchanged memory.retrieve/store; filters gain person_id and role.

###### 12. Cognition (native tools, lanes)

- **name:** Cognition (native tools, lanes)
- **from:** keep simorgh/cognition/; providers implement tools=; add a lane router
- **responsibility:** Native structured tool calls on every provider that supports them, the marker parser kept only as the floor; a fast lane for acknowledgements, intent classification and addressee scoring; the main lane for reasoning; a vision lane for percepts.
- **key algorithms or methods:**
  - Tool schemas generated from Execution's registered tools (already JSON-described) and passed natively; parallel tool calls allowed for read-only groups; the regex police in orchestration/session.py retired one by one as each incident class becomes impossible
  - Lane routing by purpose: ack/intent/addressee -> small fast model (local or cheapest cloud) with a 400 ms budget; chat/draft -> primary; vision -> a multimodal provider; each lane with its own rolling budget
  - Streaming completion surfaced on the bus (cognition.think.partial) so Voice can start speaking at the first sentence
- **interfaces:** cognition.think gains stream=true and lane; replies carry structured tool_calls.


#### merges

- curiosity/sharing.py + persona/sharing.py + execution/vision.py announce step + reminder delivery -> Initiative (one policy for all unprompted speech)
- contracts/household.py + voice SpeakerBook identities + Telegram/WhatsApp allow-lists + persona/user_model.py -> People model (one person_id across channels)
- voice/session.py room/bystander/identity regexes + scaffolds.who_is_here -> Attention and Dialogue Policy (cross-channel)
- execution/vision.py + cam_watch/ring_watch loops + the designed HA bridge -> Perception
- voice/session.py _room deque + contracts/places.py -> Home World State facet
- interface CLI/TUI + telegram + whatsapp + WS chat + TV page -> Channels; interface dashboard/dashfeeds/vitals/benchmark views -> Admin plane; dispatch.py -> command registry of declared tools

#### additions

- simorgh/perception/ with the HA websocket bridge (percept.home.state_changed) and detection percepts
- worldmodel facets: home (entity/area/state projection), presence (per-person per-area belief with decay), situation facts
- contracts/people.py schema + people_* tools (link identity, set role, forget) + requester fields on action.proposed
- Guardian HomeRule/PersonRule/PresenceRule and a separate [guardian.physical] posture and auto-approve setting
- Initiative policy with interruption cost, presence-aware channel choice, class thresholds, and every delivery as a guarded action
- Routine miner in Learning and home_automation_create/enable/disable tools (human class)
- Streaming path: cognition.think.partial, sentence-chunked TTS, streaming STT as primary, fast lane for acks
- Native tool calling in every provider adapter; tool schemas generated from the registry
- Real embedding index with per-person namespaces; persistent per-(person, channel) conversations with compaction
- Labelled ground-truth streams (addressee, speaker, presence corrections from the phone) as the evaluation sets for the household handles
- Frigate/go2rtc adoption for cameras (design section 1) with Sim consuming MQTT/HA events; workspace retention policy

#### deletions or freezes

- Freeze the marker protocol (cognition/parser.py, orchestration/tools.py marker maps) as the floor only; stop adding marker hints
- Retire the regex police in orchestration/session.py (invented_markers, unhonoured_marker, _transcript_echo, claimed_*) one per incident class as native tool calling and the Initiative/People model make each impossible; keep the ledger record of why each existed
- Delete the ffmpeg->HLS relay and on-disk camera event JSON once Frigate/go2rtc serves streams and events; bound workspace/cameras
- Remove the single SIMORGH_GUARDIAN_AUTO_APPROVE from covering physical tools; it may keep covering code
- Drop the throwaway session-per-typed-line in interface/service.py _handle_chat once persistent conversations exist
- Freeze new features in voice/session.py until room memory, bystander and identity regexes have moved out; the file is the home of every per-turn-fact-in-session-state bug
- Retire src/ (v1) from the tree; it is a 16k-line attractor for coding agents' searches


### capability programs

##### 1. Reasoning (for a household: situated reasoning over who, where, when, and what the house is doing)

- **capability:** Reasoning (for a household: situated reasoning over who, where, when, and what the house is doing)
- **current state:** The model reasons from persona + self summary + a memory block (hashed bag-of-words, silently dropped past 0.25 s) + the last 16 spoken lines of one microphone + a 60-tool marker list; no house state, no presence, no structured addressee; tool calls parsed from prose with 8 regex guards; one action per step; chat sessions are throwaway.
- **method:** Give the model the situation as data, not prose: a compact 'house block' (areas with notable states, presence distribution, situation facts, time and quiet-hours flag) and a 'dialogue block' (who is speaking with what confidence, addressee label, open thread with this person, pending question) assembled by Orchestration from world.env.query{home, presence} and dialogue.state; native tool calling with schemas generated from the registry so a spoken command is one structured call; lane routing (fast model for ack/intent/addressee, primary for reasoning, vision for frames); a verify step for physical actions that reads home_call's before/after snapshot and says what changed. Reasoning quality then comes from the frontier model plus grounded context, which is the pattern that works in 2026: structured tool use, context management, critic loops on effects.
- **how to measure:** A household eval set of 200 spoken/typed requests with labelled correct tool call and correct addressee (built from the ledger's voice:turns and corrected from the phone): tool-call exact-match rate, wrong-entity actuation rate (must be 0), clarification-when-ambiguous rate, and answer correctness on 'who/where/what is on' questions against the world state. Track per model in simorgh/benchmark alongside GAIA/BFCL.
- **first increment:** Implement tools= natively in cognition/providers/together.py and claude_code.py for the VOICE_CHAT profile only; generate schemas from Execution's registry; add the house block from a stub 'home' facet fed by a manual HA state dump; run the 200-case set before and after. Two weeks.

##### 2. Long tasks (household horizon: hours to weeks, e.g. 'watch the driveway tonight', 'keep the house at 21 while Soodeh is home', 'learn when we go to bed')

- **capability:** Long tasks (household horizon: hours to weeks, e.g. 'watch the driveway tonight', 'keep the house at 21 while Soodeh is home', 'learn when we go to bed')
- **current state:** Long work exists only as code tasks with step budgets, leases and worktrees; a spoken turn is 6 steps; reminders are durable one-shots; there is no standing intent, no trigger engine (designed, unbuilt), no checkpointed monitors; a 'watch' is a tool that runs until the process dies.
- **method:** Standing intents as Ledger-backed objects (design section 4's rule shape: trigger, conditions, action, expiry, owner person, class) evaluated by a small engine on percepts and situation changes, never by a model in the loop per event; each firing is a normal action.proposed with the intent as requester context; the model is used to compile a spoken request into an intent (with a read-back confirmation) and to summarise outcomes, not to poll. Long-horizon checkpointing: an intent's state (last fired, count, suppressed reasons) is a projection rebuilt on restart (Flow 7). Hard safety intents are never Sim's: they are installed into HA as automations through the human-class tool. Sub-tasks with isolated contexts (delegate exists) handle the research half of a long household job.
- **how to measure:** Intent survival across restart (100%), firing latency from percept to action.proposed (p95 < 2 s), false firings per week on the labelled situation stream, and the fraction of standing intents that expire or are cancelled by the owner as 'annoying' (target < 10%). Ledger streams intent:<id> make all four countable.
- **first increment:** Build the intent object and engine over the existing schedule stream plus percept.home.state_changed, with three intents: 'tell me when someone is at the front door after 22:00', 'lights off in the kitchen when nobody has been there for 20 minutes', 'remind Aran at 20:30 on school nights'; all firings through Guardian; two weeks after the HA bridge exists.

##### 3. Environment interaction (Home Assistant as the hub, cameras and events as perception, actuation gated by people and presence)

- **capability:** Environment interaction (Home Assistant as the hub, cameras and events as perception, actuation gated by people and presence)
- **current state:** Five home_* tools over HA REST (HA not configured), Reolink/Ring tools with bespoke watchers, ffmpeg HLS relays, Cast/Android TV tools; classify_call exists but Guardian does not recompute it; no HA event ingestion; no presence; cameras described whole-scene by a vision model.
- **method:** Perception subsystem with an HA websocket bridge (state_changed -> percepts) and a full-state resync; Frigate/go2rtc for detection and streams with Sim consuming tracked-object events; a home world state projection with presence belief fusion (speaker id, device trackers, motion, detections, decay); Guardian HomeRule/PersonRule/PresenceRule on a separate physical axis with its own auto-approve default false; home_call unchanged in shape (ambiguity refused, before/after snapshot, undo); automation create/enable/disable as human-class tools so routines run inside HA; registry seeded from HA's area/device registry. Every physical effect remains proposal -> approval -> effect.
- **how to measure:** Percept lag from HA state change to projection (p95 < 500 ms on LAN); presence accuracy against a one-week diary the family corrects from the phone (per-person area accuracy > 85%, unknown reported rather than wrong); actuation correctness on the eval set (wrong entity 0, refused-ambiguous rate); human-class attempts that reached Execution without a person's approval (must be 0, with a self-check drill like the forged-token one); camera announcements judged 'described the event, not the scene' > 90%.
- **first increment:** Install HA on a separate box per the design, configure HOME_ASSISTANT_URL/TOKEN, add the Guardian HomeRule that imports classify_call and recomputes from args, add [guardian.physical] with auto_approve=false, and add a kernel self-check drill that proposes lock.unlock with reversibility='reversible' and asserts it is escalated. One week; it closes the most serious gap before anything else grows.

##### 4. User interaction (turn taking, barge-in, latency, several people, when to speak unprompted, when to ask)

- **capability:** User interaction (turn taking, barge-in, latency, several people, when to speak unprompted, when to ask)
- **current state:** Solid turn manager and barge-in gate; 4-17 s spoken responses; addressee and identity by regex inside voice/session.py; no per-person conversation across channels; proactive speech from four uncoordinated sources; bystander suppression by exchange windows; children handled by prompt prose; no labelled data for any of it.
- **method:** Latency: streaming STT primary, LLM token streaming into sentence-boundary TTS, fast-lane acknowledgements, native tool calls; target first audio p50 <= 1.2 s, p95 <= 2.5 s from end of speech for tool-free turns. Turn taking: keep the state machine, add a HOLD state for initiative and per-device sessions. Addressee: a scored classifier over name mention, question shape, exchange continuity, pending question, with a fast-model tie-break; below threshold means silence. Identity: People model with speaker verification scores and step-up on the phone for human-class requests. Proactivity: Initiative policy with interruption cost from presence/activity/time, presence-aware channel choice, class thresholds, daily caps, every delivery a guarded action. Asking: ask only when the answer changes an actuation or the addressee is mid-band on a command; otherwise act or stay quiet. Children: role tier limits tools and initiative classes, not just tone.
- **how to measure:** From voice:turns and the new labelled streams: first-audio p50/p95 per turn class; addressee precision/recall (target > 0.9/0.85) on a 500-line labelled set including asides and cross-talk; speaker misattribution rate (< 2%, unknown allowed); false-interruption rate from barge-in (crow-and-TV set); unprompted utterances per day per person and the fraction the family marks unwanted (< 10%); clarification questions per actuation request (bounded, not zero).
- **first increment:** Wire cognition.think.partial -> planner -> StreamingSynthesiser so Sim speaks the first sentence while the model is still writing, and make sherpa streaming the primary STT with whisper as the rescoring lane; measure first_audio before and after on the same 50 spoken turns. Two weeks; it is the change the family notices most.

##### 5. Self-improvement (for a household: learning routines, preferences and identities safely, plus the existing code-level path)

- **capability:** Self-improvement (for a household: learning routines, preferences and identities safely, plus the existing code-level path)
- **current state:** Code self-patching works (worktree, gate, rollback); competence table per task type; curiosity explores the codebase; persona learns two regex facets; the speaker book refines voices under strict rules; nothing learns from the house; the self model's capabilities['tools'] is never written; reflection observes but does not act.
- **method:** Three learning loops with different gates. (1) Routine mining from HA history and presence (time-of-day x weekday histograms, windowed episode mining, person-conditioned preferences) producing suggestions with a proposed -> shown -> accepted/declined lifecycle; accepted routines become HA automations through a human-class tool, so learning changes the house only with a person's yes and runs without Sim afterwards. (2) Identity and preference refinement from confirmed events (speaker takes from verified solo turns as today; brightness/temperature/volume estimates from confirmed home_call results; corrections from the phone as labelled data). (3) Code self-patching as today, but driven by the household handles: an eval-driven loop where a regression in addressee precision or first-audio p95 opens a patch task with the failing cases attached. Reflection's findings feed the Self Model's competence per household task type (actuation, identification, announcement) so Initiative and Guardian posture can read 'I misidentify voices in the car'. Loosening any gate stays human-only.
- **how to measure:** Routine suggestions accepted / shown (target > 40% after a month), routines later disabled by the owner (< 15%); preference estimate error on held-out actions; speaker-book precision over time; the household eval set's scores per release (no metric may drop across a bless); number of learning-driven changes that reached HA without a person's approval (0).
- **first increment:** After four weeks of HA history exists: the histogram miner over light/switch/climate events with a weekly digest of at most three suggestions delivered through Initiative to the owner only; accepted ones rendered as HA automation YAML and installed via the human-class tool. Three weeks including the tool.


### migration path

##### 1. 0. Close the physical-safety gap and stand up the hub

- **stage:** 0. Close the physical-safety gap and stand up the hub
- **weeks:** 1
- **does:** Install Home Assistant on a separate box (design section 1), configure HOME_ASSISTANT_URL/TOKEN; add Guardian HomeRule importing contracts/home/policy.classify_call and recomputing from proposal args; add [guardian.physical] posture with auto_approve=false and irreversible_requires_human=true, separate from the code axis and from sim.sh's SIMORGH_GUARDIAN_AUTO_APPROVE; add a kernel self-check drill (mislabelled lock.unlock must be escalated); add requester{person_id, role, channel, verified} to action.proposed with 'unknown' as the default.
- **unlocks:** Every later stage can add physical actuation without widening risk; the design's core decision becomes real.
- **risk:** Low. Purely additive; the only behaviour change is that house actions stop being auto-approved, which the policy docstring already says is right.

##### 2. 1. People model and person-resolved channels

- **stage:** 1. People model and person-resolved channels
- **weeks:** 2
- **does:** contracts/people.py (person_id, linked identities, role tier, permission matrix, memory namespace) with a store in World Model; channel adapters resolve sender -> person_id (Telegram/WhatsApp ids, CLI = owner, voice = speaker book match with score); Guardian PersonRule over the matrix; memory tags person:<id> on every channel; scaffolds read role and relation from the model instead of the frozen tuple.
- **unlocks:** Per-person permissions (a child cannot trigger the siren), per-person memory across channels, step-up verification later.
- **risk:** Medium: identity linking mistakes are the new failure class; keep 'unknown' as the default and make every link an owner action through Guardian.

##### 3. 2. Perception subsystem and Home World State

- **stage:** 2. Perception subsystem and Home World State
- **weeks:** 3
- **does:** New simorgh/perception/ with the HA websocket bridge (percept.home.state_changed, full resync), move execution/vision.py and the cam/ring watchers into it as detection percepts; World Model gains the home facet (entity/area/state projection) and presence facet (belief fusion with decay) and situation facts; Orchestration renders a house block into every prompt; voice/session.py's _room moves to the room transcript ring in the world state.
- **unlocks:** Situated reasoning, presence-aware anything, the trigger engine, routine mining. Also the first honest answer to 'who is home'.
- **risk:** Medium: presence fusion over-claims if evidence weights are guessed; ship it reporting distributions and measure against a diary before any rule depends on it.

##### 4. 3. Streaming voice path and native tool calls for the spoken profile

- **stage:** 3. Streaming voice path and native tool calls for the spoken profile
- **weeks:** 3
- **does:** cognition.think.partial streaming; planner splits at sentence boundaries into StreamingSynthesiser; sherpa streaming STT primary with whisper rescoring; fast lane for acknowledgements; tools= implemented natively in Together/Claude/Gemini adapters for VOICE_CHAT with schemas generated from the registry; marker parser retained as the floor.
- **unlocks:** First-audio p50 near 1 s; the spoken command becomes one structured call; two or three regex guards can be retired immediately.
- **risk:** Medium-high on regressions in echo/barge-in (earlier audio starts while the mic is open) and provider differences in tool-call schemas; gate with the existing voice bench and the 50-turn latency set.

##### 5. 4. Attention and Dialogue Policy extracted, persistent conversations

- **stage:** 4. Attention and Dialogue Policy extracted, persistent conversations
- **weeks:** 2
- **does:** Move addressee/bystander/exchange-window/who-said logic out of voice/session.py into a cross-channel dialogue module producing {addressee, confidence} per percept and a per-(person, channel) conversation with a transcript projection and compaction; replace the session-per-typed-line in interface with the same conversation object; add the phone-side correction commands that build the labelled set.
- **unlocks:** Measurable addressee precision; the same conversation continues from kitchen to Telegram; voice/session.py drops to audio plumbing.
- **risk:** Medium: it touches the file with the most live-caught fixes; port each regex as a test case in the labelled set before deleting it.

##### 6. 5. Initiative policy

- **stage:** 5. Initiative policy
- **weeks:** 2
- **does:** One module for all unprompted speech: merge curiosity/persona sharing, camera announcements and reminder delivery; utility vs interruption cost from the world state; presence-aware channel choice; per-person DND and class caps; every delivery as action.proposed{reversibility: attention}; HOLD state in the turn manager.
- **unlocks:** Sim can be proactive without being a nuisance, and 'too chatty' becomes a Guardian posture the owner can set.
- **risk:** Low-medium: the merge changes when existing shares arrive; measure unwanted-utterance rate from the phone corrections for two weeks before raising any class threshold.

##### 7. 6. Standing intents and routine learning

- **stage:** 6. Standing intents and routine learning
- **weeks:** 3
- **does:** Intent objects and a small engine over percepts and situation changes (design section 4 rule shape) with Ledger projections and restart survival; the routine miner (histograms, episode mining, person-conditioned preferences) producing a weekly digest of at most three suggestions; home_automation_create/enable/disable as human-class tools rendering HA YAML; competence per household task type into the Self Model.
- **unlocks:** Long-horizon household work and the first learning that compounds outside code; hard safety stays in HA.
- **risk:** Medium: needs ~4 weeks of HA history first (start collecting at stage 2); a rule engine that fires on noisy presence is the annoyance risk, so intents require situation facts with confidence thresholds.

##### 8. 7. Interface split, cameras on Frigate, memory index, cleanup

- **stage:** 7. Interface split, cameras on Frigate, memory index, cleanup
- **weeks:** 3
- **does:** Split interface into channels/ and admin/ with a declared command registry; bind HTTP to localhost with token by default; adopt Frigate/go2rtc for detection and streams, delete the ffmpeg HLS relay and bound workspace/cameras; switch memory to the real embedding index warmed at boot with per-person namespaces and a token budget; retire src/ and the remaining regex police whose incident classes are now impossible.
- **unlocks:** Two smaller, separately testable surfaces; camera events that name tracked objects; memory that does not vanish under load.
- **risk:** Low-medium: mostly moves; the Frigate adoption needs the HA box to have the compute (a Coral or CPU headroom).


**agi honesty:** Plainly: this architecture is a harness around a frontier model, and its reasoning ceiling is that model's. It can become a highly competent, trustworthy, continuously improving household agent, and 'more general' has a concrete meaning here that is worth investing in: (1) it handles requests nobody wrote a feature for by composing a large, honest tool surface over one device hub with a world state it can actually read; (2) it treats a family as several people with their own memory, permissions and preferences rather than one user; (3) it acts on its own initiative with judgment about presence, time and interruption; (4) it learns the household's routines and installs them where they run without it; (5) it improves its own code against measured household handles with a gate and rollback. Those five compound: every new HA integration, every corrected identification, every accepted routine and every labelled turn makes the next request easier. What it cannot become: a self-contained general intelligence. There is no weight-level learning; 'self-improvement' is memory, skills, routines and audited code; perception is limited to microphones, cameras and hub state; embodiment is limited to what HA can actuate; and its judgment on novel situations is bounded by the cloud model's, filtered through a context this architecture assembles. The regex police, prompt prose and marker protocol do not compound and should not be mistaken for intelligence work. If 'AGI' is used at all for this project it should stay as the blueprint's own stance (01 section 2.1): a queryable competence and calibration per household task type in the Ledger, never a claim. A useful honest target for 2027 is 'the most trustworthy agent in this house': zero unapproved physical effects, sub-second first audio, presence and addressee accuracy the family stops noticing, and routines it learnt that still run when it is switched off.

**biggest risk of this proposal:** That the house layer grows before the identity and physical-safety layers do. A presence-aware, proactive agent with today's identity model (three unjoined per-channel identities, no requester on proposals, Guardian trusting the proposer's reversibility label, one auto-approve knob covering doors and docstrings, speaker id that once filed the creator under Aran) is a safety problem, not a feature: a misidentified voice plus 'trusted' mode is a child unlocking the front door. So stage 0 and stage 1 are prerequisites, not options, and the whole program depends on Home Assistant actually being installed, which the design has said for nine days and nobody has done. The second risk is the same one the codebase has already met twelve times: designed slots with one side built (the home subsystem, the trigger engine, the HomeRule, the People model) left as unconnected wires because coding agents build the half that is easy to unit test. The mitigation is the project's own lesson: every stage ends with one watched live run of the primary interface (a spoken turn in the kitchen, a Telegram message from outside) and a number read from the Ledger, and a stage that cannot show its handle moving does not get blessed.

