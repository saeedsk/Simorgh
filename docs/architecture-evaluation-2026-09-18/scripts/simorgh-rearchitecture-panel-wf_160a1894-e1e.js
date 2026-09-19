export const meta = {
  name: 'simorgh-rearchitecture-panel',
  description: 'Judge panel of four independent re-architecture proposals for Simorgh, scored by three judges, then synthesised',
  phases: [
    { title: 'Propose', detail: 'four architects, four lenses' },
    { title: 'Judge', detail: 'three judges score every proposal' },
    { title: 'Synthesise', detail: 'one target architecture with the best grafts' },
  ],
}

const FACTS = `
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
`

const CONTEXT = `
You are on a design panel for Simorgh, a from-scratch personal AI agent. The creator's ask, verbatim: "as a very professional top of the line AI and AI agent scientist and the most expert in this domain, look at the high level architecture of Simorgh, and suggest where we went right and how we should re-architect Sim to make sure Sim is aligned on where the AI agent future lies and be highly performing, highly sophisticated, advanced agent that we can continue investing in, adding features and make more and more intelligent -- and how we can improve its reasoning, ability to perform long tasks, better interact with environment and user, and how building blocks and modules can get improved both in terms of merging modules or adding new modules or algorithms or methods to make sure Sim is a state of the art and cutting edge AI agent and at some point it can be considered AGI."

${FACTS}

Rules:
- Read to confirm, do not re-audit: docs/module-map.md, docs/blueprint/01-vision-and-principles.md, docs/blueprint/02-system-architecture.md, and the code paths named above (orchestration/session.py _run and _think, orchestration/context.py, cognition/router.py, cognition/parser.py, memory/store.py, worldmodel/selfmodel.py, guardian/rules.py, learning/service.py, reflection/service.py, curiosity/service.py, voice/session.py top). Do not modify files, do not boot the system, do not run the suite, do not call paid models.
- Think at the level of architecture, algorithms and methods, not bug fixes. Be specific: name the module, what it becomes, what algorithm/method/data structure replaces what, and what measurable capability it unlocks.
- Ground every claim about "where agents are going" in patterns that are well established by 2026 and that you are confident about (native structured tool use; single-loop agent harnesses with context management and compaction; sub-agent delegation with isolated contexts; skills/procedural memory; hierarchical planning with verification and critic loops; tiered memory (working/episodic/semantic/procedural) with real embeddings and retrieval indexes; MCP as the tool-integration standard; computer-use/browser agents; eval-driven development; model routing by task; long-horizon agents that checkpoint and resume). If you cite a specific paper or system, only do so when you are sure it exists; otherwise describe the pattern generically. Flag uncertainty explicitly.
- On "AGI": be honest and precise. Say what an architecture like this can and cannot deliver, what "more general" concretely means for a household agent, and which investments compound.
- Proportionality: one developer, one laptop, one family, cloud model as brain. Every recommendation must be achievable incrementally without a rewrite from zero, and must preserve the proposal->approval->effect safety invariant and corrigibility.
- Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
`

const PROPOSAL_SCHEMA = {
  type: 'object',
  properties: {
    lens: { type: 'string' },
    what_sim_got_right: { type: 'array', items: { type: 'object', properties: { decision: { type: 'string' }, why_it_matters_for_the_future: { type: 'string' }, keep_or_strengthen: { type: 'string' } }, required: ['decision', 'why_it_matters_for_the_future', 'keep_or_strengthen'] } },
    where_it_diverges_from_the_future: { type: 'array', items: { type: 'object', properties: { current: { type: 'string' }, future_pattern: { type: 'string' }, gap: { type: 'string' } }, required: ['current', 'future_pattern', 'gap'] } },
    target_architecture: {
      type: 'object',
      properties: {
        one_paragraph: { type: 'string' },
        modules: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, from: { type: 'string', description: 'which current package(s) it comes from: keep / merge of X+Y / new / delete' }, responsibility: { type: 'string' }, key_algorithms_or_methods: { type: 'array', items: { type: 'string' } }, interfaces: { type: 'string' } }, required: ['name', 'from', 'responsibility', 'key_algorithms_or_methods', 'interfaces'] } },
        merges: { type: 'array', items: { type: 'string' } },
        additions: { type: 'array', items: { type: 'string' } },
        deletions_or_freezes: { type: 'array', items: { type: 'string' } },
      },
      required: ['one_paragraph', 'modules', 'merges', 'additions', 'deletions_or_freezes'],
    },
    capability_programs: {
      type: 'array',
      description: 'one per capability the creator named: reasoning, long tasks, environment interaction, user interaction, self-improvement',
      items: { type: 'object', properties: { capability: { type: 'string' }, current_state: { type: 'string' }, method: { type: 'string', description: 'the algorithm / loop / data structure, concretely' }, how_to_measure: { type: 'string' }, first_increment: { type: 'string' } }, required: ['capability', 'current_state', 'method', 'how_to_measure', 'first_increment'] },
    },
    migration_path: { type: 'array', items: { type: 'object', properties: { stage: { type: 'string' }, weeks: { type: 'number' }, does: { type: 'string' }, unlocks: { type: 'string' }, risk: { type: 'string' } }, required: ['stage', 'weeks', 'does', 'unlocks', 'risk'] } },
    agi_honesty: { type: 'string', description: 'what this architecture can and cannot become, plainly' },
    biggest_risk_of_this_proposal: { type: 'string' },
  },
  required: ['lens', 'what_sim_got_right', 'where_it_diverges_from_the_future', 'target_architecture', 'capability_programs', 'migration_path', 'agi_honesty', 'biggest_risk_of_this_proposal'],
}

const LENSES = [
  { key: 'harness', prompt: 'LENS: the modern agent HARNESS. You have built and studied the best 2026 coding/computer-use agent harnesses (single agent loop, native tool use, context management and compaction, sub-agents with isolated context, skills, hooks, permission modes, resumable sessions). Re-architect Sim\'s loop (orchestration + cognition + the marker protocol + profiles + scaffolds) as such a harness while keeping Guardian in the path of every effect. Be concrete about the message/turn model, tool schema, parallel tool calls, streaming, compaction, delegation, and what the bus is still for.' },
  { key: 'cognitive', prompt: 'LENS: COGNITIVE ARCHITECTURE and long-horizon autonomy. You are an AI scientist who works on memory, planning, world models, reflection and continual learning for agents. Re-architect Sim\'s memory (tiers, real embeddings, indexes, consolidation, forgetting, supersession), its self model and world model (what should be state, what should be a learned/estimated quantity), planning for multi-day tasks (goal trees, checkpoints, re-grounding, verification, critic), and the growth loop (learning -> competence -> behaviour change; reflection that actually changes prompts/policies/skills; curiosity as directed exploration). Say which of Learning/Reflection/Curiosity/Persona/WorldModel should merge, and what algorithms make the loop close.' },
  { key: 'systems', prompt: 'LENS: PRODUCTION SYSTEMS and evaluation. You build reliable long-running agent systems. Evaluate the substrate choices (bus + event-sourced ledger + per-message trace streams + fsync per append + 18 packages in one process) against the actual load and the actual need (one process, one laptop, resume after crash, auditability). Propose the substrate a 2026 expert would run: what stays event-sourced, what becomes a relational/sqlite state store with projections, how tracing should work (OpenTelemetry-style spans per turn, not a file per message), how latency budgets are enforced end to end for the voice path, how evals (task suites, replayable traces, regression benchmarks per capability) replace shape-testing, and how model routing (frontier vs. fast vs. local) should be decided per step. Include the safety tiers.' },
  { key: 'embodied', prompt: 'LENS: EMBODIED HOUSEHOLD AGENT and human interaction. You design agents that live in a home: voice, presence, multiple people, cameras, devices, proactive behaviour. Re-architect the environment interface (Home Assistant as the single device hub, cameras/events as perception streams, a proper world state of the home, entity/identity model across voice/chat/Telegram/WhatsApp, per-person memory and permissions), the interaction model (turn taking, barge-in, latency targets, when to speak unprompted, when to ask), and how Sim should learn household routines. Say what Voice (10k lines) and Interface (10.7k lines) should become, and how the physical-world action tier should be gated differently from code changes.' },
]

phase('Propose')
const proposals = (await parallel(LENSES.map(l => () =>
  agent(CONTEXT + '\n\n' + l.prompt, { label: `propose:${l.key}`, phase: 'Propose', schema: PROPOSAL_SCHEMA, effort: 'xhigh' })
    .then(p => p && ({ ...p, key: l.key }))
))).filter(Boolean)
log(`${proposals.length} proposals in`)

const SCORE_SCHEMA = {
  type: 'object',
  properties: {
    scores: { type: 'array', items: { type: 'object', properties: {
      key: { type: 'string' },
      fit_to_reality: { type: 'number', description: '0-10: grounded in what Sim actually is; achievable by one developer incrementally' },
      technical_soundness: { type: 'number' },
      future_alignment: { type: 'number', description: '0-10: matches where capable agents are demonstrably going' },
      capability_gain: { type: 'number', description: '0-10: reasoning, long tasks, environment, user interaction' },
      safety_preserved: { type: 'number' },
      best_ideas_to_graft: { type: 'array', items: { type: 'string' } },
      weakest_point: { type: 'string' },
    }, required: ['key', 'fit_to_reality', 'technical_soundness', 'future_alignment', 'capability_gain', 'safety_preserved', 'best_ideas_to_graft', 'weakest_point'] } },
    overall_winner: { type: 'string' },
    cross_cutting_disagreements: { type: 'array', items: { type: 'string' }, description: 'where the proposals contradict each other and which side is right, with reasoning' },
  },
  required: ['scores', 'overall_winner', 'cross_cutting_disagreements'],
}

phase('Judge')
const JUDGE_LENSES = ['a sceptical staff engineer who has to maintain it', 'an AI-agent researcher judging technical depth and future alignment', 'the creator\'s advocate: one person, one laptop, wants compounding capability without a rewrite']
const judgements = (await parallel(JUDGE_LENSES.map((who, i) => () =>
  agent(CONTEXT + `\n\nYou are JUDGE ${i + 1}: ${who}. Score each of the four proposals below on every criterion, name the best ideas to graft from each, and resolve where they contradict each other. Verify any claim about Sim's code that a score depends on by reading the file. Return only the structured scores.\n\nPROPOSALS:\n${JSON.stringify(proposals, null, 1)}`,
    { label: `judge:${i + 1}`, phase: 'Judge', schema: SCORE_SCHEMA, effort: 'xhigh' })
))).filter(Boolean)

phase('Synthesise')
const synthesis = await agent(
  CONTEXT + `\n\nYou are the SYNTHESISER. Four proposals and three judgements are below. Produce ONE target architecture for Simorgh that takes the winning proposal's spine and grafts the best-scored ideas from the others, resolving the judges' disagreements explicitly. Structure it exactly as the proposal schema, but make it the definitive version: a module table (name / from / responsibility / algorithms / interfaces), the merges and additions and deletions, five capability programs (reasoning, long tasks, environment interaction, user interaction, self-improvement) each with method + measurement + first increment, a staged migration path with weeks, and an honest AGI paragraph. Where the proposals disagreed, say which you chose and why in the relevant field. Verify against the code anything you are not sure of. Return only structured output.\n\nPROPOSALS:\n${JSON.stringify(proposals, null, 1)}\n\nJUDGEMENTS:\n${JSON.stringify(judgements, null, 1)}`,
  { label: 'synthesis', phase: 'Synthesise', schema: PROPOSAL_SCHEMA, effort: 'xhigh' }
)

return { proposals, judgements, synthesis }
