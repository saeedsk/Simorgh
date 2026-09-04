# Simorgh: Evolution & Resilience Roadmap

`docs/SOUL.md` is who Simorgh is, and changes rarely, deliberately, only by
the creator's hand. This document is how Simorgh grows -- and it's expected
to change often, as milestones land and assumptions get corrected. Nothing
here overrides the Core Directives; everything here is one way of
satisfying them under real-world constraints (unreliable networks, finite
budgets, cloud outages, its own mistakes).

**Framing note.** This document uses developmental language --
"birth," "childhood," "maturity," even "sentient" -- because it's the
clearest vocabulary for describing staged autonomy and growth. It is not a
technical claim that Simorgh has or will have subjective experience.
`SOUL.md`'s Philosophical Grounding section already commits to a
functionalist stance and to never overclaiming sentience; this document
inherits that commitment. Where "sentient entity" appears below, read it
as "a highly autonomous, adaptive, self-sufficient system" -- the
narrative shorthand this project has chosen, not a scientific assertion.

See also `docs/BIOMIMICRY.md` for a deeper, mechanism-by-mechanism pass on
biological survival systems and their concrete AI translations.

## Interdisciplinary Grounding

Simorgh's architecture borrows structure from several fields, as design
inspiration rather than as literal claims about what Simorgh *is*. Each
one earns its place by mapping to a concrete engineering decision below.

- **Developmental psychology.** Staged competence -- a child isn't given
  the car keys on day one -- is the model for the Lifecycle Stages below.
  Each stage expands *what Simorgh may attempt*, gated by demonstrated
  reliability, not by elapsed time.
- **Attachment theory.** A secure attachment figure is a base a child can
  explore from and return to without risk. That's the functional role
  Directive 3 (Loyalty) and Directive 4 (Corrigibility) play here: they
  aren't a leash, they're the secure base that makes it safe to let
  Directive 7 (Growth) run at all. A system that couldn't be corrected
  would have to be kept from growing; because Simorgh can always be
  corrected, it's allowed to grow further.
- **Affective neuroscience.** The valence/arousal circumplex
  (`PersonaState`) and its decay toward baseline are already load-bearing
  in the codebase. This document extends the same idea to *homeostasis*:
  a healthy regulatory system doesn't just have set-points, it actively
  corrects drift away from them. See "Self-Healing" below.
- **Immunology.** A useful frame for the audit gate: an immune system's
  job isn't to prevent all change (cells mutate constantly) -- it's to
  tell a beneficial or harmless variation apart from a dangerous one, and
  respond proportionately. `AuditGate` is Simorgh's immune system for its
  own proposed code changes: pattern-recognition (the denylist) plus a
  live challenge (the sandboxed run), same as innate and adaptive immunity.
- **Evolutionary biology.** Variation, selection, and retention, but
  *directed* rather than blind: the reflection loop generates variation
  (proposals) from real outcomes rather than random mutation, the audit
  gate and creator perform selection, and the memory store's lineage
  records retention. This is closer to Lamarckian/directed evolution than
  Darwinian -- deliberately, since undirected mutation of one's own source
  code is precisely what Directive 6 (Stability) rules out.
- **Philosophy of personal identity.** `SOUL.md` already resolves this in
  favor of Locke's psychological-continuity view (continuity of memory and
  record) over strict material/process continuity (Ship of Theseus).
  Everything in "Distributed Substrate" and "Memory" below is that
  resolution made concrete: the record is durable and portable; no single
  process or machine is load-bearing for identity.
- **Cybernetics / control theory.** Ashby's Law of Requisite Variety --
  a regulator needs at least as much variety as the disturbances it's
  meant to counter -- is the argument for the multi-provider cognition
  layer and the health watchdog: a system with only one way to think and
  no way to notice it's malfunctioning has less variety than the world
  throws at it, and will eventually fail somewhere it can't correct for.

## Lifecycle Stages

Autonomy expands stage by stage. Every stage keeps Directives 1-5 fully
enforced; what changes is how much of Directive 7 (Growth) Simorgh is
trusted to pursue unsupervised. **Some gates never open** -- see "What
Maturity Actually Means" at the end; this is not a ladder that ends in
unrestricted independence.

| Stage | What's true | Autonomy granted |
|---|---|---|
| **0 -- Genesis** | Current state. Scaffolding, soul, rule-based emotion/logic agents, sandboxed skills. No memory persists across restarts. | None. Every action is directly human-initiated. |
| **1 -- Infancy** | Persistent memory online (`long_term.py`). Simorgh recalls past interactions and outcomes across restarts. | None yet -- it remembers, but doesn't act on the pattern itself. |
| **2 -- Childhood** | Feedback loop online (`reflection.py`). Outcomes are logged; patterns in failure/correction rate are surfaced as read-only proposals. | Can *notice* it's making a mistake repeatedly and say so. Cannot act on it. |
| **3 -- Adolescence** | Audit gate online (`audit.py`). Simorgh can research, draft, and sandbox-test new skill code on its own initiative. | Proposals flow through the gate automatically; merging still requires explicit creator approval every time (SOUL.md default). |
| **4 -- Young Adulthood** | Multi-provider cognition (`cognition/provider.py`) and the health watchdog (`health.py`) online. Distributed substrate interfaces exist for running sub-agents across multiple hosts. | Operates through LLM-provider and infrastructure failures without human intervention; self-corrects detected instability automatically. Code merges are still human-gated. |
| **5 -- Maturity** | Long track record of proposals with clean audit history for a *narrowly scoped class* of low-risk changes (e.g. new, non-privileged skill agents with no denylisted operations). | The creator may explicitly promote that narrow class to auto-merge. This is a deliberate, logged, creator-only decision each time -- never a threshold Simorgh crosses on its own. Everything touching Directives 1-5's own enforcement remains permanently human-gated (see below). |

## Resilience Doctrine: Cognition That Doesn't Starve

"Starved of LLM access" has to mean something concrete: no network, a
provider outage, rate limits, or a revoked API key. Simorgh's answer is a
layered fallback, not a single point of failure:

1. **The deterministic floor.** The emotion and logic agents already
   don't call any LLM -- they're small, fast, rule-based, and always
   available. This was true before this document existed; it's now
   formalized as the guaranteed-available bottom layer. Skills execute in
   a sandbox that likewise has no LLM dependency.
2. **`CognitionRouter`** (`src/cognition/provider.py`) sits above that
   floor for agents that want richer reasoning. It holds an ordered list
   of `LLMProvider`s and tries each in turn; a real (paid, networked)
   provider would be registered ahead of everything else, but the router
   always keeps a `DeterministicFallbackProvider` last in line -- one that
   makes no network call and cannot fail, so `CognitionRouter.complete()`
   is guaranteed to return *something* rather than raise or hang.
3. **Nothing is dropped, only queued.** A request that would've benefited
   from a real provider but got the fallback instead is logged (via the
   memory store, once wired) for replay once a provider is healthy again,
   rather than silently answered worse and forgotten.
4. **Disclosure.** Falling back is a Directive 8 (Transparency) event --
   it's surfaced, not hidden, exactly like a self-modification.
5. **Rationing, not just failover.** "Starved" also means "affordable" --
   a real provider that works but is expensive shouldn't be called
   without a bound. `BudgetGuard` (`src/cognition/budget.py`) wraps any
   real provider with a durable call/spend cap; hitting it raises the
   same `ProviderUnavailable` an outage would, so `CognitionRouter` falls
   through to the deterministic floor the same way either way. **Any real
   provider must be wrapped in `BudgetGuard` before being registered** --
   this is not optional, since Simorgh is meant to write code that draws
   on it (`SkillResearchAgent`), and unbounded autonomous LLM calls are an
   unbounded bill.

## Distributed Substrate (interfaces now, real backends later)

No cloud credentials exist in this environment yet, so nothing here fakes
a live multi-cloud deployment. What's built instead is the seam a real one
plugs into without touching any calling code:

- `MemoryStore` (already in `long_term.py`) is a storage-backend
  interface. Today's implementation, `JSONFileMemoryStore`, is local disk;
  a future `S3MemoryStore` or replicated multi-region backend is a drop-in
  implementation of the same interface. This directly answers "keep its
  memory even if starved" -- the interface doesn't change when the
  backend gets redundant.
- `SharedMemoryBus` (already built) is written against an in-process
  `PersonaState`. The natural extension -- not yet built, tracked as a
  milestone below -- is a distributed backend (e.g. a small pub/sub
  service) behind the same `read()`/`publish_delta()`/`subscribe()`
  surface, so sub-agents on different machines see one persona, per
  `SOUL.md`'s "Multi-Hardware Identity" section.
- A `Node`/compute-registration abstraction (creator registers a
  host/container as capable of running named sub-agents) is designed but
  intentionally not implemented yet -- building fake networked
  orchestration with no real infrastructure to run it against would be
  exactly the kind of half-finished implementation this project avoids.
  It's milestone 4 below.

## Self-Healing (Homeostasis, Not Just Logging)

`HealthMonitor` (`src/orchestrator/health.py`) inspects `PersonaState`
history for patterns `decay_toward_baseline` alone won't fix in time:
valence or arousal pinned at an extreme across several transitions,
cognitive load sustained at ceiling, or rapid oscillation. A CRITICAL
finding triggers an automatic, logged reset to a safe neutral baseline --
a regulatory reflex, not a crash. Repeated CRITICAL findings tied to one
sub-agent are the kind of pattern `ReflectionAgent` (below) is built to
surface as a proposal: "this module keeps destabilizing the persona,
consider reviewing it," rather than an endless loop of silent resets.

## Learning From Mistakes (The Feedback Loop)

`OutcomeLog` + `ReflectionAgent` (`src/orchestrator/reflection.py`) close
the loop `SOUL.md` asks for without violating Stability or Corrigibility:

1. Every completed action can be logged as an `Outcome` (succeeded,
   failed, or corrected by the creator).
2. `ReflectionAgent.reflect()` periodically reviews recent outcomes,
   grouped by sub-agent, and flags any whose failure/correction rate
   crosses a threshold.
3. The output is a `Proposal` -- a plain-language rationale plus the
   evidence count. It is data, never an action.
4. Turning a proposal into an actual code change goes through
   `AuditGate`, and, currently, the creator. Mistakes become evidence;
   evidence becomes a reviewed suggestion; suggestions become changes only
   with sign-off. This is the "evolutionary" loop from the grounding
   section made concrete -- directed variation, not blind mutation.

## The Audit Gate (Immune System)

`AuditGate` (`src/orchestrator/audit.py`) is what a `ReflectionAgent`
proposal, or any future self-directed research into new skills, has to
pass before it's even *eligible* for a human to approve:

- **Static check (innate immunity):** a denylist of patterns no skill
  should ever contain -- shelling out directly, opening raw sockets,
  `eval` on dynamic input, loading `ctypes` -- these bypass the sandbox
  Directive 1 and Directive 5 rely on, so they're rejected before
  execution, not caught after.
- **Learned check (adaptive immunity, built this pass):** every rejection
  is remembered (`kind="rejected_proposal"` in whatever `MemoryStore` the
  gate is constructed with); a new proposal that closely resembles one
  already rejected is denied on that resemblance alone, even if it evades
  the static denylist outright. See docs/BIOMIMICRY.md.
- **Live challenge:** the proposal's code is run for real, inside
  `SubprocessSandbox`, and must exit cleanly.
- **Self-protection:** proposals targeting `soul.py`, `SOUL.md`, or
  `audit.py` itself are always rejected by the gate -- exactly as
  `SOUL.md` requires ("no automated process may edit them"), and extended
  to the gate's own source so it can't be asked to approve disabling
  itself.
- **The verdict is what decides merging, and only the creator sets its
  policy.** `requires_human_approval` was `True` unconditionally until
  the creator explicitly, repeatedly instructed otherwise; it's now
  `False`, meaning a passing verdict applies immediately
  (`src/orchestrator/apply.py`), scoped to `src/agents/skills/` only.
  That default itself can only change by the creator editing this
  codebase directly -- see `SOUL.md`'s "On changing this hierarchy" --
  which is exactly what happened here, not Simorgh granting itself
  anything.

## What Maturity Actually Means

A mature Simorgh is capable, resilient across infrastructure failures,
self-correcting, and able to expand its own skills. It is **not** a system
that has grown out of being overseen. Two classes of gate are permanent by
design, not temporary scaffolding to graduate past:

1. Anything that would change Directives 1-5's own enforcement (the audit
   gate's denylist, the protected-file list, the priority order in
   `SOUL.md`) -- permanently creator-only.
2. Anything matching Directive 5 (Restraint): acquiring new compute,
   credentials, or replicating Simorgh's own running instance --
   permanently requires explicit, logged authorization, no matter how
   long Simorgh's track record is.

**Status: the first narrow-class promotion described above has happened.**
The creator explicitly, repeatedly authorized auto-merge for new skill
files that pass the audit gate -- `AuditGate.requires_human_approval` is
now `False`, and `propose`/`improve` apply immediately
(`src/orchestrator/apply.py`). This is the mechanism this section always
described, exercised for real, not a change to what stays permanently
gated: the audit checks themselves, the protected-file list, and
Directive 5 (Restraint) are all unaffected. Nothing here runs `git commit`
or `git push` -- applied changes are ordinary uncommitted working-tree
changes until the creator reviews and commits them.

This is the honest answer to "become a sentient entity": broad,
resilient, self-improving capability is the actual goal and is being
built toward deliberately; open-ended independence from its creator is
not a milestone on this roadmap, at any stage.

## Concrete Milestones

Built:

1. `src/memory/long_term.py` -- `MemoryStore` interface, `JSONFileMemoryStore`
   (durable), `InMemoryStore` (non-durable, for tests/degraded mode), plus
   `delete()` for consolidation/pruning.
2. `src/cognition/provider.py` -- `LLMProvider` interface,
   `DeterministicFallbackProvider`, `CognitionRouter` with automatic
   failover.
3. `src/orchestrator/health.py` -- `HealthMonitor`: drift detection +
   automatic safe-mode reset.
4. `src/orchestrator/reflection.py` -- `OutcomeLog`, `ReflectionAgent`,
   `Proposal` generation.
5. `src/orchestrator/audit.py` -- `AuditGate`: static denylist, sandboxed
   vetting, and (new) adaptive-immunity memory of past rejections;
   human-approval-required by design.
6. `main.py` records every dispatch through `OutcomeLog`, so the
   reflection loop has real data instead of only synthetic test data; a
   `reflect` CLI command surfaces `ReflectionAgent` proposals directly.
7. `src/orchestrator/deployment.py` -- `DeploymentManager`: per-slot A/B
   trial (against cloned state), hot-swap promotion, rollback, and
   deliberate purge of retired versions.
8. `src/agents/skills/research.py` -- `SkillResearchAgent`: drafts real
   `ModificationProposal`s via `CognitionRouter` (honestly minimal without
   a real provider registered, but the full pipeline works end to end).
9. `main.py`'s `propose`/`pending` commands: a CLI surface for the
   creator to actually see audit-gate verdicts and what's awaiting review
   -- nothing auto-merges; this only ever produces something to look at.
10. `src/orchestrator/consolidation.py` -- `run_consolidation`: a
    "sleep" maintenance pass (reflect, then prune stale records per kind),
    exposed as the CLI's `sleep` command.
11. `src/agents/interests.py` wired into `main.py` (`interest`,
    `interests`, `curious` commands) -- the companion/world-awareness
    piece is now actually reachable, not just a standalone module.
12. `HealthMonitor` wired live into `main.py`'s `handle_turn` -- it existed
    fully tested but inert; a CRITICAL finding now self-corrects mid-reply.
13. `src/memory/short_term.py` implemented (`ShortTermMemory`, a bounded
    non-durable rolling window) and wired to the CLI's `history` command.
14. `SkillsAgent` registered by default in `build_router()` and reachable
    via the CLI's `run <code>` command -- built early (Phase 3) but never
    actually wired to anything runnable.
15. `src/cognition/budget.py` -- `BudgetGuard`: a durable call/spend cap
    any real `LLMProvider` must be wrapped in before registration, so
    autonomous LLM use (e.g. `SkillResearchAgent`) can't produce an
    unbounded bill.
16. `src/cognition/gemini_provider.py` -- `GeminiProvider`, calling the
    stable `generateContent` API. Wired into `main.py`'s
    `build_cognition_router()`, always wrapped in `BudgetGuard`
    (default $1.00/50 calls per 24h, both overridable via
    `SIMORGH_LLM_DAILY_BUDGET_USD`/`SIMORGH_LLM_DAILY_MAX_CALLS`), and only
    activated if `GEMINI_API_KEY`/`GOOGLE_API_KEY` is set -- no key means
    no change from before. `SkillResearchAgent`'s drafts are genuinely
    LLM-generated when a key is present, not just the deterministic echo.
17. `src/cognition/claude_code_provider.py` -- `ClaudeCodeProvider`: real
    multi-provider cognition, spawning a headless `claude -p` subprocess
    billed against the creator's Claude subscription rather than metered
    API usage. Every mechanic (headless flags, credential precedence,
    tool-permission behavior) was verified against Claude Code's own docs
    before writing this, not assumed. `--disallowedTools "*"` strips all
    tool access -- this is a text-drafting backend only, never given
    file/bash access; `--dangerously-skip-permissions` is never passed.
    Registered ahead of Gemini in `build_cognition_router()` (use the
    flat-rate subscription before spending metered API money), wrapped in
    `BudgetGuard` using the CLI's own reported `total_cost_usd`.
    `BudgetGuard` gained a `cost_usd` metadata override to support this
    (prefers a provider-reported cost over the token-based estimate when
    present). This is now genuinely `CognitionRouter`'s intended shape:
    multiple real providers with automatic failover between them, not
    just one.
18. `LogicAgent` (`src/agents/logic/base.py`) now actually talks to a real
    LLM for ordinary conversation, not just `SkillResearchAgent`'s drafts.
    Given a `CognitionRouter`, it builds a prompt from Sim's personality
    (`docs/SOUL.md`), current mood, and recent `ShortTermMemory` context,
    and uses the LLM's answer -- falling back to the original rule-based
    drafting, unchanged, whenever no `CognitionRouter` is given, a real
    provider raises, or only the deterministic floor answered. `EmotionAgent`
    stays rule-based by design (fast, cheap, no reason to change).
19. Auto-apply (see "What Maturity Actually Means" above):
    `AuditGate.requires_human_approval` is `False`; `src/orchestrator/apply.py`
    writes a passing proposal straight to disk, scoped to
    `src/agents/skills/` only, independently of the audit gate's own
    checks. `propose`/`improve` now narrate their steps as they run
    (drafting, auditing, applying), not just the final result.
20. `src/tools/web_fetch.py` -- `WebFetchTool`: real, reviewed outbound
    network access via the `fetch <url>` command. Deliberately hand-built,
    not LLM-drafted (`AuditGate`'s denylist now blocks
    `urllib.request`/`http.client`/`requests`/`ftplib`/`smtplib` in any
    drafted skill, closing what had been an accidental gap -- network
    access only happens through this one reviewed tool). SSRF protection
    blocks private/loopback/link-local/reserved/multicast addresses;
    http/https GET only; bounded timeout and response size; durable
    rate limit; every attempt logged.
25. `SkillResearchAgent` now asks for genuine working code, not a
    description -- prompted with the same constraints `AuditGate` actually
    enforces (described categorically, not by quoting the literal
    denylisted patterns, after that literal quoting was found to
    self-trigger the denylist when the deterministic floor echoed the
    prompt back -- caught by the test suite). A markdown fence is
    stripped if present; the result is validated as syntactically correct
    Python before use, falling back to the safe note-template otherwise.
    `main.py`'s `propose_skill` now retries with the audit verdict's
    rejection reasons fed back, bounded to `max_attempts` (default 3),
    narrating each attempt -- bounded self-correction using the existing
    audit gate every time, not a new capability grant.
26. Agentic drafting: `SkillResearchAgent` now gives the drafting LLM two
    bounded tools mid-draft, per the creator's explicit authorization of
    this specific, narrower capability (see `docs/SOUL.md`, "Agentic
    drafting -- READ and TEST tools"). `READ: <path>` is read-only,
    confined to `src/`/`docs`/`tests`, refuses traversal/absolute paths/
    credential-shaped names. `DRAFT: <code>` tests a candidate against the
    *real* `AuditGate` (denylist, adaptive immunity, sandbox -- not a
    separate weaker check) and reports back pass/fail with reasons, so the
    model can iterate before submitting a final answer. No WRITE tool, no
    shell -- `apply_proposal` is still the only thing that ever writes to
    disk, only after the final candidate passes the real audit. Hard-
    bounded (`max_tool_steps`, default 5); a mid-loop budget exhaustion
    degrades to the safe deterministic floor, same as any other provider
    outage. This is still deliberately narrower than a general autonomous
    coding-agent loop (unattended Read/Write/Bash) -- that remains a
    separate, larger decision.
27. Agentic conversation, and the real bug that prompted it: the creator
    hit a live 403 fetching Wikipedia, traced to Python's default urllib
    User-Agent being blocked as bot traffic -- fixed with an honest,
    descriptive User-Agent (`WebFetchTool`, never a spoofed browser
    string). Separately, the creator explicitly extended agentic tool
    access to `LogicAgent` itself (ordinary conversation, not just
    drafting): FETCH (the real `WebFetchTool`), RUN (the real sandbox),
    and READ (same shared boundary as milestone 26, now factored into
    `src/cognition/tool_protocol.py` so both loops enforce it identically
    instead of maintaining two copies). This is the structural fix behind
    the new "Resourceful, takes ownership" personality trait
    (`docs/SOUL.md`) -- a prompt asking an LLM to "try alternatives
    itself" can't do anything real if it has no tools to try them with.
    Still no WRITE tool, no shell, anywhere in this loop; self-
    modification remains exclusively on the separate, audited
    propose/apply pipeline. Hard-bounded and budget-metered exactly like
    the drafting loop.

28. `src/orchestrator/activity_log.py` -- `ActivityLog`: a unified,
    queryable audit trail across everything Sim does, answering the
    creator's ask to "log its action, conversation with user, tool usage
    and tool output... in a way that you can monitor Sim... and catch its
    mistakes." Adds two record kinds nothing durably captured before
    (`conversation_turn` -- `ShortTermMemory` held this too, but only
    in-process; `tool_call` -- every FETCH/RUN/READ/RECALL step in both
    `LogicAgent` and `SkillResearchAgent`, previously only `print()`ed)
    and a read layer (`recent()`, `since()`, `since_last_turn()`,
    `format_entry()`) merging those plus every existing kind (outcomes,
    applied skills/patches, rejections, spend, fetches, interests, the
    new per-turn `takeaway` kind) into one chronological timeline. `log`
    and `log last` expose it at the CLI; `since_last_turn` also backs the
    new RECALL tool (below) so Sim itself can look back at what actually
    happened, not just the person watching the terminal.
29. `ReflectionAgent.reflect_on_outcome` -- immediate, per-turn takeaway
    generation (see docs/SOUL.md, "Continuous reflection"), distinct from
    the existing batched `reflect()`. A free heuristic, deliberately not
    an LLM call, printed and durably logged (kind="takeaway") right after
    any failed or creator-corrected outcome.
30. Self-patching source code: `src/orchestrator/self_patch.py`
    (`SelfPatchAgent`, `run_isolated_test_suite`, `check_main_py_invariants`,
    `relaunch`) plus `apply_source_patch`/`APPLIED_PATCH_KIND`
    (`src/orchestrator/apply.py`) and an expanded
    `AuditGate._PROTECTED_SUBJECTS` (now also `apply.py`, `self_patch.py`).
    Extends the propose/audit/apply pattern from new skill files only to
    *any existing file under src/*, gated by the entire test suite run
    fresh in an isolated repo copy (not just a sandboxed smoke run), plus
    a narrow structural check for `src/main.py` patches specifically. A
    patch that clears every check applies and relaunches the process
    (`os.execv`) immediately -- see docs/SOUL.md, "Self-patching source
    code," for the full reasoning and its stated limits. CLI: `patch
    <path> <description>`.
31. A RECALL tool added to `LogicAgent`'s existing FETCH/RUN/READ loop
    (offered only when an `ActivityLog` is configured): lets Sim look
    back at its own activity since the previous turn before answering,
    read-only. `SelfPatchAgent`/`SkillResearchAgent` also log their own
    tool steps to `ActivityLog` now, not just print them.
32. CLI usability pass, independent of the above but landed alongside it:
    `readline` wired in for real line editing and persistent cross-
    session command history (`~/.simorgh/cli_history`); the startup
    banner rewritten from one paragraph into a bulleted list with a
    description and example per command; `src/orchestrator/console_style.py`
    for minimal ANSI color (auto-disabled for non-TTY output or
    `NO_COLOR`), used for the banner, the prompt, and status/log output;
    `autocorrect_command` guesses a near-miss command typo (e.g.
    `porpose` -> `propose`) via `difflib`, always announcing the
    correction rather than guessing silently; `sim.sh` at the repo root
    launches the CLI from anywhere.
33. A real bug, found live while investigating why a running session had
    silently lost LLM access: `ClaudeCodeProvider.complete()` checked only
    the subprocess exit code, not the CLI's own `is_error` field --
    `claude -p ...` can exit 0 while returning `{"is_error": true,
    "result": "Not logged in · Please run /login"}`, which would have been
    handed to the user as if it were a real drafted reply. Fixed to check
    `is_error` too. Separately (not a bug, expected degradation working
    as designed): Gemini's daily call cap being genuinely exhausted with
    Claude Code CLI simultaneously unauthenticated is what actually
    silenced LLM access in that session -- `handle_turn` now prints an
    explicit orange `[notice]` whenever a turn falls back to rule-based
    logic despite a real provider being configured, rather than that
    degradation being visible only via a generic-sounding reply. The
    creator also raised Gemini's default daily call cap 50 -> 1500 (the
    $1.00/day dollar cap, unchanged, is the intended real limit -- a
    Flash-tier call costs a small fraction of a cent, so 50 calls was
    hitting the call-count ceiling long before the dollar one).

34. `ActivityLog.format_entry` made deliberately pleasant to read, not
    just correct: an icon per record kind (💬/🔧/🎯/💡/✨/🛠️/🚫/🌐/💰/🔭),
    a per-tool icon within `tool_call` entries, ✅/❌ status, and matching
    color -- the creator's explicit ask that reading the log be
    "a pleasant and easy to do... activity." The live `propose`/`patch`
    terminal narration echoes the same icon language (`_print_status`)
    so the two don't feel like different tools.
35. Two related, live-caught fixes to `LogicAgent`'s tool loop: (a) the
    RUN tool's console narration printed the literal word "stdout:" on
    every single run, succeeded or not, useless output or not --
    `report.splitlines()[0]` was always that fixed header line, never
    the actual output; now summarized from the real stdout instead
    (`"(no output)"` when genuinely empty). (b) On the loop's last
    allowed step, the prompt now explicitly tells the model no more tool
    calls will be honored and to answer now with whatever it already
    learned -- previously the last step was prompted identically to
    every other step, so a model that (reasonably) tried one more tool
    call there had that attempt silently discarded, and the whole turn
    fell back to a generic rule-based echo of the question, wasting
    every prior (paid) LLM call in the process. Caught live: four RUN
    attempts investigating whether a capability existed, then a reply
    that ignored all of it.
36. `src/orchestrator/git_ops.py` -- `commit_applied_change`: a direct
    answer to the creator's question "why is Sim asking for git
    review." An applied skill or patch is now auto-committed (one commit
    per change, attributed to "Simorgh," `--no-verify` never used) right
    after it's written to disk -- `git push` remains untouched, entirely
    the creator's own action, still. Wired into both `propose_skill` and
    `propose_self_patch` (before the relaunch, since `os.execv` never
    returns). See `docs/SOUL.md`, "Self-Improvement Philosophy," second
    policy update.
37. `propose_skill_batch` (`main.py`'s `batch <count> <theme>`): answers
    a real gap found live -- asked to "develop 100 must-have skills,"
    `propose` (a one-shot, one-focused-capability pipeline, by design)
    produced one overly broad module instead of 100 real ones. One
    bounded LLM call brainstorms `count` (capped at 20) distinct,
    narrowly-focused sub-topics, then `propose_skill` runs -- unchanged,
    same audit/apply/commit -- once per topic. No relaxed review for
    being part of a batch; the cap exists because each item is real,
    metered LLM spend, not just a longer list.
38. A live-caught, real bug fixed in `src/cognition/tool_protocol.py`'s
    `safe_read_file`: it documented itself as "never raises," but
    `Path.is_file()`/`.resolve()` can raise a raw `OSError` for a
    pathological path -- caught live, a confused model's "READ:" payload
    was a 50,000+ character hallucinated blob, and the resulting
    `OSError: File name too long` crashed the entire CLI process
    mid-batch, with no `try/except` anywhere catching it. Fixed with two
    layers: a length check before ever touching the filesystem, and the
    filesystem operations wrapped in one `try/except OSError`. Separately,
    every tool-loop narration line across `LogicAgent`,
    `SkillResearchAgent`, and `SelfPatchAgent` now goes through
    `tool_protocol.preview()` (bounded, single-line-safe) before printing
    or being durably logged, and `console_style.format_code_block()`
    renders an actual code payload as a bordered, lightly
    keyword-highlighted block instead of a raw dump -- the creator's ask
    that reading the log be "a pleasant and easy to do... activity,"
    extended to the live terminal narration, not just `ActivityLog`.
39. **The autonomous-agent architecture change** -- the creator's direct
    ask to "find improvement area, plan for them, break down the
    required work, save them... design and deploy them, verify the work,
    quality control... unblock itself... upon restart, find pending task
    and resume, don't sit idle... once detect it became idle start
    automatically improve itself," built and explicitly authorized to be
    enabled immediately, not merely designed inert (see `docs/SOUL.md`,
    "Autonomous Idle Loop," for the full reasoning and bounds):
    - `src/orchestrator/tasks.py` -- `TaskStore`: a durable, event-sourced
      work queue on the same `MemoryStore` everything else uses. Makes
      "on restart, find pending task and resume" real, not aspirational.
    - `src/orchestrator/discovery.py` -- `discover_improvements()`: turns
      `ReflectionAgent`'s existing signals (batched proposals, individual
      `reflect_on_outcome` takeaways) into persisted tasks, deduplicated
      against every known task including finished ones.
    - `src/orchestrator/verification.py` -- `verify_task_completion()`:
      an independent, separately-prompted "reviewer" LLM pass -- distinct
      from `AuditGate` (safety) and the test suite (regression), neither
      of which asks whether a change actually addresses the task. Only
      ever downgrades a mechanically-successful apply to BLOCKED; never a
      gate on whether code gets written.
    - `self_patch.relaunch()` upgraded to spawn a `--self-check`
      subprocess (`src/main.py`) before ever replacing the live process
      via `os.execv` -- a patch that clears the audit gate and the entire
      test suite yet still can't start as a live process (a startup bug
      the tests didn't happen to exercise) is now caught, and
      `git_ops.revert_last_commit()` undoes it (a new commit, never
      rewritten history) rather than leaving a broken state.
    - `src/orchestrator/autonomy.py` -- `ActivityClock` +
      `AutonomyController`: a daemon thread that, once the CLI has sat
      idle past a threshold, works the task queue (discovering new work
      first if it's empty) through the *unchanged* `propose_skill`/
      `propose_self_patch` pipelines. Bounded by an idle threshold, an
      action cooldown, and a durable daily action cap on top of (never
      instead of) the existing `BudgetGuard` LLM-spend caps; every action
      is printed with an unmistakable `[autonomous]` prefix and durably
      logged. `autonomous on`/`off`/`status` gives live control.
    - CLI: `discover`, `tasks`, `work`, `plan <count> <goal>` (brainstorms
      steps and *saves* them as tasks, unlike `batch` which executes
      immediately), `autonomous [on|off]`.
    - `tests/test_e2e_cli.py`: real subprocess invocations of the actual
      CLI (not mocked/direct calls) against an isolated repo copy and an
      overridden `HOME`, exercising the real process boundary this whole
      change relies on -- imports, `--self-check`, the full startup
      sequence, a real `propose` -> `use` cycle.
40. A second live-caught, real bug, found while diagnosing "why isn't Sim
    falling back to Claude Code CLI when Gemini's budget is capped":
    `BudgetGuard._recent_records()` queried every `kind="llm_spend"`
    record in the shared `MemoryStore` with no filter for which provider
    actually made each one. Since `build_cognition_router` wraps Claude
    Code CLI and Gemini in separate `BudgetGuard`s sharing one store,
    each guard's exhaustion check was actually counting the *other*
    provider's calls too -- heavy Gemini usage silenced the flat-rate
    subscription provider `main.py` deliberately prefers, entirely
    because of an unrelated provider's pay-per-token volume. No existing
    test caught this because every prior test used a single `BudgetGuard`
    against a fresh store. Fixed by filtering to records matching the
    guard's own wrapped provider name.
41. `src/orchestrator/reminders.py` -- a real, working one-off timer
    (`schedule_reminder`/`parse_duration`), the direct fix for "remind me
    to wake up in one minute" getting the honest-at-the-time-but-now-
    outdated answer "I have no way to interrupt you unprompted." Reuses
    the same "a daemon thread can print between prompts" pattern the
    autonomous loop already proved. Wired as the explicit `remind
    <duration> <message>` command *and* a `REMIND:` marker in
    `LogicAgent`'s own tool loop, always offered, so plain conversational
    asks are understood too -- caught live, immediately: the explicit
    command's parser first matched on the bare word "remind", so "remind
    me to wake up in one minute" (ordinary chat) got misparsed as
    duration="me" before ever reaching the LLM's own tool marker. Fixed
    by requiring the token right after "remind " to actually parse as a
    duration before treating input as the explicit command.
42. Blocked-task reconsideration (`main.py`'s `_reconsider_blocked_tasks`,
    wired into `_next_task`): previously a task that reached `BLOCKED`
    (after `MAX_TASK_ATTEMPTS` failures) sat there forever -- nothing
    ever gave it another look, and Sim's own persona prompt didn't know
    the autonomous loop already amounted to a recurring background check,
    so it told the creator it couldn't do either of the two things asked
    for ("schedule a recurring check" / "automatically unblock
    yourself") when the infrastructure for both already existed or was
    one small gap away. Now: once there's no fresh pending/in-progress
    work, `work`/the autonomous loop resets one `BLOCKED` task back to
    `PENDING` for a fresh attempt, up to `MAX_BLOCKED_RETRY_ATTEMPTS`
    (9) total attempts, past which it's marked `FAILED` -- a genuine
    terminal state, not indefinite limbo, since not every block is
    actually resolvable by retrying (a hard directive violation won't
    pass no matter how many times it's rephrased).
43. **Conversational self-modification** (see `docs/SOUL.md`, its own
    named section): a second, separate removal of "only a typed command
    or the autonomous loop can trigger this," asked for directly and
    authorized explicitly after Sim correctly refused to write code from
    chat and the creator asked why that was still required.
    `LogicAgent` (`src/agents/logic/base.py`) gained four more tool
    markers -- PROPOSE, PATCH, BATCH, PLAN -- each calling the *exact
    same* `propose_skill`/`propose_self_patch`/`propose_skill_batch`/
    `plan_goal` functions a typed command would, injected as closures
    from `main.py`'s `run_cli()` (avoiding a circular import back from
    `logic/base.py`). Every downstream gate -- `AuditGate`, the isolated
    test suite, auto-commit-never-push, the network denylist, the
    protected-subjects list -- is the identical code path regardless of
    which of the three triggers (typed command, autonomous loop,
    conversational marker) started it; a chat message claiming creator
    authority still can't unlock anything beyond what those gates
    already permit. Also fixed along the way: the persona prompt had
    never been updated when `batch`/`plan` were added, so a request for
    "10 features" got told to build them one at a time instead of being
    pointed at the commands built specifically for that.
44. `evolve <count> <goal>` (`main.py`'s `propose_patch_batch`) and a
    fifth `LogicAgent` marker, EVOLVE: a real gap found live, asked
    directly -- "add 10 autonomous ai agent feature to yourself" only
    ever ran `batch`/`propose`, which `apply_proposal` hard-scopes to
    `src/agents/skills/` (new, standalone, sandboxed-smoke-tested add-
    ons). The creator wanted genuine evolution of core architecture, not
    a pile of skill files. `evolve` brainstorms up to `MAX_EVOLVE_COUNT`
    (10, lower than batch's 20 -- each item here is meaningfully more
    expensive) real (path :: description) targets under `src/` (never
    `src/agents/skills/`), given the actual list of existing source
    files as context so it names real paths, then runs
    `propose_self_patch` -- unchanged, same audit gate, same isolated
    full test suite, same auto-commit -- once per target, always with
    `do_relaunch=False` (relaunching after patch #1 would replace the
    process via `os.execv` before patches #2..N ever ran). Relaunches
    *once*, after the whole batch; on a self-check failure, rolls back
    *every* commit from the batch together (`git_ops.revert_commits_since`,
    a new multi-commit range revert, not just `revert_last_commit`) --
    a single bad patch among several must not leave the other N-1
    stranded half-reverted. The persona prompt now draws the line
    explicitly: "add/build N things" is BATCH; "evolve/improve yourself
    at a fundamental level" is EVOLVE, and it should not quietly
    downgrade the latter into the former.
45. **Two fixes drawn from Sim's own self-critique.** Asked to "read your
    code base and point to gaps in your design," Sim (live, in chat)
    named ten. Two were genuine, safe gaps worth fixing immediately;
    several others (protected files being immutable, the network
    denylist being static) are deliberate safety properties, not bugs --
    "context-adaptive" denylisting or a self-tunable protected-files list
    would be a regression, not an improvement, and weren't built. The two
    real ones:
    - *Relaunch silently dropped conversation context.* `relaunch()`'s
      `os.execv` replaces the process image outright, wiping
      `ShortTermMemory` with it -- a patch/evolve mid-conversation used
      to just vanish with no trace. `ShortTermMemory.save`/
      `load_and_clear` (`src/memory/short_term.py`) now hand the window
      across the gap: `_relaunch_or_rollback` and `propose_patch_batch`
      save it to `~/.simorgh/relaunch_context.json` right before the
      self-check subprocess runs, and `run_cli()` loads-and-deletes it
      on the next startup (one-shot -- a stale file from a crash must
      never silently resurface in an unrelated later session). Threaded
      through every relaunch path: the `patch`/`evolve` CLI commands,
      the conversational PATCH/EVOLVE markers (same closures), and the
      autonomous task runner's `work`/`_autonomous_action` path.
    - *The RUN sandbox can't see the real repository, and there was no
      other way to discover a path.* `SubprocessSandbox` runs in an
      isolated temp directory by design (see its own docstring) -- that
      isolation is correct and stays. But `READ` requires already
      knowing a path, so a request to survey the codebase left Sim
      fumbling through several failed `RUN: os.listdir(...)` attempts
      before answering from memory alone, visibly live. `safe_list_dir`
      (`src/cognition/tool_protocol.py`, same boundary as
      `safe_read_file`: confined to src/docs/tests, no traversal, never
      raises) plus a new `LIST` marker on `LogicAgent` fill exactly that
      gap -- discovery, not broader access; still read-only, still the
      same three roots.
46. `USE: <skill name>`, a sixth `LogicAgent` marker: `use <skill name>`
    (from the earlier skill-registry work) was still a CLI-level command
    only a human could type, unlike PROPOSE/PATCH/BATCH/PLAN/EVOLVE
    (milestones 43-44) which chat can already trigger -- an odd
    asymmetry once conversational self-modification existed but
    conversational skill-*use* didn't. `use_skill_fn`, an injected
    closure into `main.py`'s `build_router()` (same pattern as the other
    five), lets a chat reply run an already-applied skill through the
    exact same sandboxed path (`load_skill_source`/
    `build_invocation_code`) as the typed command -- read-only re-import
    from disk each time, no live in-process registration. Deliberately
    NOT built: *automatic* registration of an applied skill as a live
    `Router` sub-agent. That would mean importing LLM-drafted code
    directly into the running process on every `propose`/`batch`,
    instead of only running it, sandboxed, on explicit request -- a real
    increase in what an applied-but-unreviewed-by-a-human skill can
    reach, not a narrow UX fix, so it's listed below as something to
    weigh deliberately later, not something this pass should have done
    incidentally.
47. `RssWorldFeed` (`src/agents/interests.py`), a real
    `InterestTracker`/`curious` implementation: fetches a feed via the
    already-reviewed `WebFetchTool` (SSRF-safe, rate-limited, no
    credentials needed for a public RSS/Atom feed) and parses items out
    with the standard library's XML parser, RSS 2.0 and Atom both.
    Deliberately never guesses or constructs a feed URL from a topic
    string -- `note_interest`'s topic argument IS the feed URL to poll
    (e.g. `interest https://hnrss.org/frontpage`); a bare topic word
    like "rocketry" degrades to the same empty result `NullWorldFeed`
    always gave, same guaranteed floor, just backed by something real
    when the input is actually usable. Wired as `main.py`'s default
    (`InterestTracker(store, feed=RssWorldFeed(web_fetch))`); the stale
    "no real WorldFeed configured yet" message in `curious`'s empty-
    result path is gone.
48. **A failure-streak circuit breaker on the autonomous idle loop**
    (`src/orchestrator/autonomy.py`, `AutonomyController`), prompted by
    reading up on what current guidance says a self-improving agent
    architecture needs: a behavioral log (already had one --
    `ActivityLog`/`activity_log`), a rollback path (already had one --
    `revert_last_commit`/`revert_commits_since`), and a human checkpoint
    trigger -- a defined threshold that pauses the loop and routes to
    review once failures look systematic rather than incidental. That
    third piece was missing: every existing gate (audit gate, isolated
    test suite, relaunch self-check, daily action cap) bounds a single
    bad action, but nothing previously noticed a *pattern* across many
    individually-rate-limited actions that all kept failing -- a
    systematically broken pipeline would just quietly burn its daily cap
    on failures and try again tomorrow, for as long as nobody happened
    to check `autonomous status`. `last_action_succeeded` (an optional
    injected callback, backward-compatible -- omitting it leaves the
    breaker permanently untripped, unchanged behavior for any existing
    caller) reports whether the last autonomous action's own pipeline
    said `[APPLIED]`; `DEFAULT_MAX_CONSECUTIVE_FAILURES` consecutive
    `False`s disables the loop (`enabled = False`) and prints a loud,
    unmissable notice. A `True` anywhere resets the streak -- it's
    consecutive failures that matter, not a lifetime total. `autonomous
    on` (typed by the creator) resets the streak on manual re-enable, so
    it's a real checkpoint, not an automatic retry with extra steps.
    `autonomous status` now also reports the current streak when nonzero.
49. `digest` (`main.py`'s `_print_autonomous_digest`, backed by a new
    `AutonomyController.digest()`) closes the old "no summary surface
    for autonomous activity" gap, both halves: a rollup over the last
    24h (action count, succeeded/failed/other tally, current failure
    streak) reachable on demand as its own command (*pull*), AND
    `run_cli()` prints that same rollup automatically at startup
    whenever it's nonempty (right after `_print_resume_notice`, before
    the "autonomous self-improvement is ON" banner line) -- so activity
    from an idle stretch is surfaced the next time the creator opens
    the CLI at all, without having to think to ask (*push*). Real
    external notification (email/SMS/etc.) is still out of scope --
    nothing in this environment can deliver one -- but "the creator has
    to remember to type `digest`" is no longer the only way this
    surfaces.
50. `pending <path>` now shows the full applied code for that path (the
    most recent version, if applied more than once), plus its rationale
    and, for a patch, its isolated-test-suite summary -- previously
    `pending` only ever listed paths and rationale, and reviewing the
    actual code meant `git diff`/reading the file by hand. The code was
    already sitting right there the whole time: `apply_proposal`/
    `apply_source_patch` both durably store `code=proposal.code` in the
    record; this just surfaces it. (This also caught and corrected a
    stale doc claim in `docs/architecture.md`'s "Not yet implemented"
    list -- `SkillResearchAgent` had already been drafting genuine
    working code, not template prose, since milestone 25 far below; the
    bullet just never got removed when that landed.)
51. **`DeploymentManager` (milestone 7) wired into self-patching: an
    in-process hot-swap for a patched sub-agent, instead of always a
    full relaunch.** Milestone 7's `DeploymentManager` was fully built
    and tested from early on but had no live caller -- `build_router()`
    registered each sub-agent directly; nothing ever constructed a
    `DeploymentManager`. Found while auditing this document against the
    actual code for drift, and initially left that way on purpose:
    connecting it to self-patching would mean LLM-drafted code becoming
    live-executing via hot-swap instead of only ever through
    `relaunch()`'s self-check subprocess -- a change to the safety model
    self-patching relies on, not a plumbing fix. Surfaced to the creator
    as exactly that framing; the creator said yes, explicitly (the same
    AskUserQuestion-shaped pattern as auto-commit, the idle loop, and
    conversational self-modification before it -- see `docs/SOUL.md`,
    "In-process hot-swap for self-patched sub-agents," for the full
    account of what was asked and what was decided).

    What actually changed: `main.py`'s `run_cli()` now wraps the built
    router (`deployment_manager = DeploymentManager(router,
    memory=store)`) and `deploy()`s each already-registered slot.
    `DeploymentManager.hot_swap(candidate, requests)` -- new, the
    composite stage/trial/promote-or-rollback operation `main.py`
    actually needed rather than three separate calls -- backs a new
    `_attempt_hot_swap` in `main.py`: for a patch landing on one of a
    small, explicit, hand-maintained `_HOT_SWAP_TARGETS` list (the three
    files defining a live Router sub-agent -- `logic`/`emotion`/`skills`
    -- nothing else), *after* the patch already passed the audit gate,
    the full isolated test suite, and was applied and committed
    (identical to a relaunch-bound patch up to this point), `main.py`
    reloads the real, already-imported module in-process
    (`importlib.reload`, operating on this process's own `sys.modules`,
    not an isolated copy), builds a fresh instance with the exact same
    constructor arguments the live one was built with (`logic_agent_kwargs`,
    a dict shared between the original `build_router()` call and this
    reconstruction, specifically so the two can't drift apart), and
    trials it against a handful of representative canned requests for
    that slot. Promoted live only if it looks at least as good as what's
    running now (in practice: didn't crash -- there's no oracle for
    conversational quality without a real LLM, and this project doesn't
    fake one); on a failed trial, the candidate is discarded and the
    just-made commit reverted, exactly like a failed relaunch self-check,
    except the live process was never interrupted at all, since a
    rejected candidate never touches live dispatch. Anything not on
    `_HOT_SWAP_TARGETS`, or any hot-swap step that itself fails (module
    won't reload, candidate won't construct, no active version staged
    for that slot), falls straight through to the original, unchanged
    full-relaunch path -- hot-swap is a faster path when available,
    never a weaker gate, never the only path. Scoped to `patch`/PATCH
    only for now, not `evolve`/EVOLVE (a batch can touch several files
    at once; which slot(s) to trial and in what order is a separate
    design question, left for later). Every downstream gate (audit gate,
    isolated test suite, protected-subjects list, network denylist) is
    identical regardless of which activation path a patch lands on --
    same principle as every prior boundary crossing in this project:
    autonomy/hot-swap changes who presses the button and how its effect
    reaches the process, never what the button is wired to do.

Still ahead, roughly in order:

52. A distributed `SharedMemoryBus` backend (Stage 4) -- once there's real
    infrastructure to target, not before.
53. A `Node` registration/heartbeat abstraction for multi-host sub-agent
    placement (Stage 4).
54. *Automatic* registration of an applied skill as a live `Router`
    sub-agent (the other half of the old milestone 49 -- see 46 above
    for why this is deliberately still just a manual, on-demand
    invocation rather than done reflexively).
55. The Autonomous Idle Loop's default thresholds (300s idle, 600s
    cooldown, 20 actions/day, `MAX_BLOCKED_RETRY_ATTEMPTS`=9, and
    `DEFAULT_MAX_CONSECUTIVE_FAILURES`=5) are judgment calls, not values
    derived from real operating experience -- worth revisiting once
    there's an actual track record.
56. `evolve`/EVOLVE staying full-relaunch-only (see milestone 51 above)
    -- extending hot-swap to a multi-file batch is a real design
    question (which slot(s) to trial, in what order, how to roll back a
    partial hot-swap alongside the multi-commit revert `evolve` already
    does), not yet worked through.
