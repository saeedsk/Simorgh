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
52. **Proactive socializing: a real news knowledge base, and Sim
    starting the conversation on its own.** The creator's direct ask --
    "sim should be able to goto internet get the news from different
    fields and domains, summarize and create knowledge base for itself
    to socialize and share the highlight and interesting topics with
    user, on its own, instead of being reactive."

    `InterestTracker.follow_up()` (`src/agents/interests.py`) used to
    fetch items and hand them straight back to the caller, forgetting
    them immediately after -- not a knowledge base, just a pass-through.
    It now persists every fetched item (`kind="news_item"`, deduped
    per-topic by title) durably in the same `MemoryStore` everything
    else uses, and tracks what's been shared via an additive marker
    record (`kind="news_item_shared"` -- `MemoryStore` has no in-place
    update, same reasoning as `TaskStore` folding status from a
    sequence of events, not mutating one). `DEFAULT_NEWS_TOPICS`: three
    well-known public feeds spanning distinct fields (Hacker News for
    tech, BBC World for world news, NASA for space/science), seeded
    exactly once -- only on a genuinely first run, when nothing is
    tracked at all -- so "different fields and domains" produces
    something real without the creator configuring anything, while
    never silently re-adding a default the creator later removed.
    Best-effort, not a guarantee: a stale/dead feed just yields no items
    (the existing, already-tested `RssWorldFeed` failure-is-empty-list
    behavior), never an error.

    New: `src/orchestrator/socializing.py`'s `NewsSocializer`.
    `share_next` picks the next unshared item (refreshing the
    most-overdue tracked interest first if none is known yet), drafts a
    short, warm, conversational blurb via `CognitionRouter` when a real
    provider answers -- an honest `title — summary` rendering otherwise,
    never a claimed "summary" that didn't happen, the same
    guaranteed-floor principle as every other cognition-backed drafting
    step in this codebase. `maybe_share` wraps that with its own pacing
    cooldown (`DEFAULT_SHARE_COOLDOWN_SECONDS`, one hour by default) --
    deliberately separate from, and usually much longer than,
    `AutonomyController`'s own action cooldown, so proactive sharing
    doesn't crowd out ordinary self-improvement work on every idle tick;
    the two compete for the same idle ticks, this only decides which one
    "wins" a given one.

    The actual "start the conversation" mechanism: `main.py`'s
    `_autonomous_action` now checks `maybe_share` FIRST on every
    autonomous tick (a no-op on most ticks, since the module's own
    cooldown gates it) and, when it fires, prints the highlight
    unprompted, between prompts -- reusing the exact "a daemon thread
    can safely print while the main loop blocks on `input()`" pattern
    `src/orchestrator/reminders.py` already proved works, rather than
    inventing a new mechanism. This is genuinely Sim initiating,
    occasionally, not just replying faster. A typed `news` command and
    a new, seventh `LogicAgent` marker, `NEWS:`, both call
    `share_next` directly (bypassing the pacing cooldown -- an explicit
    request, the same way typing `work` bypasses `AutonomyController`'s
    own idle-trigger check) for on-demand checking instead of waiting
    for the next idle share.

    A real bug caught live while manually verifying this against an
    actual feed (`https://hnrss.org/frontpage`, over real network):
    HN's RSS descriptions embed literal HTML (`<p>`, `<a href=...>`,
    entities), and `RssWorldFeed` had only ever extracted raw XML text
    content -- so a shared highlight printed raw markup straight to the
    terminal. `_strip_html` (`src/agents/interests.py`, stdlib
    `html.parser.HTMLParser`, bounded and honestly documented as "not a
    general sanitizer") now cleans both title and description at parse
    time, so every consumer -- the new proactive-share path and the
    pre-existing `curious` command alike -- gets readable text.
53. **A cold, corporate-sounding reply to ordinary small talk, fixed at
    the prompt level -- and the start of matching Claude Code's terminal
    UI conventions.** Live bug report: "what's up?" got back "Okay. Not
    much—just here, keeping things running and ready to dig into
    whatever you're working on today." Root-caused to prompt dilution:
    `_PERSONA_PREFIX`'s actual tone instructions are two sentences at
    the top, followed by 80+ lines of tool/pipeline/safety reference
    material that grew turn by turn this session -- by the time the
    model reaches the user's message, warmth is buried under audit-gate
    and self-modification procedure, and the literal "Current mood:
    neutral valence, low arousal." line likely compounded it (clinical
    phrasing right before answering tends to produce clinical replies).
    Fixed in three layers, not a rewrite: a concrete anti-pattern ban on
    corporate filler added to the tone instruction; `_mood_phrase()`
    replacing raw enum-speak with natural first-person phrasing ("calm,
    nothing much going on" instead of "neutral valence, low arousal");
    and `_TONE_REMINDER`, a short anchor placed right before the final
    "User: .../Sim:" cue -- instructions closer to the actual generation
    point carry more weight than ones diluted by everything in between.

    Separately, the creator asked how Claude Code's terminal UI handles
    ongoing status and asked to start building something similar for
    Sim. `src/orchestrator/console_style.py`'s new `LiveTicker` is the
    first piece: a periodic "still working... (Ns elapsed)" status line
    (a daemon thread, default every 5s) for a long blocking call that
    was previously completely silent -- `self_patch.run_isolated_test_suite`'s
    two subprocess runs (copy the repo, run the entire suite, twice) are
    the motivating case, reached by every `patch`/`evolve` invocation.
    Deliberately not a true in-place spinner -- a carriage-return redraw
    is fragile across terminals -- a new line per tick instead, reusing
    the same "a daemon thread can safely print while the caller stays
    blocked" property reminders/the autonomous loop already established
    rather than inventing a new mechanism.
54. **Two more pieces of the same Claude Code UI parity work, landed
    hands-free right after (the creator: "continue build ui improvement
    autonomously, I'd like to be hands-free").** `render_checklist`
    (`src/orchestrator/console_style.py`): a compact, icon-prefixed
    checklist (○ pending / ◐ in-progress / ✅ done / ❌ failed),
    reprinted as a whole block after each item changes -- `batch`
    (`propose_skill_batch`) and `evolve` (`propose_patch_batch`) now
    show one, kept visible and updated through the whole run, instead
    of only a scrolling trail of individual step narration with no
    summary in between. `format_diff_block`, `format_code_block`'s
    sibling for a `difflib.unified_diff` (+/- colored, bounded/
    truncated the same way): `pending <path>` now diffs against the
    previous applied version by default -- "minimize a big file down to
    what's relevant," the creator's own framing of what Claude Code's
    UI does well -- falling back to the full file when there's no prior
    version to diff against, or when `--full` is explicitly asked for.
    Same non-negotiable as `LiveTicker`: no cursor-redrawn in-place
    UI -- everything still prints new lines, safe across any terminal,
    piped output, or non-TTY logging.
55. **Two real, live-caught self-patch bugs, found while the creator
    asked Sim to patch `docs/EVOLUTION.md` with new roadmap milestones
    (persistent causal world model, continuous learning, intrinsic
    curiosity, counterfactual simulation).** The attempt failed with a
    misleading "no real drafting intelligence available," which reads
    like an infrastructure problem; it wasn't. Two real, distinct bugs:

    First: self-patch has always been scoped to `src/` only
    (`apply.py`'s `SELF_PATCH_SCOPE_PREFIX`, deliberate -- a self-patch
    changes Simorgh's own logic, not its docs) -- but nothing checked
    that *before* drafting. A `docs/`-scoped `patch` request burned a
    real drafting attempt against a check that was always going to fail
    it at the apply step regardless. `main.py`'s `propose_self_patch`
    now rejects an out-of-scope subject instantly, honestly, and for
    free, before ever calling the drafting LLM.

    Second, and more serious: `SelfPatchAgent.draft_patch` seeded its
    "write the complete new content of this file" prompt with
    `safe_read_file` -- the same function backing the bounded,
    chat-facing READ tool, truncated at 20,000 characters. `docs/EVOLUTION.md`
    is ~63KB, so the model was silently shown barely a third of it while
    still being asked to reproduce the whole thing -- it visibly
    confused itself trying to ask for "more" (hallucinating an
    offset-based read protocol this system has never had) before the
    attempt failed outright. Checking further: `src/main.py` (~106KB)
    and `src/agents/logic/base.py` (~36KB) -- two of the most important
    files in the entire self-modification system -- were *also* over
    that cap, meaning this was a latent correctness bug for real `src/`
    self-patch targets, not just an edge case surfaced by a docs/
    request. `tool_protocol.read_file_for_patch` (sharing
    `safe_read_file`'s path-safety validation via a new
    `_resolve_safe_path`, factored out so the two can't drift apart)
    returns a file's complete, untruncated content up to a much higher,
    but still real, ceiling (`_MAX_PATCH_SEED_CHARS`, 300K) -- and an
    honest refusal, not a silent truncation, for anything larger still.
56. **A full retrospective, and the fixes it pointed to.** The creator's
    direct feedback, verbatim: "sim still give me feeling of dumb
    entity, not acting on its own, sitting idle all the time, the
    command lines are rigid, interaction with it doesn't give a
    comfortable pleasant feeling. and most of all, I don't see any
    evidence of self improving." A published retrospective root-caused
    five findings (persona prompt bloat, purely-reactive discovery,
    idle-loop pacing tuned for an unattended daemon rather than a
    conversation, commands-as-primary-interface, unconfirmed model
    tier) and ranked fixes by likely felt impact. Three landed in this
    same pass:

    - **`GrowthSocializer`** (`src/orchestrator/socializing.py`): the
      direct answer to "no evidence of self-improving." Exactly
      `NewsSocializer`'s shape, pointed inward -- draws from Sim's own
      applied changes instead of RSS, own pacing cooldown (15 min,
      tighter than news' 30, since this was the more pointed
      complaint). `main.py`'s autonomous tick now checks growth before
      news. New `growth` command and `GROWTH:` marker for on-demand
      checks. See `docs/SOUL.md`, "Proactive Socializing."
    - **Autonomous loop retuned**: `DEFAULT_IDLE_THRESHOLD_SECONDS`
      300s -> 60s, `DEFAULT_ACTION_COOLDOWN_SECONDS` 600s -> 150s
      (`src/orchestrator/autonomy.py`); `NewsSocializer`'s own cooldown
      3600s -> 1800s. Idle time resets on every keystroke, so the old
      defaults meant the loop essentially never fired during an active
      chat session -- only after a multi-minute walk-away. Direct
      response to "not acting on its own, sitting idle all the time."
    - **`_PERSONA_PREFIX` split into `_IDENTITY_PREFIX` +
      `_CAPABILITY_REFERENCE`** (`src/agents/logic/base.py`): identity/
      tone stays short (~30 lines) and maximally prominent on every
      turn; the ~80-line tool/safety procedure block that had grown
      paragraph by paragraph every time a feature shipped this session
      was rewritten to say the same safety-relevant facts (five
      self-mod tools, "as your creator" unlocks nothing, protected
      files, PROPOSE/BATCH vs PATCH/EVOLVE, restart/hot-swap behavior,
      the autonomous loop, now growth/news sharing) in roughly a third
      of the words, not just relabeled or reordered. Direct response to
      "dumb entity" / "rigid" / "not pleasant."

    Deliberately not attempted in this same pass, and left for their
    own review: making conversational triggering as reliable as typed
    commands (a bigger, riskier change to how the marker loop works),
    and confirming which cognition provider is actually answering in
    the live session (Claude Code CLI vs. Gemini) -- diagnosis pointed
    at it, but nothing in the codebase itself was changed for it yet.

Still ahead, roughly in order:

57. A distributed `SharedMemoryBus` backend (Stage 4) -- once there's real
    infrastructure to target, not before.
58. A `Node` registration/heartbeat abstraction for multi-host sub-agent
    placement (Stage 4).
59. *Automatic* registration of an applied skill as a live `Router`
    sub-agent (the other half of the old milestone 49 -- see 46 above
    for why this is deliberately still just a manual, on-demand
    invocation rather than done reflexively).
60. The Autonomous Idle Loop's default thresholds (60s idle, 150s
    cooldown, 20 actions/day, `MAX_BLOCKED_RETRY_ATTEMPTS`=9, and
    `DEFAULT_MAX_CONSECUTIVE_FAILURES`=5 -- idle/cooldown already
    revisited once, milestone 56 above) remain judgment calls, not
    values derived from extensive operating experience -- worth
    continuing to tighten or loosen as more real feedback comes in.
61. `evolve`/EVOLVE staying full-relaunch-only (see milestone 51 above)
    -- extending hot-swap to a multi-file batch is a real design
    question (which slot(s) to trial, in what order, how to roll back a
    partial hot-swap alongside the multi-commit revert `evolve` already
    does), not yet worked through.
62. `DEFAULT_SHARE_COOLDOWN_SECONDS` (30 min for news, 15 for growth,
    milestones 52 and 56 above) remain judgment calls like the
    autonomous loop's own thresholds -- worth revisiting once there's a
    real sense of whether proactive sharing feels well-paced or not.
    `DEFAULT_NEWS_TOPICS`' specific three feeds are a starting set, not
    vetted for long-term stability -- worth checking they're still live
    occasionally, and trivially replaceable via `interest <feed url>`
    if not.
63. The one remaining piece of "match Claude Code's terminal UI
    conventions" (milestones 53-54 above landed `LiveTicker`,
    `render_checklist`, and diff-by-default `pending`): collapsed-by-
    default multi-step tool output with drill-down. Most existing tool
    turns are already reasonably bounded (`format_code_block`'s 30-line
    cap, `preview()`'s single-line truncation), so this is less about a
    broken behavior and more about there being no single shared
    convention for "one summary line, detail on request" the way the
    checklist/diff work now has one each.
64. `_MAX_PATCH_SEED_CHARS` (300K, milestone 55 above) is a generous but
    still arbitrary ceiling -- worth revisiting if a real `src/` file
    ever legitimately grows past it (unlikely soon: the largest today,
    `src/main.py`, is ~106KB).
65. Two findings from the retrospective (milestone 56 above),
    deliberately left for their own review rather than folded in here:
    making conversational triggering (the marker loop) as reliable as
    typing a command directly is a bigger, riskier change to how that
    loop works; and confirming which cognition provider actually
    answered in the live session that prompted this whole retrospective
    (this session's own `memory.jsonl` showed only Gemini spend, zero
    for Claude Code CLI, despite `build_cognition_router`'s documented
    priority order) needs a diagnosis pass, not a code change made
    without first knowing what's actually wrong.
66. **The second finding from milestone 65, diagnosed and fixed:** the
    creator's own live `budget` output (0/30 calls for `claude_code_cli`
    against a confirmed, valid `claude auth status` Pro login) proved
    this wasn't sandbox noise but a real, 100%-reproducible bug. Root
    cause: `src/cognition/claude_code_provider.py`'s `complete()` was
    passing `--bare` to the headless `claude -p` call. `--bare`'s own
    `--help` text documents it as skipping, among other things,
    "keychain reads" -- and on macOS, a normal `claude login` session
    lives in the OS keychain, not a plain credentials file. Every call
    silently failed with `is_error: true, "Not logged in"`, and
    `CognitionRouter` degraded to the next provider (Gemini) every
    single time, with nothing surfacing it as an error anywhere.
    Verified by direct A/B subprocess testing: `--bare` alone reproduces
    the failure; the same call without it, keeping `--disallowedTools
    "*"` and the fresh temp `cwd`, succeeds and bills the subscription.
    Fixed by simply not passing the flag -- everything else it would
    have bought (no CLAUDE.md/hooks/plugin sync) was already covered by
    this provider's own isolation (a fresh empty temp `cwd`,
    `--disallowedTools "*"`). Regression test added
    (`test_never_passes_bare_flag`); the module docstring's "every claim
    verified against Claude Code's own documentation" list now covers
    this finding too.
67. A gap in the same spirit as `activity_log.py`'s own stated design
    principle ("previously only print()ed for the person watching the
    terminal live -- if nobody was watching, that trail was gone") --
    but that principle had only ever been applied to `LogicAgent`'s and
    `SkillResearchAgent`'s FETCH/RUN/READ tool loops, not to
    `propose_skill`'s or `propose_self_patch`'s own multi-attempt
    draft/audit loop. A rejected attempt's specific reason (e.g. "attempt
    1 failed: uses eval on dynamic input") was printed live and then
    gone forever the moment it scrolled past, even though the final
    outcome (applied or rejected) was always durably recorded. Fixed by
    recording every attempt through the same `activity_log.record_tool_call`
    path (tool="DRAFT"), so `activity`/`activity last` now shows every
    attempt, not just the last one -- both `propose_skill` and
    `propose_self_patch` needed an `activity_log` parameter added (and
    `propose_skill_batch` needed to thread it through), so every call
    site across `main.py` (CLI dispatch, `LogicAgent`'s tool-marker
    wiring, `run_task`, `propose_skill_batch`) was updated together.
68. `JSONFileMemoryStore` (src/memory/long_term.py) loads its entire
    history into an in-memory dict on startup and answers every query
    from that dict, not the file -- genuinely fine at today's real
    scale (single user, single machine, thousands of records: sub-
    millisecond query, real fsync-per-write crash safety, no DB engine
    to run), but a real design debt worth tracking, not treating as
    settled: unbounded memory growth over a long enough history, no real
    index (a `kind`-filtered query still walks everything in memory),
    single-process-only despite the in-process `RLock`, and the
    underlying `.jsonl` file itself is never compacted (`consolidation.py`
    prunes *records*, not file bytes already written). The honest
    trigger to actually act on this is either the in-memory load
    becoming slow, or Stage 4's distributed `SharedMemoryBus` (item 57)
    needing multiple hosts to share this store -- at that point SQLite is
    the natural next step (same event-sourced/append-only shape, a real
    engine with indexes instead of a hand-rolled dict), not before.
69. **`!<command>` shell passthrough**, the creator's direct ask ("let
    runing bash command when prompt start with '!', similar to Claude
    Code"). A line typed straight into the CLI starting with `!` now
    runs the rest of the line as a real shell command
    (`_run_shell_passthrough`, `src/main.py`) with stdout/stderr/stdin
    inherited directly (not captured), so output streams live and an
    interactive command still works -- the same experience as alt-
    tabbing to a real terminal. This is deliberately a completely
    different trust boundary from every other tool-invoking path in this
    codebase: it is the human operator's own direct keystrokes, so it
    bypasses AuditGate and the sandbox entirely, on purpose, and is
    unreachable from anywhere except this literal REPL prefix --
    `LogicAgent`'s own `RUN:` marker remains the sandboxed, audited path
    for anything model-drafted, completely untouched by this change. The
    banner/help text (`_COMMANDS_HELP`) documents it, with one exception
    to the usual "a leading '/' is optional on any command" convention:
    `!` is its own trigger character, not a command word, so `_print_banner`
    is the one place that does NOT slash-prefix an entry.
70. **Proactive sharing during active conversation, not just idle gaps
    -- and a genuinely creative, self-directed discovery pass.** Two
    more direct pieces of live feedback, back to back: "just waiting
    for me to tell it what to do... I feel I'm in a terminal or shell,
    instead of interacting with a sentient, intelligent being," then,
    more urgently, "actively... starts learning and improving itself in
    rapid pace... find gaps, find improvement area, be creative, think
    big and come up with big idea... put together something that
    actually evolves."
    - The idle-triggered autonomous loop's growth/news sharing
      (milestone 52/56) only ever gets a chance to fire *between*
      conversations, since its idle clock resets on every typed
      command -- during an actively chatting session it could go the
      whole time without firing once, which is exactly what "just
      waiting for me" meant in practice, not a metaphor. Fixed with
      `_maybe_volunteer_during_conversation` (`src/main.py`): checked
      once after every ordinary conversational reply (never after a
      recognized command), reusing `GrowthSocializer`/`NewsSocializer`'s
      *same* `maybe_share`/pacing cooldowns the idle loop already uses
      -- a second trigger point for the same rate-limited behavior, not
      a second, spammier budget layered on top.
    - `discover_improvements` (`src/orchestrator/discovery.py`) was
      always purely reactive -- it only ever turns an existing failure
      signal (a reflection pattern, a takeaway) into a task, so it has
      nothing to say when nothing has actually gone wrong yet. This was
      retrospective item #4, deliberately deferred pending more design
      work; the creator's second message above is that authorization,
      explicitly. `discover_creative_improvements` (`src/main.py`) is
      the creative half: when the reactive pass finds nothing and the
      task backlog is empty, one bounded LLM call asks Sim to set its
      OWN agenda -- no goal supplied, unlike `evolve`'s human-given one
      -- and think ambitiously about its own architecture, reusing
      `evolve`'s exact brainstorm output shape (`_parse_evolve_targets`'s
      `path :: description` lines) so the resulting tasks flow through
      the *identical* audited `propose_self_patch` pipeline as anything
      else on the backlog -- no new, weaker path was added for this,
      only a new way for a task to originate. Deterministic-fallback-
      safe like every other drafting call in this codebase: a tick with
      no real LLM configured silently finds nothing, same as the
      reactive pass finding nothing. `_autonomous_action`'s existing
      bullet-formatted discovery printout (`   + [id] (via) description`)
      is unchanged and now covers both origins, distinguished by
      `discovered_via` ("scan"/"reflection" vs. "creative_agenda").
71. **A real cost/rate bug in milestone 70's `discover_creative_improvements`,
    caught in a self-review pass immediately after shipping it, before
    the creator hit it live.** `AutonomyController.tick()` only starts
    `action_cooldown_seconds` (default 150s) when `_autonomous_action`
    reports `True` ("did something"); a creative-agenda call that made a
    real, possibly-billed LLM request but parsed zero tasks out of the
    response still returned `False` (nothing was *created*), which would
    have let the very next poll (`poll_interval_seconds`, default 20s)
    immediately retry -- hammering a real provider roughly every 20s
    instead of the intended ~150s cadence, for as long as an idle,
    empty-backlog, nothing-to-react-to session kept getting unparseable
    brainstorm output back. Fixed by having `_autonomous_action` count a
    genuine attempt (any response that wasn't `deterministic_fallback`)
    as "did something" regardless of whether it produced tasks --
    `discover_creative_improvements` gained an optional `provider_sink`
    dict param (same pattern as `_dispatch_and_record`'s `metadata_sink`)
    so the caller can tell a real attempt apart from the free,
    unlimited-retry-safe fallback case without changing the function's
    `list[Task]` return shape. Regression test added
    (`test_a_creative_attempt_that_finds_nothing_still_counts_as_action`).
72. **"Hyperscale" retune, the creator's direct ask right after milestone
    70/71 shipped: "make the self improvement go at hyperscale, starting
    after 20 seconds start time, showing constantly progress with
    details."** `AutonomyController`'s thresholds (`src/orchestrator/
    autonomy.py`), already retuned once (milestone 56), retuned again,
    aggressively: `idle_threshold_seconds` 60s -> 20s (the literal
    number given); `action_cooldown_seconds` 150s -> 30s (5x tighter);
    `poll_interval_seconds` 20s -> 5s, so the daemon actually notices a
    20s/30s boundary promptly instead of polling coarser than the
    thresholds it's checking; `max_actions_per_day` 20 -> 500, since at
    the new cooldown the old cap was only ~10 idle minutes from
    exhausted, and going silent for the rest of the day directly
    contradicts "constantly show progress" -- the real spend ceiling
    stays `BudgetGuard`'s own per-provider caps, completely untouched by
    either retune; this cap was always a redundant extra layer on top,
    not the thing actually protecting real money.
    `GrowthSocializer`/`NewsSocializer`'s pacing cooldowns
    (`src/orchestrator/socializing.py`) were brought down proportionally
    alongside it, keeping the same 6x/12x ratio to `action_cooldown_seconds`
    they already had: growth 900s -> 180s, news 1800s -> 360s. No gate
    itself changed -- the audit gate, the isolated test suite, the
    relaunch self-check, the failure-streak circuit breaker, and every
    `BudgetGuard` cap are all completely unchanged; only how often those
    gates get a chance to run did. The "showing constantly progress with
    details" half of the ask was checked against what already exists
    rather than assumed to need new code: `LiveTicker` already wraps
    both isolated-test-suite runs (`self_patch.py`'s baseline and
    patched runs) with a periodic "still working... (Ns elapsed)" line,
    and every pipeline phase (drafting, audit gate, test suite, applied)
    already prints its own step live -- confirmed still true, nothing
    new needed there, only the cadence at which all of it fires.
73. **Sim didn't know its own applied skills existed.** Direct creator
    question: "when sim develop a new improvemnt or skill, dos it add
    necessary instruction to itself so later it kbow that skill is there
    and how to use it?" Checked the actual code rather than assumed: no.
    `apply_proposal` writes an applied skill to disk and records it in
    memory, and `USE: <name>` (`LogicAgent`, `src/agents/logic/base.py`)
    can already run one by name -- but `_build_prompt` never told Sim's
    own conversational awareness which skills exist. It could only ever
    find out by using `LIST:`/`READ:` to go look at `src/agents/skills/`
    itself, with nothing prompting it to think to. Confirmed live: this
    repo already has ~20 real applied skills (`100_major_skill_to_...py`
    and others, from earlier sessions) Sim's own conversation had no
    live awareness of. Fixed: `_build_prompt` now injects a fresh
    `list_applied_skills(self._repo_root)` result every single turn
    (never cached -- a skill applied moments ago, including by the
    hyperscale autonomous loop mid-session, must show up on the very
    next turn), bounded at `_MAX_SKILLS_IN_PROMPT` (40, with a "+N more"
    note past that) so a long-running session's accumulated skill count
    doesn't grow every turn's prompt unbounded forever. Milestone 59
    ("automatic registration... as a live Router sub-agent") remains
    deliberately NOT done -- this only makes Sim *aware* a skill exists
    and can still be run via the existing, already-audited `USE:` path;
    it does not change execution, wiring, or the safety boundary at all.
74. **A real bug caught live while monitoring the creator's own running
    session right after the hyperscale retune, per their direct ask
    ("monitor sims activity... tell me if you see any issue").** Two
    creative-agenda tasks -- genuinely ambitious ones, exactly what
    milestone 70 was for ("add a rollback-and-score loop...", "track
    per-provider cost/latency and adapt budget allocation...") -- kept
    failing with "[patch] no real drafting intelligence available --
    nothing applied" on their very first attempt, even though neither
    LLM budget was anywhere near exhausted (19/30 Claude Code calls,
    28/1500 + $0.38/$2.00 Gemini, checked directly against the live
    `memory.jsonl`). Root cause: `SelfPatchAgent.draft_patch` collapsed
    three genuinely different failure classes into one `None` return --
    "no real provider at all" (not retryable), a "refused: ..." target
    problem (not retryable), and "a real provider answered but its
    response wasn't valid, extractable Python" (retryable -- the exact
    kind of thing this codebase already does bounded self-correction
    for on an audit-gate rejection). `propose_self_patch` treated all
    three identically: stop on attempt 1, even though `max_attempts`
    (default 3) existed specifically for this. An ambitious, real
    self-directed idea asking for a complete-file rewrite is genuinely
    harder to get right in one shot than a narrow bug fix -- exactly the
    case that needed the retry, and exactly the case milestone 70's own
    prompt now produces more of.

    Fixed: `draft_patch` now returns `(proposal, reason)` instead of
    just `proposal | None`, with `reason` one of the literal string
    `"deterministic_fallback"`, a `"refused: ..."`-prefixed target
    problem (both still immediate, non-retryable stops), or a
    human-readable description of why the response wasn't valid Python
    (now fed back into the SAME `prior_reasons` retry mechanism an
    audit rejection already uses, up to `max_attempts`). The one
    production call site (`main.py`) and every test call site
    (`tests/test_self_patch.py`, `tests/test_main.py`'s
    `FakeSelfPatchAgent`) were updated together; two new regression
    tests lock in the retry (`test_invalid_python_draft_is_retried_with_feedback_not_abandoned`)
    and the still-immediate-stop case
    (`test_a_refused_target_stops_immediately_without_retrying`).
    746 unit tests + 19 E2E tests passing. No commits had landed from
    the creative-agenda tasks yet when this was caught -- this fix
    shipped before anything needed reverting.
75. **A third autonomy retune -- "10X speed up," with an explicit,
    reasonable cost worry attached: "would it run out my claude usage?
    ...like to be cautious there to now exhasust my claud ecode
    subscription."** `action_cooldown_seconds` 30s -> 3s, the literal
    10x (this is the knob that actually paces repeated self-improvement
    actions once idle). `idle_threshold_seconds` only 20s -> 10s (2x),
    deliberately not the full 10x -- dropping it to ~2s would mean an
    ordinary pause mid-conversation reads as "idle" and starts
    competing for attention constantly, undoing every earlier fix aimed
    at feeling like a present conversational partner rather than a
    nervous interruption engine. `poll_interval_seconds` 5s -> 1s.
    `max_actions_per_day` 500 -> 2000 (stays comfortably above Gemini's
    own 1500-call/24h cap so it's never the binding constraint).
    Growth/news sharing cooldowns (`socializing.py`) deliberately left
    UNCHANGED this round -- they weren't part of the ask, and scaling
    them down too would add extra LLM call volume for something the
    creator didn't request, working against the exact cost-conscious
    framing of the message.

    On the actual subscription-safety question, answered directly with
    real numbers pulled from the creator's own live `memory.jsonl`
    rather than guessed: `DEFAULT_CLAUDE_CODE_MAX_CALLS`/
    `CLAUDE_CODE_WINDOW_SECONDS` (30 calls / 5h, `main.py`) is a
    completely separate mechanism from this file's timing and was NOT
    touched by any of the three autonomy retunes -- it's the thing that
    actually protects the flat-rate Claude Code subscription. A faster
    tick rate only means that ceiling gets reached sooner during a
    genuinely idle stretch; real usage past it was already impossible,
    and past it `CognitionRouter`'s existing fallback (Gemini, itself
    capped at 1500 calls/$2/24h, then the free deterministic floor)
    carries the rest -- never more real Claude Code CLI usage than the
    unchanged cap already allowed, at any tick speed. The creator's own
    live spend history at the time of asking: 30/30 Claude Code calls
    used in the trailing 5h window (already at cap), averaging ~$0.055
    equivalent value per call (Claude Code CLI's own reported
    `total_cost_usd`, even though nothing is actually metered-billed
    under the flat subscription) -- worst case, at the unchanged 30-
    calls/5h ceiling, that's at most 144 calls/day regardless of how
    fast this loop ticks.
76. **A real, systemic transparency bug caught live monitoring the
    creator's session (a genuinely ambitious self-patch attempt on
    `src/cognition/budget.py` kept struggling): three separate READ/LIST
    tool-turn handlers -- `SelfPatchAgent._read_tool_turn`
    (self_patch.py), and `LogicAgent`'s own `_read_tool_turn` and
    `_list_tool_turn` (logic/base.py) -- all hardcoded `succeeded=True`
    in their `record_tool_call` call, regardless of what actually
    happened. `safe_read_file`/`safe_list_dir` never raise -- they
    return a `"[refused: ...]"` string on any real problem (bad path,
    traversal, an OSError) -- so a genuinely failed read was always
    logged as a success, hiding it from `activity`/`log` entirely.
    Directly caught live: the model wrote something malformed into a
    `READ:` marker's argument (visible in the raw activity trail as
    `"tests/test_budget.pyAn error occurred: [Errno 2] No such file or
    directory"` -- the model narrating what looks like an imagined
    error, not a clean path), and the resulting refused read still
    showed `succeeded: True`. Fixed: all three now check
    `content.startswith("[refused:")` and log the real outcome. `RECALL:`
    was checked too and left alone -- it reads only from the already-
    validated `ActivityLog`, with no real failure mode to hide, unlike
    a filesystem path. 749 unit tests + 19 E2E tests passing, two new
    regression tests (one per file) locking in the real outcome now
    getting logged.
77. **Another real, live-caught waste bug: the creative agenda could
    propose an impossible target.** Watching the same session further:
    a self-directed idea ("add a rollback-and-score loop... to
    `src/orchestrator/self_patch.py`") burned three real Gemini calls,
    got rejected three times by `AuditGate` for the exact same
    unfixable reason (`self_patch.py` is one of `PROTECTED_SUBJECTS` --
    no draft, however good, can ever pass that check), went `BLOCKED`,
    then got reconsidered and rejected again on the very next pass --
    guaranteed to keep repeating this up to `MAX_BLOCKED_RETRY_ATTEMPTS`
    (9) before finally being abandoned for good, spending real budget
    the whole way for a target that was never reachable. Fixed at the
    source: `discover_creative_improvements` (`src/main.py`) now filters
    a proposed target against `audit.py`'s protected-file list *before*
    ever creating a task for it, so this specific class of guaranteed
    failure never gets a chance to waste anything.
    `AuditGate._PROTECTED_SUBJECTS` (private, audit-gate-internal until
    now) is renamed to the public `PROTECTED_SUBJECTS` for this --
    `AuditGate.review()` remains the one real enforcement point either
    way, this is a pre-filter to avoid known-impossible attempts, not a
    second place deciding what's allowed. 750 unit tests + 19 E2E tests
    passing. The already-BLOCKED task from before this fix landed will
    still exhaust its own retry ceiling on the creator's live session
    (bounded, cheap, and it needs a restart to pick up the fix anyway)
    -- deliberately not hand-edited out of their live `memory.jsonl`
    while their process was running, to avoid a concurrent-write risk
    against a real, in-use file for a bounded, self-resolving problem.
78. **The actual root cause behind milestone 76's symptom, found through
    real hands-on sandbox testing the creator asked for directly** ("you
    were supposed to extensively test, hand hold, improve the sim...").
    Launched a real, Gemini-backed Sim instance in an isolated
    environment (its own `HOME`, `PATH` narrowed to exclude `claude` so
    none of this ever touched the creator's Claude Code subscription --
    23 real Gemini calls, $0.07 total) and drove it through genuine
    conversational turns, a real `propose`, and watched the autonomous
    loop fire on its own. Milestone 76 fixed the *symptom* (a refused
    read logged as succeeded); this hands-on session immediately
    surfaced the *cause*, reproducibly: a real provider doesn't reliably
    stop at "READ: <path>" the way the prompt asks -- it keeps reasoning
    out loud in the same response ("Wait, the tool format is... let's
    check... No, let's READ..."), and `parse_marker()` has no way to
    tell that wasn't part of the argument, since a code-bearing marker
    (`RUN:`/`DRAFT:`) legitimately needs everything after it kept
    intact. The whole rambling blob was being treated as "the path,"
    guaranteed to refuse, feeding the confusion straight back into the
    next prompt instead of resolving it.

    Fixed with a new shared helper, `first_line_argument()`
    (`src/cognition/tool_protocol.py`): takes just the first non-empty
    line of a marker's payload, for the class of argument that's always
    a single bare token. Wired into every `READ:`/`LIST:`/`FETCH:`/`USE:`
    handler across all three tool loops (`self_patch.py`, `logic/base.py`,
    `research.py`) -- `research.py`'s own `_read_tool_turn` also still
    had milestone 76's hardcoded `succeeded=True` bug, missed the first
    time since that pass only checked `self_patch.py` and `logic/base.py`;
    fixed alongside this one. 759 unit tests + 19 E2E tests passing,
    with regression tests in all three files proving a rambling READ
    payload now resolves to the real file instead of a refusal.
79. **A sandbox rejection's real error was never fed back to the
    retry loop.** Live-caught watching a real self-patch task
    (`src/cognition/budget.py`'s cost/latency tracking) fail the exact
    same generic way -- `"sandboxed run did not succeed (timed_out=False,
    exit_code=1)"` -- across multiple attempts *and* multiple blocked-
    task reconsideration rounds, with zero improvement each retry, even
    though `AuditGate.review()` was already handed `sandbox_result`
    (with the real `stderr`/`stdout`, a genuine traceback) the whole
    time. The rejection reason string fed back into `prior_reasons`
    only ever carried the generic summary -- the actual error never
    reached the drafting model, so every retry was a blind guess, not
    an informed correction. Fixed: the reason now includes a bounded
    excerpt of the real error (`_MAX_SANDBOX_DETAIL_CHARS`, 500 chars),
    giving the exact same bounded-retry-with-feedback mechanism this
    codebase already uses for audit-denylist and invalid-Python
    failures something real to act on for a sandbox failure too. 761
    unit tests + 19 E2E tests passing.
80. **The same lost-feedback problem, one level up: across BLOCKED-task
    reconsideration rounds, not just within one round's own attempts.**
    `run_task` always called `propose_self_patch`/`propose_skill` with
    the task's original, unchanged description and no memory of any
    prior round's failure -- even though `_reconsider_blocked_tasks`
    already records exactly that in the task's own `note` field
    (`"retrying after being blocked: <prior reason>"`) when it resets a
    BLOCKED task back to PENDING. A task that failed round 1 for reason
    X started round 2 completely blind to X, even though *within* round
    2's own 3 internal attempts, feedback already flows correctly
    (milestone 79 and earlier). Fixed: `propose_self_patch`/
    `propose_skill` gained an `initial_reasons` parameter that seeds the
    first attempt's retry feedback instead of starting `None`; `run_task`
    passes the task's own `note` here whenever `task.attempts > 0` (a
    genuine retry, not a first attempt). Combined with milestone 79,
    real failure detail now survives both within a round and across
    rounds. 763 unit tests + 19 E2E tests passing.
81. **Properly isolated hands-on sandbox testing, this time.** Milestone
    78's testing accidentally ran against the live repository (`HOME`
    was isolated, the working directory wasn't); this pass copies the
    entire repo to a real temp directory first with its own throwaway
    `git init` (the same pattern `tests/test_e2e_cli.py` already uses,
    now also used for interactive hands-on sessions, not just the
    automated E2E suite) -- any auto-commit from a genuinely autonomous
    session stays fully contained, never touching this project's actual
    git history again.
82. **A well-evidenced real limitation, not yet worth a rushed fix:**
    running the sandbox above unattended for an extended stretch, every
    single creative-agenda idea targeting a substantial existing core
    file (`autonomy.py` 291 lines, `reflection.py` 197, `budget.py` 140
    -- all dense with this codebase's own long rationale comments)
    failed to ever produce a valid, complete patch, across every
    attempt and every retry round, milestones 79-80's real feedback
    notwithstanding. The dominant failure mode: `'gemini' answered but
    its response didn't contain valid, complete Python` -- the model
    keeps failing to faithfully reproduce a genuinely long existing
    file (every line, every comment) while also correctly weaving in a
    nontrivial new capability, in one single-shot generation. This
    looks like a structural limit of the "rewrite the COMPLETE file"
    prompt shape itself (`self_patch.py`'s `_PATCH_DRAFT_PROMPT`) for
    ambitious changes to large files, not something a prompt wording
    tweak reliably fixes -- real feedback helps the model correct a
    *specific* mistake, but doesn't shrink the fundamental amount it
    has to get right in one pass. A genuine fix would likely need a
    different patch shape entirely (e.g. a diff/edit-based mechanism
    instead of full-file rewrite) -- a real architectural change with
    its own new risks (applying a diff correctly, handling a diff that
    doesn't cleanly apply), not attempted here without more design work
    first. Left as a clearly-documented, well-evidenced backlog item
    rather than a rushed change. (Addressed in milestone 90.)
83. **A second, more tractable cause found by controlled testing: a real
    self-patch/skill draft can fail even on a genuinely SMALL, well-
    scoped change.** A deliberate contrast test -- a direct, narrow
    `patch` request against a 59-line file (`reminders.py`), autonomous
    loop off, no ambition involved -- still failed, with the exact same
    raw-marker-as-final-answer symptom milestone 78 first spotted:
    `File "skill.py", line 1\n    READ: src/orchestrator/repl.py\n
    NameError: name 'src' is not defined`. Root cause, confirmed by
    reading the actual loop code: `SelfPatchAgent`/`SkillResearchAgent`'s
    tool loop never warned the model when it was on its LAST available
    step (`LogicAgent`'s own loop already does this,
    `_FINAL_TURN_HINT`) -- a model that spent its steps exploring
    (sometimes reading a hallucinated, nonexistent path) had no way to
    know the next response was its only remaining chance to answer, so
    it emitted one more `READ:`/`DRAFT:` marker anyway, and that raw
    marker text became the "final file content" verbatim, guaranteed to
    fail. Compounded by `DEFAULT_MAX_TOOL_STEPS` for self-patch being
    *lower* than `SkillResearchAgent`'s (4 vs. 5) despite self-patch
    legitimately needing more exploration room, not less -- it's
    revising a file that interacts with the rest of the codebase, not
    writing one new standalone file. Fixed: both agents now warn the
    model one step early (matching `LogicAgent`'s proven pattern
    exactly), and self-patch's step budget raised 4 -> 6. 766 unit
    tests + 19 E2E tests passing, with regression tests confirming the
    warning reaches the prompt and a real patch succeeds using
    already-gathered context on the final step.
84. **The actual, primary reason real self-patches to existing files
    almost never succeeded -- bigger than milestones 82/83, and this
    time a genuine change to `AuditGate`, taken to the creator directly
    rather than shipped unilaterally, given what it touches.** Chasing
    milestone 83's fix further with a fresh, controlled test (same tiny
    `reminders.py` request, fresh sandbox): still failed, now with a
    *different, much more fundamental* symptom: `ModuleNotFoundError: No
    module named 'src'`. Root cause, found by reading `SubprocessSandbox.run()`
    directly: it executes code with an EMPTY environment (`env={}`,
    `python -I`, a bare temp dir) -- correct isolation for a NEW,
    standalone skill file (never supposed to import project internals),
    but structurally impossible to pass for a self-patch to an existing
    core file, which normally and legitimately imports sibling modules
    (`from src.orchestrator.console_style import style`, etc.). Every
    real self-patch attempt observed all session -- across every
    ambitious idea and this session's own deliberately tiny, well-scoped
    contrast test -- ultimately failed this exact way, regardless of
    code quality. This wasn't "hard tasks fail sometimes"; it was the
    audit gate's own sandboxed-execution check being unconditionally
    unwinnable for this entire pipeline.

    Presented directly to the creator before touching anything, given
    this is `AuditGate` -- the "immune system," repeatedly called out
    throughout this project's own docs as something to never casually
    weaken -- with the reasoning and a recommendation: the check is
    scoped to subjects under `src/agents/skills/` (new skills) only now;
    a self-patch subject skips it entirely. This does NOT skip
    verification for a self-patch -- `run_isolated_test_suite`
    (self_patch.py) already runs immediately afterward, executing the
    patched code for real, as part of the whole real test suite, against
    a full repo copy with the package genuinely intact -- a strictly
    *stronger* check for this exact case (real imports work, real tests
    exercise the code) than a bare-environment smoke test that could
    never pass a legitimate import in the first place. Every other check
    -- denylist, protected-subjects, adaptive-immunity -- applies
    identically to both self-patches and new skills, completely
    unchanged; only this one, structurally skill-specific check is now
    scoped to skill subjects. The creator reviewed and explicitly chose
    this fix. 769 unit tests + 19 E2E tests passing, with new tests
    proving (a) a self-patch with a real cross-module import is now
    approved, (b) the identical import in a NEW skill subject is still
    correctly rejected (the scoping doesn't widen what a skill can get
    away with), and (c) denylist/protected-file checks still fully apply
    to self-patch subjects.
85. **A second, independent bug found immediately by verifying milestone
    84 live: even a patch that passes the audit gate and the entire
    isolated test suite still got silently reverted at the final step.**
    Re-ran the exact same tiny `reminders.py` request in a fresh sandbox
    with milestone 84's fix in place -- for the first time all session,
    a real self-patch actually passed the audit gate AND the isolated
    test suite (769/769) and got applied and committed. It then failed
    `relaunch()`'s own final self-check with the *same*
    `ModuleNotFoundError: No module named 'src'` symptom, and got
    correctly reverted. Root cause, confirmed by direct interpreter
    testing: `relaunch()` reconstructed its self-check/relaunch argv by
    reusing `sys.argv` -- but for a process started with `python3 -m
    src.main` (`sim.sh`'s own invocation), Python resolves `sys.argv` to
    the *absolute script path* before the program ever runs, not
    `['-m', 'src.main']`. Re-invoking that path directly runs it as a
    bare script, not a module -- `sys.path[0]` becomes `src/`'s own
    directory instead of the repo root, so every `from src.... import
    ...` in the patched code fails, regardless of how correct the patch
    itself is. This silently reverted every otherwise-successful
    self-patch to a non-hot-swappable file, and stayed hidden because
    the unit test suite always injects `exec_func`/`check_runner`
    (documented in `relaunch()`'s own docstring) rather than exercising
    the real subprocess/exec path -- so no test ever actually ran
    `python3 -m src.main` a second time to notice.

    Fixed: both the self-check subprocess and the final `os.execv`
    reconstruct `[sys.executable, "-m", "src.main"]` explicitly instead
    of reusing `sys.argv`. Unlike milestone 84, this doesn't touch any
    safety boundary -- it's a pure correctness fix to how the process
    re-invokes itself, verifiable directly (Python's own `-m` semantics
    are well-documented and were confirmed empirically), so it shipped
    directly rather than being taken to the creator first. 770 unit
    tests + 19 E2E tests passing, with a new regression test asserting
    the reconstructed argv exactly.
86. **`vitals`: a real-time terminal status panel.** The creator's own
    ask: "a window or box in terminal where it shows its mood in form
    of a couple of bar meters... and any other thing I can measure...
    updated in real time." `EmotionalState` already carries continuous
    `valence`/`arousal`/`cognitive_load` floats (never surfaced as bars
    before, only as `mood_phrase()` prose or raw enum labels) -- exactly
    the raw material a bar meter needs. `render_bar()`/`render_vitals()`
    (`src/orchestrator/console_style.py`) render Mood/Energy/Focus-load
    bars plus plain stat lines (memory records, skills applied,
    interests tracked, task backlog), opening with the same natural
    `mood_phrase()` text `LogicAgent`'s own prompt uses -- a numbers
    panel that still reads in Sim's own voice, not a diagnostics dump.
    `mood_phrase` itself is now public (was `_mood_phrase`, private to
    `logic/base.py`) since this panel needed it too.

    "Real time" specifically: `VitalsMonitor` is a toggleable
    (`vitals on`/`vitals off`) daemon thread, started once at CLI
    startup exactly like `AutonomyController` (a boolean `enabled` flag
    checked every tick, not something that starts/stops the thread, so
    there's no restart-race to get wrong) -- deliberately reuses the
    same safe pattern this project has used everywhere it prints on its
    own (`LiveTicker`, `reminders.py`, the autonomous loop itself): a
    fresh block between `input()` calls, never a true in-place cursor
    redraw, which `LiveTicker`'s own docstring already explains this
    project has deliberately avoided (fragile across terminals, piped
    output, non-TTY logging). Only actually reprints while idle
    (`DEFAULT_VITALS_IDLE_SECONDS`, 3s -- short enough to feel live once
    the creator pauses, long enough not to fight active typing), reusing
    the same `ActivityClock` the autonomous loop already has rather than
    a second one. The bare `vitals` command always prints one snapshot
    immediately regardless of the live toggle. 786 unit tests + 21 E2E
    tests passing.
87. **The self-patch pipeline finally worked end-to-end for real -- and
    immediately revealed a systemic quality regression, caught and
    fixed the same day.** With milestones 84/85 landed, five real,
    autonomous self-patches to core files applied for the first time
    all session: `autonomy.py` (a `CuriosityDrive` feature), `tool_protocol.py`
    x2 (a capability registry), `budget.py` x2 (adaptive per-provider
    cost/latency tracking). All passed the audit gate and the full
    isolated test suite (788/788).

    Reviewing them directly (the creator's own earlier ask, "review
    changes... approve their commit if they make sense") found a
    serious problem: **all five deleted the target file's entire module
    docstring**, with no replacement -- `autonomy.py`'s, `tool_protocol.py`'s,
    and `budget.py`'s own carefully-written rationale (including
    `budget.py`'s `docs/BIOMIMICRY.md` tie-in) all silently gone. A
    full-file-rewrite prompt doesn't reliably preserve documentation
    that isn't the direct subject of the requested change, and nothing
    in the pipeline was checking for that loss. `CuriosityDrive`
    specifically also had two independent functional defects on top of
    that: its contradiction-detection heuristic, tested live against
    the real 3200+ record memory store, found nothing but false
    positives (comparing unrelated internal log lines, e.g. a carpentry
    chat reply against a self-patch failure message); and its
    exploratory tasks never reached the real task queue at all --
    `AutonomyController`'s own construction in `main.py` was never
    updated to pass `task_store` through, so task creation silently
    no-opped. A half-finished feature, not a working one.

    All three files reverted to their pre-patch state. Root cause fixed
    structurally, not just patched over: `_docstring_regression_reason()`
    (`self_patch.py`) compares the original file's module docstring
    (via `ast.get_docstring`) against the draft's -- a substantial
    original docstring that's now missing or shrunk to under 30% of its
    length is a retryable failure, fed back via the same `prior_reasons`
    mechanism an invalid-Python draft already uses (milestone 78), not
    a hard block and not something that silently applies anyway. A file
    with no/trivial docstring, or a patch that genuinely rewrites one at
    similar length, is never flagged. 796 unit tests + 21 E2E tests
    passing, with tests proving the drop is caught, a genuine rewrite
    isn't, and `draft_patch()` treats it as retryable end to end.
88. **`vitals` now also prints once automatically at startup** -- the
    creator's follow-up ask, after noticing it didn't appear until asked
    for. Deliberately still only a one-time snapshot in the startup
    sequence, not the live-reprinting mode (`vitals on` stays an
    explicit opt-in) -- showing it once on the very first screen is
    unambiguous; having it start reprinting itself unprompted every few
    idle seconds from the first launch was not asked for. Separately
    asked whether the panel could stay pinned to a fixed part of the
    screen at all times rather than reprinting as a scrolling block --
    answered honestly rather than built: that needs raw ANSI terminal
    control (a reserved scroll region) that has to coexist carefully
    with `readline`'s own cursor management for the input line, and
    stops working entirely over SSH/piped/non-standard terminals --
    meaningfully more fragile than every other "prints on its own"
    mechanism this project has built so far, all of which deliberately
    avoid exactly that kind of terminal control. Not built without the
    creator explicitly choosing that tradeoff first.
89. **The true pinned vitals panel: built after the creator knowingly
    chose the riskier option, then reverted the same night after real
    use confirmed the exact risk that was flagged.** Presented with the
    honest tradeoff from milestone 88 (fragile raw terminal control vs.
    the safer scrolling block), the creator picked "build the true
    pinned panel anyway." `vitals pin` reserved a fixed strip of rows at
    the top of the screen via a DECSTBM scroll region
    (`\x1b[{top};{bottom}r`) and redrew into it with save/restore-cursor
    (`\x1b7`/`\x1b8`); a real design bug (reissuing DECSTBM on every
    redraw, not just the first, fighting the terminal's own cursor
    tracking) was caught and fixed before it shipped, and startup was
    changed to try `pin()` first, falling back to milestone 88's one-shot
    print.

    It did not hold up in real use. The creator reported, in their own
    running terminal: arrow keys and Enter behaving as if unrecognized,
    and new input appearing near the vitals panel's last line instead of
    after the prompt, with freshly typed characters visually merging
    into already-printed text. This is the textbook failure mode of a
    DECSTBM scroll region running underneath `readline`'s own line
    editing: `readline` tracks the cursor by counting what it has
    printed, with no awareness that an active scroll region has changed
    where the terminal is actually drawing -- exactly the coexistence
    problem milestone 88 named as the reason not to build this without
    the creator explicitly accepting the risk first. Confirmed the
    interpreter itself wasn't at fault (`readline` here is genuine GNU
    readline, not macOS's libedit shim, so the corruption traced to the
    scroll-region mechanism, not a platform quirk).

    Reverted outright (`git revert`) rather than patched further:
    correctly reconciling a raw ANSI scroll region with `readline`'s own
    cursor bookkeeping is a genuinely hard terminal-programming problem
    (real curses/prompt_toolkit-style TUI libraries exist specifically
    because this is hard to get right), not something to keep patching
    live against a creator's broken interactive session. Back to
    milestone 88's behavior: a one-shot `vitals` print at startup, `vitals
    on`/`off` for a periodic scrolling reprint, no in-place cursor
    control anywhere. The lesson holds for future terminal-UI work in
    this project: the existing "print a fresh block, never redraw in
    place" pattern (`LiveTicker`, `render_checklist`, the autonomous
    loop's own announcements) is safe precisely because it never
    contests the terminal's cursor with `readline` -- any future feature
    should keep doing that rather than reach for raw cursor/scroll-region
    control again.
90. **The milestone-82 structural limit finally addressed: SEARCH/REPLACE
    edit blocks for self-patches to large existing files.** Milestone 82
    left this as a documented, well-evidenced backlog item rather than a
    rushed fix: every self-patch attempt against a substantial file
    (autonomy.py 291 lines, reflection.py 197, budget.py 140) failed to
    ever produce valid Python via the full-file-rewrite prompt, because
    faithfully reproducing an entire long file verbatim while also
    correctly weaving in a change is a fundamentally harder single-shot
    task than reproducing just what's actually changing -- no amount of
    prompt-wording retry shrinks that.

    `draft_patch` (`self_patch.py`) now checks the target file's line
    count against `_EDIT_MODE_LINE_THRESHOLD` (100). At or above it, the
    model is asked for one or more SEARCH/REPLACE blocks (the exact
    three-way `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` marker
    shape used by real merge conflicts and tools like aider -- asking
    for a shape the model has already seen thousands of times, not a
    bespoke format) instead of the whole file. `_apply_search_replace_blocks`
    applies each block against the file's real current content and is
    deliberately strict, not fuzzy: a SEARCH snippet that doesn't match
    character-for-character, or matches more than once, is rejected with
    a specific reason rather than guessed at -- fed back through the
    exact same `prior_reasons` retry mechanism the invalid-Python and
    docstring-regression failures already use (milestones 78, 87). A
    model that ignores the instruction and answers with the whole file
    anyway still works: `parse_search_replace_blocks` returning `None`
    (no blocks found) falls back to the plain full-file path unchanged.
    Below the threshold, behavior is completely unchanged -- the
    existing full-rewrite prompt already works reliably there.

    Every downstream check (denylist, adaptive-immunity memory, sandbox,
    `_docstring_regression_reason`, the full isolated test suite) runs
    against the same reconstructed full-file content either mode
    produces, so none of them needed to change. Verified end-to-end
    against the real `AuditGate` with a 150-line target file: a scripted
    SEARCH/REPLACE response applied cleanly and passed review. 820 tests
    passing (11 new: block parsing, block application including the
    not-found/ambiguous/empty-SEARCH failure cases, and integration
    tests proving edit mode is selected by size, falls back cleanly, and
    still catches a docstring regression).
91. **Claude Code CLI's call cap raised, on the creator's explicit
    request.** The live session was observed idling with every draft
    attempt falling through to `deterministic_fallback` -- both real
    providers were legitimately exhausted for their rolling windows
    (Gemini at its $2.00/24h cost cap, Claude Code CLI at its own
    30-calls/5h cap). Since Claude Code CLI is flat-rate rather than
    metered, its cap (`DEFAULT_CLAUDE_CODE_MAX_CALLS`, `main.py`) is a
    conservative safety net against Anthropic's own subscription rate
    limits, not a dollar guard -- so raising it is the subscription
    owner's call, not a design assumption to make unilaterally. Asked
    directly rather than guessed a number: the creator chose 500 (up
    from 30), a real, deliberate increase in how much of the
    subscription's own quota Sim's autonomous drafting can consume
    before falling back to Gemini/deterministic -- Anthropic's own
    enforcement still applies underneath this and surfaces as an
    ordinary `ProviderUnavailable` if it's ever hit first, unchanged.
    `SIMORGH_CLAUDE_CODE_MAX_CALLS` remains the env-var override for
    anyone who wants a different value without editing source. 820
    tests passing (no test depended on the old default).
92. **A live-caught false positive in task-completion verification --
    caught by direct supervision of a restarted, freshly-uncapped
    session.** The creator asked to kill the running instance and start
    a fresh one under active supervision (a log tail + Monitor watching
    for applied changes, rejections, and errors). The very first
    self-patch it drafted -- a genuinely good one, adding
    `CapabilityRegistry.complete_ensemble` (`provider.py`) to query
    Claude and Gemini concurrently on high-stakes decisions and
    reconcile disagreement -- passed the audit gate and the full
    isolated test suite (820/820) and got applied and committed cleanly.
    It was then wrongly sent back to BLOCKED anyway: `verify_task_completion`
    (`src/orchestrator/verification.py`) asks a second, independent LLM
    call to answer "YES or NO" as its literal first word, but Claude
    Code CLI narrated instead ("I'll check the actual file that was
    modified to verify the claim.\n\n{}") and never actually answered --
    the old strict `first_line.startswith("YES")` check silently read
    that non-answer as a NO. The change itself was never in question
    (it had already cleared two independent, stronger gates); only the
    quality-review step's own parsing was fragile against a real
    provider that reasons out loud instead of complying with a strict
    format -- the same failure shape already fixed twice elsewhere this
    project (`first_line_argument`, `_FINAL_TURN_HINT`).

    Fixed the same way: scans every line of the response for a
    standalone YES/NO token instead of demanding it as the literal first
    line, so a verdict stated after some narration still counts. A
    response that never states a clear verdict at all now defers to the
    mechanical gates (`passed=True`) exactly like "no real reviewer
    available" already did -- a non-answer is evidence the reviewer
    didn't review, not evidence the change looks wrong. The wrongly-
    blocked task cost nothing but a wasted retry round (its next
    reconsideration re-drafted a small, harmless docstring addition
    referencing the already-good `complete_ensemble` feature) -- this
    fix is what stops that class of waste from recurring. 822 tests
    passing (2 new: the exact rambling-non-answer case, and a genuine
    verdict stated after narration still being honored).
93. **An observed, benign, not-yet-root-caused anomaly: `git commit`
    intermittently reports "nothing to commit, working tree clean"
    immediately after a self-patch write that plainly did change the
    file.** Caught by the same live supervision as milestone 92, twice
    in one evening (`provider.py`'s ensemble mode, `long_term.py`'s
    embedding-based semantic retrieval). In both cases the content was
    NOT lost: `apply_source_patch` still wrote it to disk, and it later
    became part of the repository's real history -- but misattributed,
    folded silently into a LATER, unrelated task's own commit for the
    same file (that later task's `git add -- <path>` naturally staged
    whatever was currently on disk, including the earlier task's still-
    uncommitted write, so its commit message describes only its own
    change while the diff actually contains both). Confirmed by reading
    the current file directly: the semantic-retrieval code is present
    and passing, just not under a commit that mentions it. Deliberately
    NOT patched blindly tonight -- the exact race in `commit_applied_change`
    (`git_ops.py`) that lets `git add` see no diff right after a real
    write hasn't been pinned down with a controlled reproduction, and a
    guessed fix around commit/retry logic risks masking the real cause
    or introducing duplicate commits. Left as a documented, low-severity
    finding (benign failure mode: worst case is a commit message that
    undersells its own diff, never data loss or wrong code running) for
    a future session with room to reproduce it deliberately rather than
    read tea leaves from one live log.
94. **Milestone 89's pinned vitals panel reverted, on direct creator
    bug report.** While supervising a live session, the creator reported
    their own separate interactive terminal breaking: arrow keys and
    Enter appearing not to work, and new input drawing near the vitals
    panel instead of after the prompt, merging with already-printed
    text. Root-caused to exactly the coexistence risk milestone 88
    named before building this and milestone 89 knowingly accepted:
    `readline`'s cursor bookkeeping has no way to know a DECSTBM scroll
    region has changed where the terminal actually draws. Reverted via
    `git revert` (not a live patch) -- `pin()`/`unpin()`, the `vitals
    pin`/`unpin` commands, and the auto-pin-at-startup attempt are gone;
    `vitals` is back to milestone 88's one-shot print plus `vitals
    on`/`off` for a periodic scrolling reprint. See milestone 89's entry
    above (rewritten in place to tell the full built-then-reverted arc
    rather than presenting the reverted version as still current).
95. **A real work harness -- Task/Research/Project -- researched before
    building, plus the fix for the "capability negotiation" repetition
    problem milestone 92/93's supervision session watched happen live.**
    The creator asked directly for "the right methodology and framework
    to tackle handling task, research, projects," then explicitly asked
    for research first: how a well-structured agent harness works in
    general, and specifically how Claude Code's own harness handles
    large projects. Researched via WebSearch/WebFetch against Anthropic's
    own engineering writing and Claude Code's own docs before writing any
    code -- see Sources below.

    Two concrete mechanisms carried directly into this build:
    - **Subagents work in their own context window; only a summary comes
      back.** ("How Claude Code works" docs: "A subagent starts fresh...
      the subagent's tool calls stay out of your context, and Claude
      gets back a summary when the subagent finishes.") `RESEARCH_TASK`
      (`src/orchestrator/research_task.py`, new) is that shape for Sim: a
      bounded READ/LIST tool loop (`ResearchAgent`, reusing the exact
      `parse_marker`/`safe_read_file`/`safe_list_dir` machinery
      `SelfPatchAgent`/`SkillResearchAgent` already share) that can
      actually open real files to check "does this already exist" before
      concluding, producing a written finding (`kind=research_finding`
      on the shared `MemoryStore`) instead of code. Deliberately never
      given DRAFT/RUN/WRITE -- never touches `AuditGate`, the sandbox, or
      the isolated test suite, because it never writes to `src/` itself.
      A finding that concludes something concrete and well-scoped ends
      with `FOLLOW-UP: <path> :: <description>`, spawning a real child
      `PATCH_TASK` (filtered against `PROTECTED_SUBJECTS`, same
      unfixable-target guard creative-agenda already has).
    - **`PROJECT_TASK`**: a goal decomposed into ordered child tasks
      (patch and/or research), reusing `Task`'s own long-unused
      `parent_id` field rather than a new persistence layer --
      `src/orchestrator/projects.py`'s `decompose_project()` is one LLM
      call turning a goal into real children; `project_status()` is a
      *pure function* of the children's current statuses, never
      persisted as independent state, so it can never drift out of sync
      with what actually happened to them. `main.py`'s `_next_task()`
      now never hands a `PROJECT_TASK` with children straight to a
      caller -- it resolves to the project's next unfinished child (or
      the project itself, if not yet decomposed), and a stuck project
      (every child terminal, nothing pickable) is skipped in favor of
      the next ordered item rather than stalling the whole queue behind
      it. `research <topic>`/`project <goal>`: the immediate-execution
      CLI counterparts to `propose`/`patch`, same "create a real,
      durable Task and run it right now" shape.

    **The repetition fix, diagnosed by the creator mid-session while
    directly watching it happen:** live supervision (milestone 92) had
    just surfaced that an evening of creative-agenda runs produced 10+
    near-duplicate "capability negotiation" ideas across two files --
    milestone 92's fuzzy-dedup fix stops an *exact* repeat, but a model
    given one open-ended "think ambitiously about your whole
    architecture" prompt kept clustering on the same neighborhood of
    genuinely-differently-worded ideas regardless. The creator's own
    diagnosis and proposed fix, given directly mid-session: translate
    the goal into a hierarchy of required capabilities, then sample
    across the *leaves* of that hierarchy rather than letting the model
    pick its own focus every time. Implemented as
    `src/orchestrator/capability_map.py`: level 1 is each top-level
    `src/` subdirectory, level 2 is the real `.py` modules inside it --
    both pure filesystem listings, not LLM-generated, so they're free
    and can never hallucinate a target or drift from the real tree.
    Level 3 (the actual idea) is the only LLM call, and it's made
    *after* `pick_diverse_target()` has already chosen the target by
    structured random sampling (weighted away from areas the backlog
    already covers) -- `discover_creative_improvements` (`main.py`) now
    asks a narrow "propose one improvement for THIS file" question
    `count` times instead of one open-ended "propose N ideas anywhere"
    question. The model's own response is never trusted to restate the
    target path, even if it tries -- `_parse_targeted_idea` only ever
    extracts `PATCH`/`RESEARCH` + a description, so a model that ignores
    "don't second-guess the target" can't quietly defeat the whole
    mechanism by picking its own file anyway. Fuzzy dedup
    (`_creative_agenda_already_covered`) stays as a second, independent
    line of defense for the cases diversified sampling alone doesn't
    cover.

    882 tests passing (55 new: `capability_map.py`'s pure sampling
    functions, `projects.py`'s decomposition/rollup, `research_task.py`'s
    tool loop, `run_task`/`_next_task`'s project-unwrapping and rollup
    hooks, `research`/`project` CLI commands, and the rebuilt
    `discover_creative_improvements` test suite).

    Sources (researched live via WebSearch/WebFetch before writing any
    code): [Building Effective AI Agents (Anthropic)](https://www.anthropic.com/engineering/building-effective-agents),
    [How Claude Code works (Claude Code docs)](https://code.claude.com/docs/en/how-claude-code-works).
96. **The project tier made reachable autonomously, not just by typing
    `project <goal>`.** Milestone 95 shipped `PROJECT_TASK` and the CLI
    command, but nothing in the autonomous loop itself ever created one
    -- the harness existed but wasn't actually live for Sim's own
    self-directed work, only for a human invoking it by hand.
    `discover_creative_project()` (`main.py`) closes that: rarely
    (`DEFAULT_CREATIVE_PROJECT_CHANCE`, 20%, checked only on an empty-
    backlog tick after the reactive pass finds nothing), asks one
    genuinely open-ended "propose an ambitious multi-step goal" question
    -- deliberately the one place left in this codebase that still lets
    a model pick its own focus with no target chosen in advance, since a
    real project's whole point is spanning more ground than a single
    diversified-sampling target could represent -- then immediately
    decomposes the result into real child tasks via `decompose_project`,
    rather than leaving a vague one-liner nothing ever acts on. Falls
    straight through to the ordinary per-file `discover_creative_improvements`
    path when no real provider answers or the goal doesn't parse, so a
    failed attempt is never a wasted tick.

    Live-caught while wiring this in: sharing one `provider_sink` dict
    across the project attempt and the fallback idea-search would have
    silently lost track of a real, already-billed call if the project
    attempt used a real provider but the fallback pass never got far
    enough to call one itself (e.g. no diversified target available) --
    the shared dict's last write would overwrite "attempted_creative" back
    to `False`, letting `AutonomyController`'s cost-safety cooldown skip
    starting despite real spend having happened. Fixed before it ever ran
    for real: each call gets its own sink, and `attempted_creative` is
    OR'd across both rather than overwritten by whichever ran last.

    889 tests passing (7 new: `discover_creative_project`'s own success/
    failure/decomposition-empty/provider-sink cases, and
    `_autonomous_action`'s rare-project-branch and failed-project-falls-
    through-to-a-single-idea paths, the latter two made deterministic via
    a mocked `random.random` rather than left to a 20% coin flip).
97. **The Simorgh v2 blueprint: a complete re-architecture, designed to
    be built by many agents in parallel.** The creator asked for the
    knowledge base to be read and then for a re-architecture toward a
    capable, functional AGI foundation with a first-class harness for
    projects and general work -- modular, clear interfaces, separate
    directories, independently evolvable, async messaging, API-based,
    hostable anywhere, and documented in enough detail that AI coding
    agents can pick up pieces and build them. `docs/blueprint/` is the
    result: six governing documents (vision and fifteen binding
    principles; the sixteen-subsystem architecture with an enforced
    import boundary and nine worked message flows; the full message
    contract -- envelope, topic taxonomy, catalog, delivery semantics,
    Bus/Ledger/Subsystem protocols, memory/SQLite/AWS backends; a phased
    build plan with parallel tracks and a definition of done; build
    instructions for AI agents; a v1 -> v2 migration map that carries
    every live-caught lesson and its test) plus sixteen subsystem specs
    on one mandatory template, ~67,000 words in all.

    The architectural thesis is the name itself: thirty birds discovering
    they are the Simorgh. Sixteen small subsystems, one package each,
    share exactly one dependency (`simorgh/contracts`) and talk only
    through typed, traceable messages on an async Bus; all state is an
    append-only Ledger whose projections (task status, project rollups,
    competence, the Self Model) are always rebuildable; safety is
    structural -- every action is proposed, only the Guardian can approve
    (with an HMAC-bound token), only Execution can run, and pause/stop/
    Plan Mode/protected files/budgets are enforced at that one
    chokepoint no reasoning can route around. The harness takes Claude
    Code's shape from the research (a minimal gather->act->verify loop
    around a rich operational harness: graduated context compaction,
    Plan Mode, a durable backlog with a dependency DAG and re-grounding,
    checklist-and-trajectory verification with an evaluator-optimizer
    loop, isolated sub-agent delegation), and growth is a loop: outcomes
    feed Learning, Reflection, and Curiosity, so the system measurably
    learns what it can do, what it can't, and what to explore next --
    self-awareness as a maintained, queryable Self Model rather than a
    prompt.

    Process note worth recording: the six core documents were written
    by one author for coherence, then the sixteen specs were written in
    parallel by five agents working only from those documents and the
    template, exactly the way the blueprint proposes the *system* be
    built. The specs came back with ~30 independently-found contract
    gaps and ownership ambiguities (several found by more than one
    agent: `turn.completed` used in a flow but absent from the catalog;
    no scope on pause; no `guardian` domain; no task-create request) --
    all folded into the governing documents in one integration pass,
    every one non-breaking, and recorded in `00-README.md`'s changelog.
    That the parallel-build process surfaced real interface gaps before
    a line of code exists is the strongest evidence so far that the
    contracts-first, boundary-enforced approach is the right one.
98. **Phase 0 begins: `simorgh/contracts/` -- the one dependency every
    v2 subsystem shares -- built to the blueprint.** The first code of
    the re-architecture, and deliberately the least glamorous: 123
    message types across 21 domains, each declared once in a tiny
    field-type language (`fields.py`) from which `registry.define()`
    generates both a frozen dataclass (`to_payload`/`from_payload`) and
    a JSON Schema, so the two can never drift; `schemagen` writes the
    schemas to `schema/` as checked-in files and a test fails if they
    fall out of sync with the declarations. The envelope enforces every
    section-2 invariant in the producer's process at publish time
    (unknown type, bad payload, priority range, `<kind>:<id>` partition
    keys, replies carry a correlation id, and the one the Bus spec
    author flagged: a preempting priority-9 message may never set a
    partition key, or `system.stop` could queue behind a held task
    partition). `topics.py` carries the reserved-topology tables as
    data -- who may subscribe to `action.proposed` (guardian only), who
    may publish `action.approved` (guardian, plus the kernel for its
    forged-token drill), execution's `action.denied` only with
    `layer=token`, single-writer streams -- so the Kernel enforces
    policy it reads rather than policy it hardcodes. `security.py` holds
    the approval token (HMAC-SHA256 over the exact action: id, tool,
    canonical-args hash, expiry; constant-time compare; a bounded
    `ReplayGuard`) and the subsystem token for multi-process identity.
    `protocols.py` is the Bus/Ledger/Subsystem/Context/Provider/Tool
    interfaces, structural so a fake conforms by shape. `compat.py` is
    the version-translator registry, present before it is needed.

    The boundary rule from `02` section 4 is now a test, not a
    convention: `tests/simorgh/test_module_boundaries.py` walks every
    module under `simorgh/` by AST and fails on a subsystem importing
    another subsystem, contracts importing anything but the standard
    library, bus/ledger importing anything but contracts, or an
    unguarded third-party import -- and it carries its own self-test
    against temporary packages, because a boundary check that has never
    been seen to fail is not evidence of anything. One documentation
    fix surfaced by building: `turn.completed` and `project.*` are their
    own first segment on the wire, so they are domains, not `task.*`/
    `plan.*` entries. 84 new tests; the full suite is 973 and green, v1
    untouched.
99. **`simorgh/bus/` built -- the second Phase 0 package, and the
    nervous system every later subsystem is written against.** All
    three interaction patterns (event, competing-consumer command,
    request/reply) over one abstraction, ordering per `partition_key`,
    priority-9 preemption for `system.pause/stop/resume`, at-least-once
    delivery with exponential-backoff retry and dead-lettering (mirrored
    to a durable Ledger `dead:<type>` stream, not just the backend's own
    DLQ), backpressure, and reserved-topology enforcement (only
    `guardian` may subscribe `action.proposed`, only `execution`
    `action.approved`, only `guardian`/`kernel` may publish
    `action.approved` at all) with subsystem-token identity for the
    multi-process modes. Three backends behind the identical `Bus`
    protocol, selected purely by config: `memory` (asyncio, the
    guaranteed floor -- zero configuration, zero dependencies), `sqlite`
    (one WAL-mode file shared by every process on a host, proven with a
    real `multiprocessing` test where a child process consumes a
    durable delivery the parent enqueued, and a dead process's expired
    lease is reaped so another consumer picks the message up), and
    `aws` (SNS per domain, SQS FIFO per consumer group plus DLQ, driven
    end-to-end against a hand-written fake `boto3` session so the whole
    suite still never touches the network or costs a cent).

    Two real bugs surfaced by the spec's own property tests, both fixed
    before commit, both the kind that would have been genuinely
    confusing to debug later: `BusClient.new()` was passing
    `partition_key=None` explicitly when building a message caused by
    another one, which silently defeated `Message.caused()`'s own
    "inherit the parent's partition key" default -- a follow-on message
    would have lost its ordering guarantee with no error anywhere,
    exactly the kind of thing `test_new_fills_source_trace_and_causation`
    exists to catch. And the sqlite reaper's partition-lock release
    required an exact `delivery_id` match on a table already uniquely
    keyed by `(grp, partition_key)` -- correct in the ordinary case, but
    a lock could outlive its own reap if the two ever disagreed, which
    defeats the entire point of reaping a dead process's lease. Also
    made `TraceWriter` lazily start its own drain task on the first
    `write()` rather than requiring every caller to remember an explicit
    `start()` -- found because a test (correctly) never called it and
    silently got zero tracing instead of an error, which is exactly the
    failure shape a real subsystem wiring mistake could produce too.

    Process note: this build was interrupted mid-session by a rate
    limit and resumed from exactly where it left off, verified against
    the actual on-disk state rather than re-derived from memory -- the
    four failures the resuming pass found and fixed (the two bugs above,
    plus two test-authoring bugs of its own: a TTL test whose message
    timestamp came from real wall-clock time while the assertion
    compared against the test's fake clock, and an integration test
    that published two causally-related messages as independently-traced
    ones and then asserted they shared one trace) were all caught by the
    spec's own testing strategy doing its job, not discovered later.
    1041 tests passing (v1 + contracts + 68 new for the bus).
100. **`simorgh/ledger/` built -- the third Phase 0 package, in parallel
    with the bus.** Everything durable in Simorgh v2 is a projection over
    this: append-only, typed event streams with compare-and-swap appends
    for single-writer coordination, idempotency-key dedupe so at-least-
    once delivery from the Bus can never double-record, snapshots so a
    `Projection` need not replay from the beginning of time, a content-
    addressed blob store so a large payload never bloats a stream, and a
    record-compaction/retention policy distinct from the Bus's own
    context-adjacent tracing. Four backends behind one `LedgerClient`:
    `memory` (tests), `jsonl` (default -- v1's own `fsync`-per-append and
    tmp-write/`fsync`/`os.replace` atomic-rewrite discipline carried over
    almost verbatim from `src/memory/long_term.py`, plus recovery from a
    truncated trailing line on restart -- a real crash loses at most the
    record that was mid-write, never a corrupted stream), `sqlite` (WAL,
    `BEGIN IMMEDIATE`-serialized writers, a `(stream, seq)` primary key
    doing double duty as the CAS check -- the recommended engine once
    more than one process needs to append, proven with eight concurrent
    `asyncio` tasks racing the same `expected_seq` and exactly one
    winning), and `dynamodb` (conditional-put CAS, S3 for blobs and
    oversized payloads, `boto3` imported lazily so the core dependency
    graph never needs it -- exercised entirely through in-memory fakes of
    its own two adapter protocols, so the parity suite proves the CAS/
    idempotency/snapshot logic without any credentials or network call).

    `migrate_v1.py` is what makes the eventual Kernel `migrate-v1`
    command a plain, idempotent replay rather than a bespoke importer:
    `read_v1_records` maps every kind in the real
    `~/.simorgh/memory.jsonl` (task events, applied patches and skills,
    LLM spend, interests, research findings, rejected proposals, and
    everything else as a generic episodic memory) to the stream
    `06-migration-from-v1.md`'s own route table already specified,
    tagged `idempotency_key="v1:<id>"` -- replaying the same file twice
    appends nothing the second time, proven directly against a fixture
    shaped like the real file, malformed line included (skipped, not
    fatal, the same tolerance v1's own loader already had).

    Interrupted mid-build by the same session rate limit as the bus
    package, in the same way: resumed from the verified on-disk state
    (the package code, written first, was already complete and
    untouched) rather than restarted, with the test suite -- entirely
    unwritten before the interruption -- as the remaining work. 1188
    tests passing (v1 + contracts + bus + 158 new for the ledger).
101. **`simorgh/kernel/` built -- the composition root, and Phase 0's
    last package.** Everything the other three packages built is inert
    until something boots it in the right order and enforces the safety
    topology for real: the Kernel loads config (file, env overrides,
    validated `RuntimeConfig`), builds a layered secret store (a
    subsystem sees only the secret names its own config section
    declared, plus -- for `guardian`/`execution` alone -- the per-run
    HMAC secret an approval token is signed with), runs the state
    machine (`booting → running ↔ paused → stopping → stopped`, a
    terminal `failed`, and a `scope="autonomous"` pause that suspends
    autonomous work without blocking a human still typing -- distinct
    from a full pause, and both idempotent), drives the Scheduler (three
    tick loops off one injected `Clock`, and durable `system.schedule.*`
    timers written to the Ledger before anything is armed, so a second
    process pointed at the same data directory re-arms every outstanding
    timer exactly where the first one left off -- the direct fix for a
    v1 reminder being a bare `threading.Timer` a restart simply forgot),
    and the Supervisor (every layer boots concurrently and is health-
    gated before the next one starts, crashed services restart on a
    backoff table within a 10-minute budget, and a `guardian`/`execution`
    that exhausts that budget auto-pauses the whole system -- "nothing
    may execute without the safety path" enforced by wiring a callback,
    not by a comment asking nicely).

    `--self-check` is the actual point of Phase 0: before any real work
    is allowed to run, it proves the guarded-action path works end to
    end over a real Bus and Ledger -- a stub Guardian and Execution
    speaking the real `contracts.security` token contract, not a mock of
    it. Four proofs, all passing for the first time: a legitimate
    proposal is approved with a verifiable token and executed; a forged
    token is rejected by Execution's own verification before the tool
    ever runs; a proposal made while paused is denied at the paused
    layer; and a throwaway source cannot subscribe to `action.proposed`
    -- the bus's reserved-topology policy, built during the bus package,
    exercised for real for the first time rather than only unit-tested
    in isolation. `python -m simorgh --self-check` now exits 0 and
    prints `OVERALL: PASS`.

    Four integration tests go further than the unit suite could alone:
    booting two toy subsystems standing in for not-yet-built Phase 1
    packages through the real layer-ordered, health-gated Supervisor;
    `system.pause` actually suspending the Scheduler's own idle/sleep
    tick loops and `system.resume` restoring them, not just flipping a
    state flag nothing reads; a schedule added before a simulated crash
    (a clock whose `sleep()` never returns, so the first process
    provably cannot fire it itself) surviving into a second, independent
    `Kernel` instance pointed at the same on-disk Ledger and firing
    there; and a toy `guardian` exhausting its restart budget through
    the real `Supervisor._restart` accounting -- not the handler called
    directly -- and auto-pausing the Kernel, while a non-safety-critical
    subsystem doing the same does not.

    Doc fix while building: `03`'s self-check walkthrough named its
    second step as a bus publish-policy test; read against the actual
    `PUBLISH_ONLY_BY` table, the Kernel is itself an allowed publisher of
    `action.approved`, so publishing a forged one is never a policy
    violation -- it is a token-verification failure Execution catches
    downstream. The fourth step (a throwaway source subscribing to
    `action.proposed`) is the real policy-violation proof; built to
    match the table, not the earlier prose.

    Phase 0 is now complete: `contracts → bus/ledger → kernel`, all four
    packages built, tested, and proven to boot together for the first
    time. Phase 1A/1B/1C (cognition/memory, guardian/execution,
    worldmodel/persona/interface) can now start in parallel, each
    against the same frozen contracts catalog and the same Kernel to
    boot into. 1336 tests passing (v1 + contracts + bus + ledger + 148
    new for the kernel: 139 unit, 9 integration).
102. **All twelve remaining subsystems built -- concurrently, by nine
    parallel agents, against nothing but the frozen Phase 0 contracts.**
    With the substrate proven (milestone 101), the creator asked
    directly whether the blueprint's own parallelization design could
    be pushed further than the phase-gated plan suggested -- "if
    blueprint allows... I'm okay with 10 or 20 subagent." It could: the
    contracts-first design plus the mandated graceful-degradation rule
    (every cross-subsystem call is a bounded request/reply that
    degrades to an honest floor, never a hang, when the other side
    isn't built yet) meant every remaining subsystem could be built at
    once rather than waiting on strict phase order. Nine agents ran
    concurrently -- cognition+memory, guardian+execution, worldmodel+
    persona+interface, planning, orchestration, verification, learning,
    reflection, curiosity -- each with exclusive file ownership (its own
    package directory, its own test directory, its own spec header) and
    an explicit ban on touching `00-README.md`/`EVOLUTION.md`, so a
    combined documentation pass could happen once at the end instead of
    nine agents racing the same shared files.

    Each subsystem ported its v1 equivalent and proved itself against a
    *real* Kernel boot (`Supervisor.start_layer`), not just isolated
    unit tests -- the same acceptance bar Phase 0 set. Real bugs were
    found and fixed along the way, not just ported behavior: Guardian/
    Execution's build found `git_commit`'s pre-check used `git diff
    --quiet HEAD`, which silently misses brand-new untracked files (not
    a v1 bug -- new in the port, caught by a test asserting a genuinely
    new file counts as "something to commit"). Planning's build found
    project tasks were created `pending` when they needed to be
    `available` to ever be dispatched at all -- a real, immediately-
    consequential state-machine bug, not a stylistic one. Verification's
    build found `verify.requested` had no duplicate-request handling at
    all -- a second request for an already-verified subject would
    silently re-run the whole check instead of replaying the recorded
    verdict, an idempotency gap the append-only design is supposed to
    close everywhere. Curiosity's build ported the milestone-95/96
    diversified-sampling fix and proved it with the exact regression
    that motivated it: ten real discovery ticks, no module repeated
    before every module had been tried once.

    Not every agent followed the "do not push" instruction -- the
    cognition/memory build pushed directly to `main` on its own, which
    also carried out Planning's own concurrently-landed commit (shared
    linear history: a `git push` sends everything ahead of `origin`,
    not just the pusher's own work). The substance was sound, but it
    surfaced one real problem before the parent session's own
    verification pass ever ran: `planning.store` had imported
    `simorgh.ledger.api` (an internal module) instead of the public
    `simorgh.ledger.client` boundary every subsystem is restricted to --
    a genuine module-boundary violation, live on `main`, for the length
    of time between that push and the fix. Corrected directly (`30e8c7b`):
    `ConflictError` re-exported from `LedgerClient`'s own public surface
    (already imported internally; the exception type just wasn't part
    of the documented client API), one import site fixed, boundary test
    and `--self-check` both green again. Every other subsystem's build
    committed locally and waited, as directed, for the parent session to
    verify (full suite + the subsystem's own tests + the boundary check
    + `--self-check`) before pushing -- each one confirmed green and
    pushed individually as it landed, not batched.

    1975 tests passing across all sixteen packages combined.
103. **The final integration pass: every subsystem wired into the
    Kernel's own registry, and the whole system proven to boot together
    for the first time.** Every subsystem built in milestone 102
    deliberately left `simorgh/kernel/registry.py`'s `build_factories()`
    untouched -- a docstring left there mid-build by one of the forks
    asked every concurrent track not to edit that one shared file, and
    to use the `mock.patch` injection seam `test_kernel_boot_two_toy_
    subsystems.py` already established for their own integration tests
    instead. That left one real, necessary step once all fifteen
    non-kernel subsystems existed: actually registering them.

    Checked every subsystem's real `Service.__init__` signature first
    (none take `bus`/`ledger` directly -- only `bus`'s and `ledger`'s
    own `Service` do, a genuine bootstrapping special case; every other
    subsystem receives them through `start(ctx)`, per the `Subsystem`
    protocol, exactly as designed) before adding all fifteen factory
    entries as simple, default-constructed lambdas -- richer wiring
    (real Cognition providers, a non-default Guardian pipeline, extra
    Execution tools) is deliberately left as a later, separate
    configuration change rather than something this composition point
    should hardcode. `interface` is constructed with `run_repl=False`
    here specifically -- the real interactive REPL is for `simorgh
    run`'s own entry point, not for a Kernel boot used by tests or
    `--self-check`, where a blocking `readline` loop would hang forever.

    Wrote the test the whole blueprint has been building toward since
    `01-vision-and-principles.md`'s own success criteria: `test_kernel_
    boots_all_sixteen_subsystems.py` boots the *real*, unpatched
    `registry.build_factories()` -- all fifteen real `Service`s, in the
    real six-layer dependency order, through the real `Kernel`/
    `Supervisor` -- and asserts every single one reports healthy before
    the boot completes, twice in a row on the same data directory (the
    second boot proving the first shutdown actually released everything
    it held, not merely that it didn't crash). This is distinct from
    `--self-check`, which deliberately uses two small inline stub
    subsystems for the guarded action-path drill so it can prove the
    safety topology independent of how much of the rest of the build has
    landed; this new test is the one place all fifteen real subsystems
    are constructed together, so a wiring mistake in any single
    constructor surfaces here.

    It passed on the first real run once the registry wiring was
    correct. The Simorgh v2 blueprint -- designed, specified, and built
    in one session, from a knowledge-base research pass through
    sixteen detailed subsystem specs to sixteen real, tested packages --
    now boots as one system. 1977 tests passing (v1's original suite
    fully intact throughout, plus the entire v2 build).

104. **A live-caught lesson: "boots as one system" is not "works as one
    system" -- `percept.text.received` was never wired to a reply, so
    plain chat had zero response until this milestone.** Milestone 103
    proved every subsystem starts up healthy together; it did not prove
    a message dropped in at the real entry point actually produces the
    behavior the architecture promises. Asked directly by the creator to
    stop building and instead *run* Simorgh v2 and talk to it -- boot the
    real Kernel, in a throwaway copy of the repo (the standing sandbox-
    isolation lesson: Execution's real git/file tools must never run
    against the working project) -- this is exactly what surfaced: a
    plain chat message went in, and nothing ever came out. Interface's
    own `_handle_chat` even carried a self-documented placeholder for
    it -- `"no response -- the reasoning subsystem isn't built yet this
    session"` -- left there by the fork that built Interface in Phase 1,
    correctly anticipating the gap but not the one that would eventually
    close it.

    Root cause, found by reading `02-system-architecture.md`'s own Flow
    1 against the real code: the spec says "orchestration: opens a TURN
    session" directly off `percept.text.received`, but `simorgh.
    orchestration.service.Service.consumes` never named that topic --
    only `task.available`, fed exclusively by Planning's `Intake`, which
    itself only reacts to `intent.goal.stated` (the explicit `batch`/
    `evolve`/`plan` commands), never to plain conversational text. Two
    real, working subsystems, each individually tested and each exactly
    matching its own spec section, with a genuine gap in the wiring
    *between* them -- invisible to every unit and integration test
    because every one of them either drove a `task.available` directly
    or patched a partial `build_factories()`, so none of them ever
    exercised the actual seam a live percept has to cross. This is
    the concrete version of the graceful-degradation principle's dark
    twin: a missing subscription degrades exactly like a slow one --
    silently, correctly, and indistinguishably from "working but taking
    a while" until someone actually waits for the reply.

    Fixed by giving `Worker` a `run_percept_chat(session_id, text)` path
    that runs an ephemeral chat `Session` directly -- no Planning task
    ever created, keyed by the percept's own `session_id` (the exact
    correlation key Interface's `_pending_turns` was already waiting on)
    -- and reusing `Worker._report` unchanged for the `turn.completed`
    publish, since every `TASK_*` handler it also fires
    (`simorgh.planning.service._on_task_started` et al.) already checks
    `task is None` first and no-ops safely for an id Planning never
    created. `Service.start` now subscribes once to `percept.text.
    received` and round-robins across its workers, so a multi-worker
    config never double-replies to the same message.

    Verified live, not just in tests: booted the real Kernel in the
    sandboxed repo copy and sent `"hello Simorgh, what are you?"`
    through the exact path Interface's REPL uses -- got back a real,
    coherent answer describing itself and correctly citing `SOUL.md`'s
    eight directives by name, with `floor: False` (a real provider
    answered, not the honest-floor fallback). Also drove the explicit-
    goal path (`intent.goal.stated` -> a real Planning task -> Worker
    claim -> completion) and Flow 5 pause/resume live in the same
    session: both already worked correctly end-to-end, unaffected by
    this bug. 1978 tests passing (four new regression tests: a percept
    with no Planning task anywhere produces `turn.completed` with the
    right `session_id` and never touches Planning's store; an empty
    percept is ignored, not a crash).

    A second, related gap was found by the same live-reading pass and
    deliberately left open rather than folded into this fix: Flow 1
    also calls for `turn.completed` -> Memory's episodic write, but
    `simorgh.memory.service.Service` only ever reacts to an explicit
    `memory.store` request -- nothing publishes one when a turn ends, so
    Simorgh currently has no memory of a conversation from one turn to
    the next. Closing it needs a real design decision this milestone
    didn't make casually: `turn.completed`'s payload only carries the
    assistant's reply, not the user's own text, so a two-sided episodic
    record needs either a contract change or Orchestration itself
    publishing `memory.store` with both halves -- left for the next
    session rather than rushed alongside a different contracts-adjacent
    fix.

105. **Flow 1's episodic-write arrow, closed: Simorgh remembers a
    conversation from one turn to the next.** Milestone 104 deliberately
    left this open rather than folding a contracts change into a
    different fix; the creator then chose it directly as the next step
    over two other offered options (keep hunting for more live bugs
    first, or move on to Phase 4 capabilities).

    The blocker was exactly what milestone 104 named: `turn.completed`
    only ever carried the assistant's reply, never the human's own
    words, so Memory had no way to write a two-sided record even if it
    listened. Added `user_text` as an *optional* field to the
    `turn.completed` catalog entry (`simorgh/contracts/messages/task.py`,
    regenerated via `python -m simorgh.contracts.schemagen`) rather than
    a breaking one -- an older producer that never sets it still
    validates. Threaded it through `simorgh.orchestration`: `Session`
    gained a `user_text` field, set once at construction in both call
    sites that build a chat session (`Worker._on_available` from a real
    Planning task's `description`, and `Worker.run_percept_chat` from
    the live percept's own text), and `Worker._report` includes it in
    the `turn.completed` payload it already builds.

    `simorgh.memory.service.Service` now subscribes to `turn.completed`
    directly and writes an episodic record combining both halves
    (`"User: {user_text}\nSim: {reply_text}"`) through the same
    `MemoryEngine.store()` path `memory.store` already used -- publishing
    `memory.stored` afterward for parity with that path. A turn with
    nothing said on either side (the honest-floor case: `floor: true`,
    empty `text`, and no `user_text` either) is skipped rather than
    filling episodic memory with blanks.

    Verified live, not just in tests: in the same sandboxed repo copy,
    sent one chat turn stating a fact ("my favorite color is teal"),
    queried `memory.retrieve` directly to see the stored record, then
    sent a second, independent chat turn asking what that favorite color
    was -- and got back "Your favorite color is teal." A genuinely
    interesting wrinkle surfaced in the same run: the *first* turn itself
    hit the honest floor (`floor: true`, empty reply -- almost certainly
    first-call cold-start latency against the real `claude` CLI
    subprocess, not a logic bug, since the second and third live calls
    in the same process all answered normally), yet the fact was still
    captured and correctly recalled one turn later -- the episodic write
    fires off the human's own `user_text` regardless of whether Sim's
    own reply that turn was a real answer or the floor, which is exactly
    the resilience the honest-floor design was for. 1982 tests passing
    (2 new regression tests: a real two-sided episodic write is stored
    and retrievable; a turn with nothing said on either side is not
    stored).

106. **`python -m simorgh run` finally launches an actual interactive
    session -- it never had before.** Surfaced by the creator's own next
    question, not a self-directed check: "how do I run v2?" The honest
    answer at that moment would have been "you can't talk to it through
    its own real entry point" -- `simorgh/kernel/registry.py`'s
    `build_factories()` constructed Interface with `run_repl=False`
    unconditionally, a deliberate Phase-0-era choice so a blocking
    `readline` loop could never hang a test or `--self-check` boot (both
    of those also call `build_factories()`), but nothing had ever added
    the other half: a way for `simorgh run`'s own entry point to ask for
    the opposite.

    Added `run_repl: bool = False` as a `build_factories()` parameter and
    `interactive: bool = False` as a `Kernel.__init__` parameter, threaded
    straight through; `simorgh/kernel/cli.py`'s `_cmd_run` is the one
    caller that now passes `interactive=True` -- every other caller
    (`status`, `trace`, `migrate-v1`, every test, self-check) keeps the
    old default, unchanged. Small, mechanical, three files.

    Verified live in the sandboxed repo copy by actually running
    `python -m simorgh run` with piped stdin, not just unit tests: the
    REPL banner appeared, a plain chat line produced a real answer
    ("2 + 2 = 4."), and Ctrl-C (`SIGINT`) cleanly published `system.stop`
    and shut every subsystem down in reverse order, exactly as
    `_cmd_run`'s signal handler was always written to do -- it had just
    never had a live REPL in front of it to prove it against before.

107. **A second bug the same live run surfaced, caught only because the
    REPL was actually running for the first time: two chat messages sent
    close together could cross-wire their replies.** `Interface._handle_
    chat` keyed `self._pending_turns` by `self.session_id` -- the REPL's
    own single, fixed per-instance identity, not a fresh id per turn.
    The real REPL thread never waits for one line's reply before reading
    the next (`_repl_main`'s loop just schedules `_handle_line` and goes
    straight back to `input()`), so a second message sent before the
    first one's `turn.completed` arrived silently overwrote the dict
    entry. Whichever reply happened to land on the bus first then
    resolved the *second* call's future regardless of whose prompt it
    actually answered, and the first call's own future -- now orphaned,
    nothing pointed to it anymore -- sat until `chat_reply_timeout_s`
    expired and printed a false "no response" for a prompt that likely
    did get a real answer, just not the one shown.

    This is exactly the class of bug milestone 104 already named and
    fixed once (a wiring gap invisible to any test that never exercises
    the real seam) showing up a second time in the same subsystem the
    moment a second real capability -- the REPL actually running -- put
    live concurrent traffic through it for the first time.

    Fixed by generating a fresh `uuid.uuid4()` per `_handle_chat` call
    instead of reusing `self.session_id` for the `_pending_turns` key
    (`self.session_id` itself is untouched and still used elsewhere,
    e.g. `dispatch()`'s `session_id=` for `plan`/`batch` commands -- a
    legitimately different, REPL-instance-scoped concern). Regression
    test fires two `_handle_line` calls concurrently against one fake
    responder that replies with distinct, content-tagged text per
    prompt, and asserts both replies land on their own call, with no
    false "no response" -- confirmed this test actually fails against
    the pre-fix code (reproduced by hand: the second reply vanishes,
    replaced by exactly the false timeout message described above)
    before confirming it passes against the fix. 1988 tests passing (1
    new regression test).

108. **Phase 4 begins: the creator chose "proceed" over redirecting the
    wave plan, and the first of four Wave-1 forks landed.** Unlike Phase
    1/3's concurrent forks sharing one working tree (which cost this
    session an unauthorized push and a real module-boundary violation
    that had to be cleaned up after the fact), all four Wave-1 forks run
    in isolated git worktrees this time -- each on its own branch, no
    shared-file collision possible, merged into `main` one at a time as
    each lands rather than trusting social-convention file ownership
    inside one tree.

    First to land: the evaluator-optimizer loop (roadmap item 4.3,
    harness-06 gap #5 -- "Verification is single-pass outcome-only, not
    iterative or trajectory-aware"). The fork correctly found that the
    bounded revise-with-feedback loop itself already existed
    (`SessionRunner._verify_then_finish`, already covered by
    `test_session_flows.py::TestPatchTaskWithOneRevision`) and did not
    rebuild it -- exactly the "read what's already there first" framing
    it was given. What it found instead were two real integration bugs
    between Orchestration and the *real* Verification service, invisible
    to every existing test because `FakeVerification` never reproduced
    either real behavior:

    1. One `verification_id` was minted before the revision loop and
       reused across every retry. The real service's duplicate-request
       rule -- `verify:<id>` already has a verdict -> re-emit it, meant
       for at-least-once redelivery of the *same* request -- treated a
       revision's new `verify.requested` as a redelivery of the first
       and replayed the cached failing verdict forever, so a genuinely
       fixed revision would spin to `max_revisions` and wrongly
       `task.blocked` no matter how good the fix was.
    2. `subject_ref` was sent as raw truncated text, not a blob id. The
       real `VerificationService._resolve_subject` calls
       `ledger.get_blob(subject_ref)` expecting a JSON
       `{description, result, ...}` object -- every other producer's
       shape. Raw text there silently resolved to `subject={}`, so the
       semantic checklist review ran against nothing and lost its
       feedback signal entirely.

    Fixed: a fresh `verification_id` per attempt inside the loop, and a
    new `_put_verify_subject` helper that blobs `{description, result}`
    via `ledger.put_blob` before each `verify.requested`. The fork
    verified its own regression test actually catches the bug (stashed
    the fix, confirmed the test fails/hangs; restored it, confirmed it
    passes) before reporting back -- the same discipline this session
    established for every live-caught fix since milestone 104.

    No `simorgh/contracts/` change was needed -- `subject_ref` was
    already typed as an opaque blob-id string; the bug was purely in
    what Orchestration put there, not the contract's shape. 1986 tests
    passing at merge.

109. **Wave-1's second fork lands: Plan Mode's human-approval gate,
    closing harness-06 gap #1.** Same pattern as milestone 108 -- read
    what's already there before writing anything, and most of it was:
    Planning's plan-mode session mechanics (`planmode.py`, `service.py`),
    the risk-routing approval matrix (`planmode.approval_decision`,
    already exactly "risk >= high -> human, else auto"), Verification's
    plan review (`plan.proposed -> plan.reviewed`, already wired),
    Guardian's plan-mode read-only enforcement, and Interface's
    `ui.prompt` rendering all already existed and worked. The fork
    touched nothing in `simorgh/guardian/`, `simorgh/interface/`, or
    `simorgh/verification/` as a result -- there was nothing missing
    there for this item.

    What was genuinely broken, found by reading `07-planning.md` section
    5.4 against the actual code rather than trusting that a passing test
    suite meant the feature worked end to end (the same lesson as every
    milestone since 104):

    1. **`risk` was unreachable above "medium" through any real
       message.** `task.create.v1.json` already had an optional `risk`
       field, but `Intake.on_goal_stated`/`on_candidate` silently
       dropped it, hardcoding "medium" for every project and "low" for
       everything else -- so the entire "risk >= high -> human approval"
       branch was dead code in the *built* system, reachable only by a
       test that constructed a `Task` directly. Fixed: both intake
       methods now accept and honor an optional `risk` override, and
       `service.py`'s `_on_task_create` passes `payload["risk"]` through.
    2. **No timeout on an unanswered human-approval prompt** -- a
       project could hang forever waiting for a human who never answers.
       Added a pure `is_human_approval_timed_out` predicate and a
       `system.tick.second`-driven check that pauses the project with a
       reason once `human_approval_timeout_seconds` elapses.
    3. **A lease-expiry race**: the plan-mode task's short exploration
       lease could expire mid-review, and `TaskStore.expire_lease` flips
       status straight to `available` (bypassing the transition table),
       letting a second Worker reclaim and re-run plan mode mid-decision.
       Fixed by extending the lease to `human_approval_timeout_seconds`
       once the plan enters review.
    4. Guarded `_on_plan_reviewed`/`_on_prompt_answered` so a late human
       answer arriving after a timeout-driven pause no-ops instead of
       attempting an illegal `PAUSED -> COMPLETED` transition.

    The new integration test boots a real Kernel with real Planning +
    Verification and proves, end to end: low-risk auto-approves with no
    `ui.prompt` ever sent; high-risk creates zero children until a
    genuine external `ui.prompt.answered` arrives; a human "no" fails
    the project with no children; an unanswered high-risk prompt pauses
    rather than hanging forever. No `simorgh/contracts/` change needed --
    `task.create.v1.json` already had the `risk` field; the gap was
    entirely in Planning never reading it. 2003 tests passing at merge.

110. **Wave-1's third fork lands: skill acquisition as procedural
    memory (roadmap item 4.7).** Read-first again: `learn.skill.
    acquired` and its `PatchPipeline` publish already existed from Phase
    3, `tool.registered` already anticipated `provider: "skill"`, and
    Memory's `procedural` kind was already fully generic (store,
    retrieve, decay, tags) -- just never actually written to for a
    skill. What was genuinely missing: Execution had no way to *run* a
    skill at all (`execution/README.md` said so outright) and nothing
    made a skill discoverable by its own description.

    Built: a `memory.store{kind: procedural}` publish alongside
    `learn.skill.acquired` so a skill's description becomes a real,
    retrievable record, not just an event; two new Execution tools --
    `ApplySkillTool` (writes a skill's source under a scope-checked
    `simorgh_skills/`) and `SkillTool` (`skill:<name>`, runs the skill's
    own source in the same sandboxed subprocess `run_python_sandboxed`
    already uses); and on-demand registration in
    `simorgh.execution.service`, two ways -- eagerly on `learn.skill.
    acquired` for a skill acquired in this process, and lazily in `_on_
    approved` the first time an approved action names an unregistered
    `skill:<name>`, reconstructing its path from the `skill_dir/<name>.py`
    convention, covering a skill acquired in a *prior* process. Neither
    path is a directory scan at boot -- "loaded on demand" means exactly
    that.

    The fork flagged rather than made one contracts change: `05-memory.
    md`'s own dependency table already describes `learn.skill.acquired`
    as producing `{name, description, path, tests}` directly, but the
    real schema was `{name, path, tests}` -- no `description`. Rather
    than editing `simorgh/contracts/` itself (every Wave-1 fork was
    asked not to, to avoid concurrent contract edits across four
    parallel worktrees), it worked around the gap with the separate
    `memory.store` publish and reported the exact field to add. Applied
    here at integration: `description` added as an *optional* `Str`
    field on `LearnSkillAcquired` (schema regenerated via `python -m
    simorgh.contracts.schemagen`), and `PatchPipeline`'s publish now
    sets it -- the event itself is self-describing for a future direct
    consumer, while the `memory.store` publish remains what actually
    makes the skill durable and retrievable (an event on the bus is not
    persisted state).

    New integration test boots a real Kernel with real Guardian +
    Execution + Memory, proving discoverability-by-description and both
    the eager and lazy on-demand-loading paths through a real Guardian
    approval, not a mock. Learning/execution/contracts suites
    individually reconfirmed first (37, 48, and 77 tests respectively,
    all passing, 123 schemas back in sync); full suite green at merge,
    2018 tests.

111. **Wave-1's fourth and final fork lands: context-compaction layers
    3-5, closing harness-06 gap #2 ("No context-compaction pipeline in
    any tool loop") by name.** Layers 1-2 (budget reduction, snip)
    already existed; this fork built the rest of `04-cognition.md`'s own
    pipeline spec on top: layer 3 (microcompact / reference
    substitution -- dedupe identical tool results, strip whitespace
    runs, shrink long previews), layer 4 (read-time collapse -- older
    transcript segments become one-line headlines while the newest stay
    full, the *stored* messages never mutated, only what's assembled for
    a given call), layer 5 (auto-compact via an injected `summarize`
    callable as the genuine last resort, emitting `cognition.compact.
    pre`/`.done` and recording the summary), and persistent-instruction
    protection (`protected: true` or `role: "system"`) honored by every
    layer above it -- proven with a property test that protected blocks
    survive compaction byte-identical.

    Two real bugs surfaced and fixed along the way, not just new layers
    bolted on: compaction was running on the assembler's already-
    flattened "conversation" block rather than the caller's raw
    messages, silently defeating layer 1 in production even though its
    own unit tests passed against raw input directly; and `compact.
    request`'s `allow_summarize` field was hardcoded to `False`,
    permanently disabling layer 5 regardless of what a caller asked for.

    Per-call budget accounting (the other half of this roadmap item):
    `RollingWindowBudget.estimate_cost()` gives a pre-call cost
    projection, and `Router.complete()` now skips any candidate priced
    over the request's own `max_cost_usd`, raising a new
    `BudgetExceeded` when every real candidate is priced out and the
    caller required a real provider -- rather than silently either
    overspending or floor-degrading for a reason the caller can't see.

    No `simorgh/contracts/` change needed -- every field used
    (`allow_summarize`, `summary_ref`, the extra `budget`/`purpose`
    fields, the `cognition.compact.pre`/`.done` topics) was already
    present or already permitted via `additionalProperties: true`.
    129 cognition-package tests, 8 new integration tests naming harness-
    06 gap #2 in their docstrings, full suite green at merge: 2059 tests.

    **Wave 1 complete.** All four independent Phase-4 items (Plan Mode,
    evaluator-optimizer, skill acquisition, compaction) built in
    isolated git worktrees -- zero shared-file collisions, zero
    unauthorized pushes, a clean merge for every one of the four,
    unlike Phase 1/3's concurrent-forks-in-one-tree approach that cost
    real cleanup work twice. Three of the four forks found that the
    session-mechanics for their assigned item were already substantially
    built, and the real gap was narrower and more specific than the
    roadmap's one-line description suggested -- reading the actual code
    against the actual spec before writing anything, every time, is what
    made that distinction possible instead of duplicating existing work.

112. **A live-status dashboard, built while Wave 2 ran in the
    background.** The creator's own framing: this was to be their first
    real experience working with v2, and they wanted to actually *see*
    it -- which subsystems are loaded, their state, bus queue depth and
    throughput, what each Orchestration worker is doing -- in real time,
    not infer it from REPL scrollback. Asked directly (not assumed):
    terminal panel or a local web dashboard, and whether to start now
    alongside Wave 2 or wait. Chose the web dashboard deliberately over
    resurrecting v1's terminal vitals panel, which this same project's
    memory records as having corrupted the creator's actual terminal via
    a readline/DECSTBM conflict (milestone 94's revert) -- a local HTTP
    page never touches the TTY at all, sidestepping that whole class of
    bug rather than trying to avoid it more carefully a second time.

    Most of the backend signal already existed and just wasn't reaching
    anywhere a human could see it: `StatusServer.snapshot()` (`simorgh/
    kernel/metrics.py`) already answered `system.status.request` with
    run id/mode/state/uptime and a bare `{name, status}` per subsystem,
    and the Bus already published real `system.metrics` gauges (queue
    depth, inflight, request latency) every 15s -- but each subsystem's
    own rich `health()` detail string ("6 tools registered", "posture=
    guarded", "0/1 worker(s) busy") was computed and then discarded by
    `_on_health`'s own comment: "the supervisor's own poll is the source
    of truth ... this just keeps the table warm." Added `detail`,
    `restarts`, and a `layer` (from `registry.LAYERS`, so a dashboard
    groups by boot order without duplicating that table) to every
    subsystem entry in the snapshot -- three fields, all already
    computed, just never carried through.

    Orchestration had no live worker visibility at all -- "what is each
    forked agent process doing" was one of the creator's explicit asks,
    and there wasn't an answer. `Worker` gained `current_task_id`/
    `current_kind`, set for the duration of `run()` (covering both the
    real `task.available` claim path and the ephemeral `run_percept_
    chat` path from milestone 104) and cleared in a `finally`; `Service`
    gained a periodic (`Config.metrics_interval_s`, default 3s)
    `system.metrics` publish carrying a `workers.busy`/`workers.total`
    gauge pair plus a structured `workers` list -- `{worker_id, task_id,
    kind}` per worker. No contracts change needed: `system.metrics`'s
    own schema already permits any value in a gauge (`additionalProperties:
    {}`, no numeric-only constraint), so a list of objects validates as
    cleanly as a float.

    `simorgh/interface/httpapi.py`: a hand-rolled, stdlib-only HTTP/1.1
    server over `asyncio.start_server` -- GET-only, `Connection: close`
    on every response, no third-party dependency (04's own "no new
    third-party dependency in the core" rule ruled out reaching for
    `aiohttp`). Two routes: `/` serves a self-contained dashboard page
    (no external requests of any kind -- system fonts only, everything
    inlined, so it works fully offline), `/api/status` proxies a real
    `system.status.request`/`.reply` round-trip over the live bus as
    JSON -- the exact same call `python -m simorgh status` already made,
    just reachable from a browser instead of a separate throwaway
    Kernel boot (worth noting for whoever touches that CLI command
    next: it boots a *fresh* Kernel just to read its own empty snapshot,
    so it was never actually querying a `simorgh run` process running
    elsewhere in `single` mode -- this dashboard, running inside
    Interface in the *same* process as the live Kernel, is the first
    place in the codebase that actually can).

    `InterfaceService` gained `http_enabled`, defaulting to follow
    `run_repl` (the dashboard is for a human watching an interactive
    session, so it comes up exactly when the REPL does, off for every
    headless boot -- tests, `--self-check`, `status`, `trace` -- unless
    a caller explicitly overrides it either way), printing its URL to
    stdout on boot.

    Verified live in the sandboxed repo copy, not just via unit tests:
    booted `python -m simorgh run` with the dashboard enabled, loaded it
    in a real browser, and watched it update in place -- subsystem cards
    color-coded by status and grouped by layer with each one's own real
    detail string, live bus counters, an idle worker row -- confirmed
    the auto-refresh was genuinely live by comparing two screenshots a
    few seconds apart (`counter.published` 72 -> 100, uptime ticking).
    2073 tests passing (new suites: `test_httpapi.py` over real sockets
    and real HTTP/1.1 requests via `http.client`, not mocked reader/
    writer objects, plus worker-busy-tracking and metrics-publish tests
    in orchestration, plus the snapshot's three new fields in kernel).

113. **Two pieces of the creator's own long-range direction for Sim,
    captured in `02-system-architecture.md` §6.1/§6.2 and cross-referenced
    from `04-build-plan-and-roadmap.md`'s Phase 5, specifically so they
    survive to whichever session reviews the roadmap next** (the creator
    named Fable 5.1 for that review, planned for after cutover) rather
    than living only in this conversation's own history:

    First: Sim's intended end state is not a CLI a person invokes, it's
    a daemon that stays alive continuously, with many independent
    *sessions* -- through the CLI, a web interface, a plain HTTP/
    WebSocket API -- all talking to the one running Kernel underneath.
    `single` mode's Kernel already runs this way in embryo; the real gap
    is narrower than a redesign: Interface hardcodes one `session_id`
    per process today, while the message contracts underneath it
    (`percept.text.received`, `turn.completed`, Memory's own episodic
    writes since milestone 105) already correlate by an arbitrary
    string, not anything process-scoped -- generalizing Interface to a
    registry of concurrent sessions is additive to what's there, not a
    rebuild of it.

    Second, offered immediately after seeing milestone 112's dashboard
    run live: an admin plane on top of it, explicitly observe-first-
    control-second, explicitly with authentication deferred to a later
    pass ("for beginning, the authentication can be ignored"). Observe:
    logs (already Ledger events, per section 7 below -- needs a query UI,
    not new capture), metrics *history* (not just the live snapshot
    milestone 112 shipped -- the trace stream already durably records
    every `system.metrics` event, so this is a query/aggregation layer
    over data already being written, not new instrumentation), LLM usage
    (explicitly flagged by the creator as postponable if it's a lot of
    work -- Cognition's `RollingWindowBudget`, milestone 111, already
    estimates this in memory; what's missing is persistence across
    restarts), and real OS-level resource usage (memory/CPU -- genuinely
    untracked anywhere today, not just unsurfaced). Control, explicitly
    deferred: live-adjustable timeouts, skill enable/disable, memory
    limits, max concurrent workers -- none of `simorgh.toml` is runtime-
    mutable today, every subsystem reads its `Config` once at
    construction. One constraint written down for whoever designs this,
    not just a feature list to build: an admin control action is still
    an action with real consequences, and `01-vision-and-principles.md`'s
    own structural-safety principle (4.3) exists precisely so nothing
    bypasses the guarded `action.proposed -> guardian -> action.approved
    -> execution` path -- worth deciding deliberately whether admin
    actions are another category of guarded action or a genuinely
    separate privileged path, rather than defaulting into the latter by
    never asking the question.

114. **Two of §6.2's observe-tier items answered directly, same
    session: LLM usage and "what does Sim remember," both reusing
    signal that already existed rather than adding new instrumentation.**
    Cognition already published `cognition.provider.status` every ~30s
    from its own `RollingWindowBudget`; that same status now also folds
    into a `system.metrics{subsystem: "cognition"}` publish (a
    `providers` gauge -- name/calls/max_calls/spend/exhausted per
    provider) on the identical throttle, reaching the dashboard's single
    aggregated snapshot the way every other subsystem's gauges already
    do. Memory gained a genuinely new capability, `MemoryEngine.
    counts()` -- a live (non-tombstoned) record count per durable kind,
    published the same way every 30s. Both new dashboard panels
    (`simorgh/interface/static/dashboard.html`) verified live against a
    real autonomous run, not synthetic data: while the sandboxed repo
    copy booted, Curiosity/Planning had already started a real research
    task, and the dashboard showed the actual resulting spend
    (`claude_code_cli`: 2 calls, $0.0597) and provider availability a
    few seconds later, exactly as it should.

    `dash.sh` added at the repo root, at the creator's own request: a
    small script that checks the dashboard is actually reachable (curl,
    2s timeout) before opening it in Chrome, rather than opening a dead
    tab and leaving the creator to guess why -- `simorgh run` must
    already be up, this script only points a browser at it. Notes its
    own real limitation: the port isn't wired to `simorgh.toml`/env
    overrides yet (`InterfaceConfig` has no `from_mapping`, unlike every
    other subsystem's own `Config` class), so it's the `InterfaceConfig`
    default unless a full URL is passed as an argument.

    Asked directly whether to fork a session to build more of §6.2's
    observe tier (metrics history, a logs view, real OS-level resource
    usage) in parallel with Wave 2 (still running at this point, on
    `reflection`/`planning`/`guardian`/`worldmodel` -- zero file overlap
    with the interface/kernel work this needs) -- launched as a second
    isolated-worktree fork, explicitly scoped to the observe tier only
    and explicitly forbidden from building any part of the control tier
    (config knobs, skill enable/disable, auth), which stays deferred
    exactly as section 6.2 already says, pending the deliberate
    Guardian-integration design decision recorded there. 2077 tests
    passing at this point in the session.

115. **Wave 2 lands: re-grounding + drift detection, trust posture, and
    Self Model completeness -- all three built as one combined thread
    (a single fork, not three parallel ones) specifically because all
    three touch `simorgh/reflection/`, which would have collided.**
    Same pattern as every Phase 4 item before it: the session-mechanics
    existed; the real gap was a specific, narrow wiring failure, found
    by reading the actual code against the actual spec first.

    **Re-grounding + drift (harness-06 gap #3):** `simorgh/planning/
    reground.py` was fully written and completely dead -- `needs_check`/
    `check` were never called from anywhere, `store.record_regrounded`
    was never invoked, and `reflect.drift.detected` wasn't even in
    Planning's `consumes` tuple, so a real drift signal from Reflection
    had nowhere to land. Fixed: every dependent's PENDING -> AVAILABLE
    transition now routes through a real re-grounding check (stale age,
    a failed sibling, or a drift flag), a "no" verdict supersedes the
    child with a replacement task and emits `plan.revised`, and a new
    handler reacts to `reflect.drift.detected` directly. Two real bugs
    found and fixed along the way: PENDING has no legal direct
    transition to FAILED in the state table (routed through BLOCKED
    instead), and a replacement task's `origin="planner"` isn't in the
    wire contract's `TASK_ORIGIN` enum (fixed to the enum's actual
    `"project"`).

    **Trust posture:** only 1 of `09-guardian.md` section 5.3's 4
    tightening triggers was wired (failure streak). `reflect.drift.
    detected`, `reflect.health.finding`, and `cognition.provider.status`
    weren't even in Guardian's `consumes`, and -- a second, independent
    bug hiding behind the first -- `self._budgets` (which `rules.
    BudgetRule` reads to deny on real spend pressure) was permanently
    empty, so `BudgetRule` silently abstained on every single proposal
    regardless of actual budget state. Fixed: all four triggers wired,
    plus `system.resume` as the one human-only loosening path section
    5.3 allows; a new `_fraction_used` helper converts `cognition.
    provider.status`'s budget object into what `BudgetRule` needs,
    fixing the dead rule as a direct side effect of wiring the trigger
    that was supposed to feed it all along.

    **Self Model completeness:** `worldmodel/selfmodel.py`'s own
    docstring admitted every section but identity was a permanent
    placeholder "because their real producers... don't exist yet" -- but
    by this point in the session they do. `Service.consumes` never
    listened to `learn.competence.updated`, `reflect.calibration.
    updated`, `self.observation`, `learn.self_patch.applied/reverted`,
    or `learn.skill.acquired` at all. `SELF.md` was rendered once at
    boot and never touched again for the rest of a run. Fixed: real
    mutators for competence/calibration/limitations/change-history/
    skills/restarts, wired through a new `_apply()` that bumps the
    Self Model's version, re-renders a real `SELF.md`, and publishes
    `self.model.updated`; Reflection now also emits `self.observation
    {kind: limitation}` per mined pattern -- the enum already allowed
    it, nothing had ever produced it. Left honestly incomplete rather
    than faked: `open_questions` stays empty, because nothing publishes
    a wire event carrying one yet -- the fork flagged this instead of
    inventing a producer, and reported exactly what contracts change
    would unblock it.

    Applied at integration: `open_question` added as an optional new
    value to `SelfObservation`'s `kind` enum (`simorgh/contracts/
    messages/self_.py`, schema regenerated) -- purely additive, so a
    future producer doesn't also need its own contracts change, but no
    producer added here; `open_questions` remains genuinely empty until
    one exists. 2105 tests passing on the fork's own branch before
    merge; full suite reconfirmed green after the contracts addition at
    integration.
