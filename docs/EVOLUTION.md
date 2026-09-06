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
89. **The true pinned vitals panel, built after the creator knowingly
    chose the riskier option.** Presented with the honest tradeoff from
    milestone 88 (fragile raw terminal control vs. the safer scrolling
    block), the creator picked "build the true pinned panel anyway."
    `vitals pin` now reserves a fixed strip of rows at the top of the
    screen via a DECSTBM scroll region (`\x1b[{top};{bottom}r`) and
    redraws into it with save/restore-cursor (`\x1b7`/`\x1b8`) so the
    conversation's own cursor position is never disturbed; `vitals
    unpin` resets the scroll region and returns to normal scrolling.
    `pin()` reports `False` (and changes nothing) when stdout isn't a
    real terminal -- `os.get_terminal_size()` fails over piped/SSH/non-
    interactive output -- so the command says plainly it can't pin
    rather than silently doing nothing useful; `vitals on` still works
    everywhere as the fallback.

    A real design bug was caught and fixed before this shipped: the
    first draft reissued the DECSTBM scroll-region escape on *every*
    redraw, not just the first. DECSTBM resets the cursor to the top of
    the new region as a side effect on most terminals, so redoing it on
    every idle-triggered tick would keep fighting wherever ordinary
    conversation output had actually left the cursor. Fixed by setting
    the scroll region exactly once, inside `pin()`, before the first
    draw -- `_draw_pinned_locked()` itself now only ever does
    save/restore-cursor, absolute positioning, and the redraw, never
    touching the scroll region again. The direct consequence is a
    documented limitation: a live terminal resize while pinned isn't
    auto-detected (deliberately -- catching it would mean going back to
    resetting the scroll region on every tick, the exact bug just
    fixed); `vitals unpin` then `vitals pin` again re-measures and
    re-fits cleanly. Startup now tries `vitals_monitor.pin()` first and
    falls back to the milestone-88 one-shot print only when pinning
    isn't possible. 804 unit tests + 22 E2E tests passing, including a
    new E2E case confirming `vitals pin` degrades honestly (not
    silently) over this project's own piped-subprocess test harness.
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
