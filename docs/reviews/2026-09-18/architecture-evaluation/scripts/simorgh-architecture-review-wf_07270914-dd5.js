export const meta = {
  name: 'simorgh-architecture-review',
  description: 'Independent architecture review of Simorgh: parallel deep readers per concern, adversarial refutation of every finding, completeness critic',
  phases: [
    { title: 'Read', detail: 'one deep reader per architectural concern, code over docs' },
    { title: 'Refute', detail: 'two skeptics per finding try to disprove it against the code' },
    { title: 'Critic', detail: 'what did the readers miss' },
  ],
}

const CONTEXT = `
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).

The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."

Ground rules for you:
- Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
- Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
- Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
- Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
- Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
- Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
`

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    concern: { type: 'string' },
    summary_of_what_is_actually_there: { type: 'string', description: '5-15 sentences: how this concern is really implemented today, as read from the code, with file paths' },
    strengths: { type: 'array', items: { type: 'string' }, description: 'design choices that are genuinely good, each with evidence' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          kind: { type: 'string', enum: ['wrong-design', 'right-design-undermined', 'bug', 'over-engineering', 'missing'] },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          claim: { type: 'string', description: 'one precise sentence' },
          evidence: { type: 'array', items: { type: 'string' }, description: 'file:line references and/or quoted command output' },
          why_it_matters: { type: 'string' },
          recommendation: { type: 'string', description: 'concrete, proportionate to a one-person project' },
          confidence: { type: 'number' },
        },
        required: ['title', 'kind', 'severity', 'claim', 'evidence', 'why_it_matters', 'recommendation', 'confidence'],
      },
    },
    measurements: { type: 'array', items: { type: 'string' }, description: 'numbers you measured with commands, quoted' },
  },
  required: ['concern', 'summary_of_what_is_actually_there', 'strengths', 'findings', 'measurements'],
}

const READERS = [
  {
    key: 'bus-ledger-substrate',
    prompt: `CONCERN: the substrate -- Bus, Ledger, and the event-sourcing claim.
Read simorgh/bus/ (client, core, policy, enforcement, backends), simorgh/ledger/ (client, store, projections, backends/jsonl.py, backends/sqlite.py, compaction), simorgh/contracts/envelope*.py and contracts/topics.py.
Questions to settle from code: Is the bus really the only path (or do subsystems share objects/ctx)? What are the delivery semantics (at-most-once? ordering? backpressure? what happens when a handler raises or is slow -- there was a 300s per-handler timeout once)? Is "every message is also a ledger event" literally true, and what does that cost (count streams in ~/.simorgh/ledger/streams if present; du -sh)? Are projections actually rebuilt from the log or are there in-memory-only state holders? What does the memory-backend bus do under load (queues, unbounded growth)? Is the SQLite ledger backend used anywhere real? Is the trace:<id> stream design sane at this scale? Is the AWS SNS/SQS backend dead weight? Evaluate: is event-sourcing + message bus the right architecture for a single-process personal agent, and if the design is right, where does the implementation undermine it?`,
  },
  {
    key: 'kernel-lifecycle-config',
    prompt: `CONCERN: composition root, lifecycle, configuration, and the boot/rollback harness.
Read simorgh/kernel/ (kernel.py or service.py, registry.py, config.py, secrets.py, selfcheck.py, cli.py, ticks/scheduler), simloader.py, sim.sh, simorgh/__main__.py, and ~/.simorgh/simorgh.toml (redact secrets mentally; do not print secrets).
Questions: How does config reach subsystems, and how many subsystems actually read their config section (a memory note claims 12 subsystems ignore their config -- verify today by grepping for how each Service consumes ctx.config)? How is shutdown handled (there was an os._exit hard-exit path -- is that a sign of a lifecycle design problem)? How are threads vs asyncio mixed (grep to_thread, threading.Thread, run_in_executor) and is there a coherent concurrency model? Is the bootloader's gate (running the test suite on boot) a sound design, what does it cost in boot time, what does it protect against and what does it not? Does the self-check prove what it claims? Are there global singletons/module-level state that break the "subsystem talks only via bus" story? Evaluate the lifecycle design.`,
  },
  {
    key: 'agent-loop-orchestration',
    prompt: `CONCERN: the agent loop itself -- Orchestration workers, sessions, step budgets, context/prompt assembly, tool routing, profiles, scaffolds, delegation, resume.
Read simorgh/orchestration/ thoroughly (service.py, worker.py, session.py, context.py, profiles.py, tools.py, scaffolds, delegation, claims/leases) and how it calls cognition (cognition.think request/reply over the bus) and tools (action.proposed -> guardian -> execution -> action.result).
Questions: Trace one chat turn and one code task end to end through the actual code; how many bus round-trips and ledger writes does ONE tool call cost, and is that latency structurally necessary? How does the model see tool results (there was a 200-char truncation bug once -- what is the limit now)? How is the prompt assembled -- system prompt size, what is injected each step, is there prompt caching-friendly stable prefix ordering? How do profiles pick tools and is the routing declarative or scattered? What does resume-from-ledger actually replay? Is the worker/lease/claim design (consumer groups, heartbeat leases) proportionate for a single process? Where is the loop's correctness fragile (retries, step budget, memory carried across attempts)? Evaluate the agent-loop design against how state-of-the-art agent harnesses are built in 2026 (single loop, tool results as messages, context compaction, sub-agents).`,
  },
  {
    key: 'safety-guardian-execution',
    prompt: `CONCERN: the safety topology -- Guardian rules, HMAC tokens, Execution's tool protocol and sandboxes, protected paths, denylist, worktree landing, and what the self-modification path really permits.
Read simorgh/guardian/ (rules.py, config.py, service.py, tokens), simorgh/execution/ (service.py, tools.py, verifier.py, worktrees, sandboxes, safety/path/net modules, run_shell/run_remote gating), simorgh/verification/ checks, simorgh/learning/pipeline.py, docs/plans/worktree-landing-design.md briefly.
Questions: What actually stops Sim from harming the creator's machine or accounts today? Enumerate the tools that can reach the filesystem, network, shell, subprocess, credentials, house devices; for each say what gate applies. Is the Guardian's rule set evaluating the RIGHT thing (the proposal payload) or something a model could route around (e.g. write_file to a path outside the worktree; run_python_sandboxed spawning subprocess; web_fetch to LAN; a tool that itself shells out)? Is the HMAC token scheme adding real security inside one process, or ceremony? Is the protected-path list complete (what about sim.sh, simloader.py, tests/, .git hooks, ~/.simorgh config, the ledger)? Does 'auto-approve irreversible' combined with worktree landing mean Sim can land arbitrary code on main with only the test suite as gate -- and can it edit tests? Are physical-world actions (locks, cameras, TV) gated differently from code? Evaluate whether the safety design is proportionate and where its real holes are.`,
  },
  {
    key: 'cognition-memory-selfmodel',
    prompt: `CONCERN: the cognitive core -- Cognition provider router and budgets, prompt/compaction, Memory (episodic/semantic, embeddings, recall), World Model / Self Model, and the growth loop (Learning, Reflection, Curiosity) that feeds it.
Read simorgh/cognition/ (router, providers/*, budgets, compaction, prompt assembly), simorgh/memory/ (service, store/engine, recall, consolidation, embeddings), simorgh/worldmodel/ (selfmodel.py, facets), simorgh/learning/, simorgh/reflection/, simorgh/curiosity/ (skim the services: what do they subscribe to, what do they emit, and who consumes what they emit -- does anything downstream actually CHANGE behaviour because of a competence estimate, a reflection finding, or a curiosity idea?).
Questions: What are the embeddings (real model or a hash/bag-of-words floor)? What is recall quality likely to be and is memory ever used in a prompt that matters? Is the "self-improving" claim backed by a closed loop (outcome -> competence -> different behaviour next time), or is it write-only telemetry? Is the provider failover design sound (the Together day cap silently failed over to the Claude CLI once)? Is the floor provider a good idea or does it mask outages? Is there a coherent notion of a conversation/session across chat, voice, and tasks? Evaluate: which of these subsystems earn their existence as separate packages, and which are speculative scaffolding?`,
  },
  {
    key: 'voice-interface-surfaces',
    prompt: `CONCERN: the human surfaces -- Voice pipeline and Interface (CLI/TUI, HTTP API + dashboard, Telegram/WhatsApp), Persona, and how a turn's identity (who is speaking, which session, which language) flows.
Read simorgh/voice/ (session.py, turns.py, vad.py, speakers.py, stt/, tts/, planner.py, playback.py, service.py) and simorgh/interface/ (service.py, cli.py, tui.py, render.py, httpapi.py, telegram.py, whatsapp.py), simorgh/persona/.
Questions: Is the voice pipeline's state machine sound -- where is per-turn state kept and is it read across awaits (a known bug shape: per-turn fact in a session singleton read across an await)? How is the mic/echo/barge-in problem handled and is it robust? Why is voice 11k lines -- what is in there, and is it the right decomposition? Interface subscribes to 30 topics and is 10.7k lines: is it a god-module, and is the HTTP API a security exposure (0.0.0.0 host in live config; auth only if SIM_API_TOKEN set; what routes can trigger actions; CSRF; camera/HLS serving)? Is there one session/identity model across CLI, voice, Telegram, WhatsApp, or several ad-hoc ones? Does Persona do anything observable? Evaluate the surfaces layer design.`,
  },
  {
    key: 'tools-domains-integrations',
    prompt: `CONCERN: the tool layer -- Execution's 98 tools across files/code/git, sandboxes, web, packages, and the six domain packages (knowledge, pim, security, home, energy, media), plus external toolsets and MCP.
Read simorgh/execution/tools.py (registry, Tool protocol), a representative sample of tools, simorgh/execution/home/, media/, pim/, security/, energy/, knowledge/, external.py, mcp*.py, and orchestration/tools.py (router policy per tool).
Questions: Is the Tool protocol well designed (schema, result shape, error reporting, truncation, idempotency, reversibility metadata, cost/latency metadata)? How much of the 21.6k lines is dead or speculative (tools never called in the ledger -- if ~/.simorgh/ledger has action streams or a tool-usage projection, measure which tools were ever invoked; otherwise estimate from tests and wiring)? Are integrations (Home Assistant not configured; Reolink direct; Ring; Cast; Android TV; energy) built to the right abstraction (device vs hub), and are they consistent with each other? Is there an honest 'capability floor' (stdlib-only) or has optional-dependency sprawl made behaviour unpredictable? Is 'domains' the right axis of decomposition or should tools be organised by risk class? Evaluate the tool layer.`,
  },
  {
    key: 'testing-observability-process',
    prompt: `CONCERN: verification of the whole -- test suite shape, integration/e2e tests, the trial harness, observer kit, benchmark unit, tracing/observability, docs/findings process, and the Verification subsystem's role.
Read tests/ layout (count per subsystem; find integration/e2e tests, tests/simorgh/integration/test_cli_end_to_end.py), conftest.py, tools/ (trial.py, trial_suite.py, observer_kit.py, bench_instance.py), simorgh/verification/, simorgh/benchmark/ briefly, docs/findings/README.md, docs/observer-testing.md.
Questions: The project's own notes say unit tests assert code shape and missed every real blocker; is the suite (90k lines, 447 files -- larger than the code) giving proportional confidence, or is it mostly mock-heavy shape testing? Count tests that boot real subsystems vs. pure unit. How long does the suite take (do NOT run it; read notes/CI config/markers)? Is the bootloader gate running THIS suite, and if so is it gating on tests that would not catch the failures that matter? Is there any load/latency/regression benchmark for the daily path (chat + voice)? Is tracing (trace:<id> streams) usable for debugging a bad turn, or noise? Is the Verification subsystem (11 mechanical checks) the right idea? Evaluate the project's approach to knowing whether it works.`,
  },
  {
    key: 'big-picture-proportionality',
    prompt: `CONCERN: proportionality and coherence of the whole -- is this the right architecture for a personal agent that one person runs on one laptop for one family, and is it the right architecture for the stated goal of self-improvement?
Do this differently from the other readers: first measure the shape of the codebase (lines per package; number of Service classes; number of topics vs. topics that have both a publisher and a subscriber -- write a small script that greps topics.X publish/subscribe usage and reports topics with only one side; number of message schemas; number of tools; number of provider adapters; number of bus/ledger backends; number of CLI commands; number of config keys defined vs. read). Then skim the top of each subsystem's service.py. Then read docs/blueprint/01-vision-and-principles.md and docs/blueprint/02-system-architecture.md to see what the design intended, and docs/blueprint/07-post-cutover-review.md for the project's own retrospective.
Questions: Where is accidental complexity concentrated? What would a senior architect delete, merge, or freeze to make the system more improvable? Which abstractions have exactly one implementation and are paying an abstraction tax (backends, providers, protocols)? What is the ratio of infrastructure code to code that produces user-visible value? Which architectural decisions are load-bearing and correct (do not touch), and which are the ones the creator 'got wrong' -- be direct and specific, with evidence. Also assess: the project's docs are extremely elaborate (blueprint, EVOLUTION 5k lines, SOUL, BIOMIMICRY) -- is the docs:code:tests ratio itself a symptom?`,
  },
]

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    verdict: { type: 'string', enum: ['confirmed', 'partly-true', 'refuted', 'already-known', 'unverifiable'] },
    reasoning: { type: 'string' },
    corrected_claim: { type: 'string', description: 'if partly true, the accurate version of the claim' },
    evidence: { type: 'array', items: { type: 'string' } },
    severity_adjustment: { type: 'string', enum: ['raise', 'keep', 'lower'] },
  },
  required: ['refuted', 'verdict', 'reasoning', 'evidence', 'severity_adjustment'],
}

phase('Read')
const reports = await pipeline(
  READERS,
  r => agent(CONTEXT + '\n\n' + r.prompt, { label: `read:${r.key}`, phase: 'Read', schema: FINDINGS_SCHEMA, effort: 'xhigh' }),
  async (report, r) => {
    if (!report) return null
    const findings = report.findings || []
    log(`${r.key}: ${findings.length} findings, ${(report.strengths||[]).length} strengths`)
    const judged = await parallel(findings.map(f => () =>
      parallel(['correctness', 'proportionality'].map(lens => () =>
        agent(
          CONTEXT + `\n\nYou are a SKEPTIC. A reader claimed the following finding about concern "${r.key}". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: ${lens === 'correctness' ? 'is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?' : 'even if true, is it actually an architectural problem at this system\'s scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?'}\n\nFINDING:\n${JSON.stringify(f, null, 2)}\n\nDefault to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.`,
          { label: `refute:${lens}:${f.title.slice(0, 40)}`, phase: 'Refute', schema: VERDICT_SCHEMA, effort: 'high' }
        )
      )).then(votes => ({ finding: f, votes: votes.filter(Boolean) }))
    ))
    return { ...report, key: r.key, judged: judged.filter(Boolean) }
  }
)

const reads = reports.filter(Boolean)
const survivors = [], killed = [], knowns = []
for (const rep of reads) {
  for (const j of rep.judged) {
    const [corr, prop] = j.votes
    const alreadyKnown = j.votes.some(v => v.verdict === 'already-known')
    const factuallyOk = corr && !corr.refuted && corr.verdict !== 'refuted'
    const entry = { concern: rep.key, finding: j.finding, votes: j.votes }
    if (alreadyKnown) knowns.push(entry)
    else if (factuallyOk) survivors.push(entry)
    else killed.push(entry)
  }
}
log(`${survivors.length} findings survive, ${killed.length} refuted, ${knowns.length} already known`)

phase('Critic')
const digest = survivors.map(s => `- [${s.concern}] ${s.finding.title}: ${s.finding.claim}`).join('\n')
const critic = await agent(
  CONTEXT + `\n\nNine readers reviewed the architecture and, after adversarial checking, these findings survived:\n${digest}\n\nYou are the COMPLETENESS CRITIC. What did they miss? Think about architectural concerns that cut across the readers' boundaries: data ownership and single-writer rules; the identity/session model across surfaces; upgrade/migration story for the ledger and schemas (174 JSON schemas -- who versions them?); secrets handling; the relationship between v1 (src/, 'retired but not deleted') and v2; the git repo itself as runtime state (worktrees, tags sim-good-NNNN, Sim committing to the same repo the creator edits); disk growth (workspace/, ledger, HLS segments); dependency on external binaries (ffmpeg, claude CLI, whisper, kokoro); Python packaging/typing/linting hygiene (is there a pyproject, mypy, ruff? grep); and anything in the top-level tree that looks like an accident (simorgh/big.py, .Rhistory, games/, images/, papers/, results/). Investigate 4-8 candidate misses against the code and return them as findings with evidence, same rigour as the readers. Return only structured output.`,
  { label: 'completeness-critic', phase: 'Critic', schema: FINDINGS_SCHEMA, effort: 'xhigh' }
)

return {
  reads: reads.map(r => ({ key: r.key, summary: r.summary_of_what_is_actually_there, strengths: r.strengths, measurements: r.measurements })),
  survivors,
  killed: killed.map(k => ({ concern: k.concern, title: k.finding.title, claim: k.finding.claim, why: k.votes.map(v => v.verdict + ': ' + v.reasoning.slice(0, 300)) })),
  knowns: knowns.map(k => ({ concern: k.concern, title: k.finding.title })),
  critic,
}
