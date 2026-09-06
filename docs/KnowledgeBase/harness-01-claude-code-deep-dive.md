# Claude Code's Harness, In Detail

Sources: [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works), [Sub-agents](https://code.claude.com/docs/en/sub-agents), and the independent academic analysis [Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems](https://arxiv.org/abs/2604.14228) (Liu, Zhao, Shang, Shen), which reverse-engineered the harness from its own source and derived the values/principles framework below.

## The core loop is deliberately small

Underneath everything, Claude Code is "a simple while-loop that calls the model, runs tools, and repeats" (the arXiv paper's own phrase). The official docs frame the same loop as three blended phases — **gather context, take action, verify results** — that repeat until the model produces a text-only response with no further tool calls. A typical task runs 5–50 iterations of this loop. The important design fact is that *almost none of the harness's real complexity lives in the loop itself*. It lives in the systems wrapped around it: permissions, context management, checkpoints, subagents, and the extensibility layer. This is the first lesson worth internalizing before anything else: a minimal core loop plus a rich, separately-engineered operational harness beats a complicated core loop every time, because the operational systems can be tested, versioned, and reasoned about independently of the model's own behavior.

## Five human needs, thirteen design principles

The arXiv analysis's most useful contribution is tracing *why* the harness looks the way it does, not just *what* it does. It identifies five human values/needs the architecture exists to serve:

1. **Human decision authority** — the human retains ultimate authority over what the system does, organized through a principal hierarchy (Anthropic → operators → users). Concretely: real-time observability of actions, the ability to approve/reject/interrupt, and after-the-fact audit.
2. **Safety, security, and privacy** — the system protects the human's code, data, and infrastructure *even when the human is inattentive or makes mistakes*. This is deliberately a different property from decision authority: it's the system's own obligation, not something contingent on the human paying attention. Four risk categories are named explicitly: overeager behavior, honest mistakes, prompt injection, and model misalignment.
3. **Reliable execution** — the agent does what the human actually meant, stays coherent over time, and supports verifying its own work before declaring success, across single turns *and* long horizons (session resumption, multi-agent delegation).
4. **Capability amplification** — the system materially increases what the human can accomplish per unit of effort. (Anthropic's own internal survey found ~27% of tasks people used Claude Code for were work they wouldn't have attempted at all otherwise — a qualitatively new workflow, not just a faster old one.)
5. **Contextual adaptability** — the system fits the specific project, tools, conventions, and skill level of the person using it, and that fit *improves over time*. (Longitudinal data: auto-approve rates rise from ~20% in a user's first 50 sessions to over 40% by 750 sessions — trust is built, not assumed.)

From these five needs, the paper derives thirteen concrete design principles. The ones most worth internalizing for any harness design:

- **Deny-first with human escalation** — an unrecognized action is escalated to a human, never silently allowed by default.
- **Graduated trust spectrum** — permission posture is not a single fixed level; it's a spectrum a user (or an autonomous system) traverses as trust is earned, matching need 5 above directly.
- **Defense in depth** — multiple overlapping safety boundaries using *different* techniques (a denylist, an ML classifier, a sandboxed run, a test suite), so one mechanism's blind spot isn't the whole system's blind spot.
- **Externalized programmable policy** — policy lives in configuration with lifecycle hooks, not hardcoded into the harness's own logic. Non-technical operators can change behavior without a code change.
- **Context as a scarce resource with progressive management** — treated as a real, binding constraint managed through a graduated pipeline (see the compaction section below), not a single blunt truncation when the limit is hit.
- **Append-only durable state** — logs, not mutable state or ad hoc checkpoint snapshots. (Sim's own `MemoryStore`/`TaskStore` event-sourcing is already exactly this principle, arrived at independently.)
- **Minimal scaffolding, maximal operational harness** — invest in the operational infrastructure (permissions, compaction, checkpoints), not in scaffolding-side prompt engineering trying to get the model to behave a certain way through instructions alone.
- **Values over rules** — contextual judgment backed by deterministic guardrails, rather than an attempt to enumerate every rule in advance (which always has gaps).
- **Composable multi-mechanism extensibility** — skills, MCP, hooks, and subagents are layered mechanisms at *different context costs*, not one unified API — because different extension types have genuinely different cost/isolation tradeoffs (see file 05).
- **Reversibility-weighted risk assessment** — lighter oversight for actions that are reversible or read-only; heavier oversight scales with how hard an action is to undo.
- **Transparent, file-based configuration and memory** — CLAUDE.md and settings files are user-visible, version-controllable text, not an opaque database the user can't inspect or diff.
- **Isolated subagent boundaries** — a subagent does not inherit the parent's full context and permissions by default; isolation is the default, not an opt-in.
- **Graceful recovery and resilience** — silent recovery from the routine failure modes, reserving human attention specifically for the unrecoverable ones. (Sim's own `CognitionRouter` fallback chain, and `AutonomyController`'s failure-streak circuit breaker, are instances of this same principle.)

## The agentic loop's three phases, concretely

- **Gather context**: search files, read code, run read-only commands, check git state, pull in CLAUDE.md and auto-memory. A pure question might only need this phase.
- **Take action**: edit files, run commands, call tools. A bug fix cycles through gather→act→verify repeatedly, often several times, adjusting based on what each step revealed.
- **Verify results**: run tests, re-read the changed file, check the diff. A refactor might spend a disproportionate share of its total steps here.

The model decides, at each step, which phase it's effectively in based on what the *previous* step returned — there's no hardcoded phase machine forcing a fixed sequence. This is deliberate: hardcoding the sequence would make the harness a workflow (predictable, but brittle against the genuinely open-ended tasks Claude Code is meant for); leaving it to the model's own judgment, backed by a strong verification culture and cheap-to-run tools, is what lets a single loop shape handle everything from "what does this function do" to "refactor this module."

## Context management: the five-layer compaction pipeline

Context is treated as the single most binding scarce resource in the whole system, and it's managed through a graduated pipeline of five shapers that run, in order, before every model call:

1. **Budget reduction** — enforces a per-message size cap on tool results specifically, replacing an oversized result with a content reference rather than dropping it outright (a small number of tools are exempted because their full output is load-bearing). This is the cheapest, least-destructive intervention, so it runs first.
2. **Snip** — a lightweight trim removing older history *segments* wholesale, reporting back how many messages/tokens it freed.
3. **Microcompact** — fine-grained compression; a time-based path always runs, with an optional cache-aware path that can use the API's actual reported `cache_deleted_input_tokens` rather than an estimate, when available.
4. **Context collapse** — the most architecturally interesting layer: it never mutates the stored history at all. It's a *read-time projection* — the model is shown a collapsed view of the conversation, but the underlying full history is untouched and can still be reconstructed. This means a resumed session, or a later `/compact`, isn't working from already-lossy data.
5. **Auto-compact** — the expensive, last-resort layer: a full model-generated summary, triggered only once the previous four have already run and context pressure is still over threshold. It fires `PreCompact` hooks (so extensions can react) and uses a dedicated compact-prompt template, not the ordinary system prompt.

The ordering is the whole design: cheap, non-destructive, reversible interventions are tried first; expensive, lossy, model-generated summarization is the last resort, not the first response to running low on space. A harness that only implements step 5 (summarize when full) is missing four cheaper, safer opportunities to buy room first.

## The permission system: seven modes, plus an ML classifier

Seven distinct modes exist, not a binary allow/deny: `plan` (explore and propose only, no execution), `default` (most operations need approval), `acceptEdits` (in-directory edits and common filesystem commands auto-approved, everything else still asks), `auto` (an ML classifier evaluates anything that doesn't pass a fast static allow/deny path), `dontAsk` (no prompting, but explicit deny rules still bind), `bypassPermissions` (skips most prompts, but *safety-critical checks and bypass-immune rules still apply* — there is no true "no rules at all" mode), and `bubble` (an internal-only mode letting a subagent escalate a permission question up to the parent's own terminal rather than deciding on its own).

The `auto` mode's classifier is a real, separate model call: it loads a base system prompt plus a permissions template (and, for a subset of users, an internal template), evaluates the proposed tool call against the conversation transcript and that template, and returns allow / deny / request-manual-approval. A related speculative classifier for shell commands races a pre-started classification against a timeout, so a high-confidence approval can return before the user would even notice a pause. Crucially, **deny always wins over allow, regardless of specificity** — a broad "deny all shell commands" rule cannot be overridden by a narrower "allow `npm test`" rule. This is the deny-first principle made concrete: ambiguity resolves toward safety, never toward permissiveness.

## Subagents: isolation is the point, forking is the exception

A subagent is a named, isolated instance with its own system prompt, context window, tool-access list, and permission mode — defined as a markdown file with YAML frontmatter (`name`, `description`, `tools`, `model`, `permissionMode`, `maxTurns`, `skills`, `memory`, `isolation`), stored project-scoped (`.claude/agents/`), user-scoped (`~/.claude/agents/`), or passed via CLI/settings.

Two distinct shapes:

- **Fresh** (the default): starts with an isolated context — its own system prompt, the delegation message, CLAUDE.md, preloaded skills, and a git-status snapshot. Nothing from the parent's conversation carries over. Cheapest in context, but the subagent has to be told everything it needs to know; nothing is assumed.
- **Fork**: inherits the *entire* parent conversation — same system prompt, tools, model, and full message history. It runs in the background; its own tool calls stay isolated from the parent, but it starts already knowing everything the parent knows, so there's no re-explanation cost. Useful specifically when a side task genuinely needs the accumulated context, or when trying several parallel approaches from the same starting point.

Either way, the boundary that matters is the same: **the subagent's intermediate tool calls never reach the parent's context — only its final summary does.** This is the mechanism, not a side effect: it's what lets a subagent search a codebase ten different ways, or grind through a noisy log, without any of that noise ever touching the orchestrating conversation's own token budget. Multiple subagents can run concurrently (default cap: 20), and subagents can themselves spawn subagents up to a bounded depth (default 3) before the delegation tool is withheld — an explicit ceiling against unbounded recursive delegation.

Design guidance the docs give directly: use the main conversation when a task needs frequent back-and-forth or shares heavy context across phases (plan → implement → test); use a subagent when the task produces verbose output that would bloat the main session, needs its own tool restrictions, or is genuinely self-contained; use a fork specifically when a side task needs the existing context and re-explaining would be wasteful.

## Checkpoints: reversibility as a first-class mechanism, separate from git

Before Claude Code edits a file, it snapshots the current contents. This is deliberately **not** git — it's a separate, always-on mechanism that works even mid-session, before anything would be committed, and survives a resumed conversation. Two presses of Escape rewind to the previous state. The scope is explicit and honest about its limits: checkpoints cover file changes only; anything with an external side effect (a database write, an API call, a deployment) *cannot* be checkpointed, and the system doesn't pretend otherwise — that class of risk is handled by the permission system instead, not by a fake "undo" that can't actually undo it.

## Plan Mode: a hard constraint, not a suggestion

Plan Mode is one of the seven permission modes, but it deserves its own callout because of what it demonstrates architecturally: it is an *enforced* read-only state, not an instruction the model is merely asked to follow. In Plan Mode, only read/search tools are available (Read, LS, Glob, Grep, WebSearch, WebFetch, plus the task-list tools) — Edit/Write/Bash are structurally unavailable, not just discouraged. The model explores, proposes a full plan, and only after explicit human approval does execution begin, at which point the harness switches to a different, execution-capable mode. The lesson: "ask the model to think first" is advisory and gets overridden under pressure; a genuinely separate mode with a genuinely different tool set is a harness-level guarantee that can't be talked around.

## Task planning: from TodoWrite to Task

The original mechanism was `TodoWrite` — an in-session, ephemeral task list the model updates as it works, giving the user live visibility into multi-step progress. As of a later version, this was superseded by a `Task` system with disk persistence, dependency tracking between tasks, and cross-session collaboration — i.e., the planning layer itself evolved from "visible scratch state for one session" toward "a durable, queryable backlog," which is precisely the direction Sim's own `TaskStore` already took independently (see file 06).

## Extensibility as a layered, not unified, system

Skills, MCP, hooks, and subagents are deliberately *not* one API with different flags — they're separate mechanisms because they have genuinely different context-cost and isolation profiles. Skills load on demand: only their short description sits in context at session start, and the full body only loads when actually invoked (and can be marked to never even auto-invoke, staying fully out of context until explicitly named). MCP tool definitions are similarly deferred by default, discoverable via tool-search rather than all being loaded up front. Hooks are lifecycle-triggered automation (e.g. `PreCompact`) that runs deterministic code around the loop, not more model reasoning. The unifying idea: match each extension mechanism's cost to how often it's actually needed, rather than paying full context cost for every capability on every turn regardless of use.
