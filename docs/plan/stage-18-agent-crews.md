# Stage 18 -- Agent crews: autonomous sub-agents that run together and talk to each other

Status: **in progress** (2026-10-27: plan written; build starts once stage 16's orchestration branch is merged) · Depends on: stage 7 (the `Task` built-in, waits, projects), stage 16 (guardrails in the loop), stage 14 (evals runner) · Modules touched: contracts, orchestration (owner), interface, evals; `agents/`; `docs/`

## Outcome

Any Sim agent, including chat and voice, can start other agents as **autonomous workers**. Several run at once. Each works on its own task with its own tools and budget, and reports back in the way the parent asked: at the end, periodically, at milestones, or when it needs a decision. Parent and children, and siblings in the same crew, exchange **typed messages** in-process over the Bus, durable on the ledger. So a crew survives a restart, every exchange is auditable, and Guardian still gates every tool call any member makes.

```
spawn{agent:"research", brief:"price of dishwasher A", report:"end"}          -> h1
spawn{agent:"research", brief:"price of dishwasher B", report:"end"}          -> h2
spawn{agent:"browser",  brief:"check delivery dates", report:"milestones"}    -> h3
await_agents{handles:[h1,h2,h3], mode:"all", timeout_s:180}                    -> three typed reports
```

## What exists (stage 7) and what is missing

| Exists | Missing |
|---|---|
| `delegate`/`task{agent, brief, isolation: fresh\|fork, budget}`, a child `Session` in-process on its own `task:<id>` stream, depth ≤ 3 (`session.py::_delegate`) | **Concurrency.** `_batchable()` excludes `delegate`, so helpers run one at a time and `max_children_concurrent` is never reached |
| Only the report comes back, and Guardian gates the child's tools | **Non-blocking spawn.** The parent cannot keep working while children run |
| `wait` on events; projects awaiting children by `task.completed` (stage 7 items 4-5) | **Communication.** No progress reports, no child→parent question, no parent→child steering, no sibling sharing |
| -- | **Chat and voice cannot delegate** (`session.py:1588` offers it to `patch`/`research` only) |
| -- | **A typed report.** The child's free text is what comes back |
| -- | **A crew-wide budget.** Each child has a step cap, but nothing bounds the crew's dollars or wall-clock |

## Definitions (shared by every item; do not rename)

**Crew.** The tree of agents under one root session. It has `crew_id` (the root's task or session id) and members `{handle, agent, parent, depth, status, budget, report_policy, isolation}`. `handle` is the child's task id, and `status` is one of `starting | running | waiting | done | failed | blocked | cancelled`. The crew is recorded on the ledger stream `crew:<crew_id>`, one event per change, never edited.

**Topics** (contracts; schemas in `contracts/messages/crew.py`):
- `crew.spawned{crew_id, handle, parent, agent, brief_ref, report_policy, budget}`
- `crew.message{crew_id, from, to, kind, body, refs, reply_to, seq}`, where `kind` is one of `progress | milestone | question | answer | steer | note | report`
- `crew.report{crew_id, handle, report}`, the final typed report
- `crew.cancel{crew_id, handle, reason, cascade}`

Every topic has a producer and a consumer (the "both sides" contract test). The interface consumes all four for the tree view.

**Report**:
- `status`: `ok | partial | failed | blocked | cancelled`
- `summary`: ≤ 1,200 characters
- `findings`: up to 20 items of `{claim, evidence_ref}`
- `artifacts`: blob or path refs
- `steps`, `tokens`, `cost_usd`, `wall_s`
- `questions_unanswered`

Anything long is a ledger blob ref, never inline. The parent reads it with `read_ref{ref}` only if it needs to. This is the main efficiency rule: **messages carry conclusions and references, not transcripts.**

**Report policy** (`report` on spawn):
- `end` (default): only the final report;
- `progress`: also every `report_progress` the child sends;
- `every_steps:N`: an automatic one-line progress line every N steps;
- `every_s:T`: the same, every T seconds of wall-clock;
- `milestones`: only progress the child marks as a milestone;
- `silent`: nothing until the parent asks with `check_agents`.

A `question` always goes to the parent whatever the policy.

**Tools** (session-local built-ins, like `delegate` and `memory_search`: they coordinate, never touch the world, so they are not proposed to Guardian; everything a member does *in* the world still is):

| Tool | Who | Does |
|---|---|---|
| `spawn{agent, brief, isolation, budget, report, background}` | any agent allowed to (below) | starts a member and returns its handle at once |
| `delegate` / `task` | as today | `spawn` + `await_agents{mode:"all"}`; the old shape still works |
| `await_agents{handles, mode: all\|any\|first_ok, timeout_s}` | parent | suspends this session, without spending steps, until the condition holds or the timeout passes; returns the reports, plus any messages that arrived |
| `check_agents{handles?}` | parent | a status table: handle, agent, status, last progress, steps, cost |
| `send_agent{to, text, kind: steer\|note\|answer}` | parent → child; child → sibling | delivered to the recipient's inbox |
| `cancel_agent{handle, reason}` | parent | cancels it and, by default, its descendants |
| `read_ref{ref}` | any member | reads a blob that a report or message refers to |
| `report_progress{text, milestone?, percent?}` | child | sent according to the parent's policy |
| `ask_parent{question, timeout_s, default}` | child | waits for an `answer`; on timeout it proceeds with `default` and says so in its report |
| `board_put{key, value}` / `board_get{key?}` | any member | the crew's shared blackboard, on `crew:<id>` as `board` events, last write wins, with values capped at 2,000 characters |

**Inbox delivery.** Messages to a member are queued in memory (one `asyncio.Queue` per member) and appended to the ledger. They are rendered as one compact `inbox` turn at the head of the member's next think, **after** the cacheable prefix, so the prefix cache still hits. A member suspended in `await_agents` or `ask_parent` wakes on delivery. Message delivery is a direct in-process hand-off over the Bus with no polling and no model call. The target is under 50 ms from send to the recipient's queue, measured in item 7.

**Concurrency and budgets.**
- `[orchestration] crew_max_members = 8` per crew, and `max_children_concurrent = 4`, which is now real.
- Writers: agents whose profile is not `read_only`, such as `patch`. At most `crew_max_writers = 1` at once by default, each in its own task worktree as today. Readers run in parallel.
- A crew budget: `crew_max_usd` (default 0.50), `crew_max_wall_s` (default 900) and `crew_max_tokens`. A child's budget is carved from the parent's remaining budget at spawn. When the crew budget is exhausted, every member is cancelled with reason `crew budget`, and the root gets `partial` reports.
- Depth is ≤ `max_depth` (3) as today.

**Who may spawn.**
- `patch`, `research`, `plan` and project sessions may spawn any agent.
- `chat` may spawn only read-only agents (`research`, `browser`), and is offered `spawn` only when `[orchestration] chat_crews = true`.
- `voice_chat` may spawn only with `background = true` (below).
- A child inherits the parent's requester and `person_scope`, never more. Guardian sees the original person on every proposal.

**Background crews (chat and voice).** `spawn{background:true}` returns immediately. The chat or voice turn answers at once ("I'll look into it"). When the crew's root report arrives, it is delivered to the person who asked, as a `ui.notice` in the console or phone, or spoken by Voice through the same path Initiative uses, respecting quiet hours. If the person is still in the conversation, the result also enters that conversation's working window.

**Durability.** On restart, `crew:<id>` is folded. Running members resume through the existing task resume (stage 7 item 1 and `resume.py`). A parent that was in `await_agents` re-enters it with the reports already received. A member whose parent is gone finishes and files its report on the stream; nothing is lost.

## Action items

1. **Contracts.** *Lock `contracts`.* Add `contracts/messages/crew.py` (the four messages and `Report`), the topics in `contracts/topics.py`, the stream `crew:<id>` in `contracts/streamnames.py`, and schemas and contract tests. Add an allow-list entry only if a side is genuinely external. Update every consumer's CONTRACT.md "Consumes" table (orchestration, interface).

   Acceptance: `python tools/modtest.py contracts --tier core` is green.

2. **The crew runtime.** *Lock `orchestration`.* Add `simorgh/orchestration/crew.py`, a pure-ish core that is testable without a bus:
   - `Crew` (members, tree, budget carving, writer and concurrency semaphores, cancellation cascade, the report-policy engine, and the `crew:<id>` fold);
   - `Inbox`;
   - `Report` building (the child's final answer parsed into a typed `Report`; when it does not parse, the summary is the first 1,200 characters and the rest is a blob ref).

   Then wire it into `session.py`:
   - the tools above;
   - `delegate` reimplemented as spawn + await, with the old behaviour kept;
   - `await_agents` suspending without spending steps;
   - inbox rendering after the prefix;
   - periodic reports on steps and seconds;
   - `ask_parent` round trips;
   - `_batchable` no longer the gate for children, because spawn is non-blocking by construction.

   Acceptance tests:
   - three read-only children run concurrently, with wall-clock under 0.6× of serial using fake providers with fixed delays;
   - writer serialisation;
   - the crew budget cancels everyone and the root gets partial reports;
   - a cancel cascade;
   - an `ask_parent` answer and a timeout falling back to the default;
   - steering changes a child's next think;
   - the inbox stays out of the cacheable prefix (byte-identical prefix before and after a message);
   - a restart mid-crew resumes and the parent gets every report;
   - with `delegate` used as today, the behaviour is unchanged.

3. **Chat and voice crews.** *Lock `orchestration`, `agents/`; after item 2.* Add `chat_crews` and `background`, the delivery path for background reports (orchestration publishes; Interface and Voice deliver through their existing notice and speech paths, with no new delivery code in Voice unless its CONTRACT requires it), and the `agents/chat.md` and `agents/voice_chat.md` lines. Acceptance: a typed "compare A, B and C" with `chat_crews = true` answers at once, and the report arrives as a notice with all three.

4. **Projects on crews.** *Lock `planning`, `orchestration`; after item 2.* A project session spawns one member per ready plan node, up to the concurrency cap, instead of one child at a time, and the stage 7 node bookkeeping reads `crew.report`. Acceptance: a three-node independent plan finishes in about the time of its longest node.

5. **The tree, visible.** *Lock `interface`; parallel to items 2-4 once item 1 lands.*
   - The TUI's task tree shows crew members under their parent, with status, the last progress line, steps and cost, in the existing ⏺/⎿ shape.
   - Add a console command `crew [<id>]` (list members and messages) and `crew cancel <handle>`.
   - The dashboard has a crew panel reading `crew:<id>`.

   Acceptance: interface tests; `tui_is_sane` holds with a 6-member crew.

6. **Crew scenarios.** *Lock `evals`.* Add `toolchain/crew-*` scenarios (`needs_model = True`):
   - fan-out research of three items;
   - a child that must `ask_parent` for a preference;
   - a parent that steers a child off a dead end;
   - cancellation when the first child finds the answer (`first_ok`);
   - the crew budget ending a runaway;
   - a background chat crew delivering a notice.

   Add a free micro-benchmark, `python -m simorgh.evals crew-bench`, with fake providers: message latency p50/p95, spawn overhead, fan-out speedup, and memory per member.

   Acceptance: the micro-benchmark runs free and records its numbers.

7. **Measure and write down.** *No lock.* Run `crew-bench`, and the crew scenarios within a spend cap the creator sets. Write `docs/findings/<date>-agent-crews.md`: speedup, message latency, tokens per crew against one agent doing it alone, and failure shapes.

## Interoperability: A2A, which ACP has become

The creator asked for **ACP** (IBM's Agent Communication Protocol). ACP **merged into Google's A2A protocol under the Linux Foundation in August 2025**. Its repository was archived on 2025-08-27 with a migration guide, and IBM's ACP lead joined the A2A technical steering committee. So the vendor-neutral standard to implement is **A2A**: JSON-RPC 2.0 over HTTP, an Agent Card at `/.well-known/agent-card.json`, `message/send`, `message/stream` (SSE), `tasks/get`, `tasks/cancel`, push notifications, and a task lifecycle (`submitted | working | input-required | completed | failed | canceled`) with message parts and artifacts. Zed's *Agent Client Protocol*, also abbreviated "ACP", is an unrelated editor-to-agent protocol and is out of scope.

**Design rule.** Inside one Sim, crew members talk over the in-process Bus. Putting HTTP between two coroutines in one process would add latency and failure modes for nothing. But the crew's **data model is A2A's**:
- `crew.*` member status maps 1:1 to A2A task states (`waiting` = `input-required`);
- a `crew.message` is an A2A `Message` with parts (`text`, `data`, `file` as a ref);
- a `Report` is an A2A `Task` with `artifacts`.

So a crew member can be a remote A2A agent, and a Sim agent can be served to a remote caller, with a pure mapping and no glue. Item 1's schemas follow this rule.

8. **A2A mapping.** *Lock `contracts`; with item 1.* Add `contracts/a2a.py`, with pure functions `to_a2a_task(member, report)`, `to_a2a_message(crew_message)`, `from_a2a_task(...)` and `from_a2a_message(...)`, plus round-trip tests against the A2A JSON schema fixtures. The schema is vendored as test data under `tests/simorgh/contracts/fixtures/a2a/`, with its version pinned.

9. **Sim calls remote agents (A2A client).** *Lock `execution`, `orchestration`, `docs`; after items 2 and 8.*
   - `spawn{agent: "a2a:<name>", ...}` makes a crew member whose work is done by a remote agent.
   - Each remote call is a tool, `a2a_call`, in Execution, so it is **proposed to and gated by Guardian**, because it sends household data out of the house. Its reversibility is `irreversible` (data sent cannot be unsent), and its policy row says which agents may receive what.
   - Remote agents are configured only by a person, under `[crew.a2a_agents.<name>] url`, `auth_secret` (a key name in `secrets.toml`) and `allowed_data`, and approved with a console `a2a approve <name>`, like `mcp approve`. Sim may *propose* one and never add one itself.
   - The client fetches the Agent Card, uses `message/stream` when the card says it streams (each A2A status update becomes a `crew.message{kind:"progress"}`), and falls back to `message/send` plus `tasks/get` polling at a bounded interval.
   - `input-required` becomes an `ask_parent`; `cancel_agent` sends `tasks/cancel`.
   - It uses the official `a2a-sdk` Python package under `try/except ImportError`, as with the MCP SDK (stage 9 item 12). Without the SDK, the member reports `blocked` with "needs `pip install a2a-sdk`".

   Acceptance:
   - tests against an in-process fake A2A server: stream, send+poll, input-required round trip, cancel, and a Guardian denial meaning no HTTP request is made;
   - a card that asks for a scheme Sim cannot meet is refused by name.

10. **Sim serves its agents (A2A server).** *Lock `interface`, `contracts`; after items 2 and 8.*
    - Interface's HTTP server gains `/.well-known/agent-card.json` and the A2A JSON-RPC endpoint. It is **off by default** (`[interface.a2a] enabled = false`) and bound to the same listener and token as the phone pairing.
    - The card lists only the agents named in `[interface.a2a] expose` (default `["research"]`), with their skills taken from the agent files.
    - An inbound `message/send` or `message/stream` becomes a crew whose **requester is the paired caller**, and Guardian treats it as that person. An unpaired caller gets a 401 and nothing runs.
    - Streaming sends the crew's `crew.message` progress as A2A status updates; `tasks/get` and `tasks/cancel` map to the crew; push notifications are left out for now.

    Acceptance:
    - an A2A client test (the SDK's client when installed, a raw JSON-RPC client otherwise) runs a `research` task end to end with the floor provider, and streams at least one progress event;
    - no token gives a 401;
    - an agent not in `expose` is not in the card and is refused.

11. **Interop proof.** *No lock; after items 9-10.* One Sim calls another Sim's `research` agent over A2A (two sandboxes, `tools/trial.py`), and Sim calls one third-party A2A sample agent. Write the latency, the failure shapes, and the data each one sent into the stage 18 findings.

12. **Claude Code as a crew member.** *Locks `execution`, `orchestration`, `guardian` (one rule), `agents/`; after item 2.*

    The creator, 2026-10-27: "allow Sim to spawn Claude Code and ask Claude Code to implement some feature for it". Sim already *thinks* through the Claude Code CLI as a last-resort provider (`cognition/providers`). This item is different: Claude Code as an autonomous **coding worker** that Sim briefs, watches and judges.

    - **How it runs.** It uses the **Claude Agent SDK** (`claude-agent-sdk`, Python, under `try/except ImportError`), driving the installed `claude` CLI (2.1.311 on this laptop). The CLI's headless `claude -p --output-format stream-json` is the fallback. `spawn{agent:"claude_code", brief, budget}` creates a crew member whose session is a Claude Code run in **its own task worktree** (existing `worktree_open`), never in the live checkout.
    - **Guardian sees every call.** This is the non-negotiable part. A `PreToolUse` hook (an Agent SDK hook, or the CLI `--settings` hooks in the fallback) sends each Claude Code tool call (Bash, Edit, Write, WebFetch, …) to Guardian as an `action.proposed` with the requester inherited from the crew. It allows the call only on `action.approved`, and denies it with Guardian's reason otherwise. With no hook path available, the member refuses to start. Claude Code's own permission mode is set to the most restrictive that still lets the hook decide, and network tools are denied unless the brief's agent definition allows them.
    - **Protected paths.** Claude Code may not edit `simorgh/guardian/`, `simorgh/execution/`, `simorgh/contracts/`, `simorgh/kernel/`, `simloader.py`, `sim.sh` or `docs/SOUL.md` (CLAUDE.md rule 5: Sim's own tasks never edit them). There are two locks on this. Guardian's ProtectedRule denies the edit through the hook. And **`worktree_land` refuses a diff that touches any protected path.** Today `execution/worktree.py` has no protected-path check at landing, which is a gap whatever this item does, and is fixed here with a test.
    - **Reporting.** Stream events become `crew.message{kind:"progress"}`, so the parent can `check_agents` or `await_agents`. Claude Code's final result becomes the typed `Report`: `artifacts` are the worktree diff, a blob ref, and the commits. The parent, or Verification, judges it. **Landing goes through the existing gate**: rebase, the whole-suite verdict from `simloader.unit_verdict`, then fast-forward. Claude Code never pushes or lands by itself.
    - **Budget.** It runs under the crew budget: a hard cap on turns (`max_turns`, with the SDK's cost reported per run), a wall-clock cap, and `[crew.claude_code] max_usd_per_run` (default 2.00) and `max_runs_per_day` (default 3). It uses the creator's Claude subscription or API key, so every run is counted and shown (the 2026-09-11 lesson: silent use of the Claude quota). It is **off by default** (`[crew.claude_code] enabled = false`). The first run of each day asks the creator, through Guardian's `needs_human`, in every posture.
    - **The brief.** It is built from the agent file `agents/claude_code.md`: the feature request, the acceptance test, the files in scope, "run `python tools/modtest.py <module>`", and "do not touch protected paths". The repo's `CLAUDE.md` already gives Claude Code the module-lock and contract rules.

    Acceptance:
    - tests with a fake Agent SDK: every tool call reaches Guardian, and a denied call never runs;
    - a protected-path diff is refused at landing, both through Claude Code and through an ordinary patch task;
    - with no hook path, the member refuses to start;
    - budget caps end the run as `partial`;
    - one live trial in a repo copy (`tools/trial.py`): Sim asks Claude Code for a small feature in a non-protected module, Claude Code implements it with a test, the landing gate passes, and the findings record the cost and every Guardian decision.

## What this must never do

- Let a member act outside Guardian, or with more authority than the person who asked. Children inherit the requester; they never escalate.
- Run two writers on one tree at once, or let a child land on main without the existing landing gate.
- Let a crew spend without a bound. Every crew has dollars, wall-clock and member caps, and exhaustion is a typed `partial`, never a hang.
- Put transcripts in messages. Messages carry conclusions and refs; a parent reading a child's whole transcript is the cost this design exists to avoid.
- Break the cacheable prefix. Inbox and progress go after it.
- Poll. Waiting is event-driven (`await_agents`, `ask_parent`, stage 7 `wait`).
- Speak a background result into a room during quiet hours, or to a different person than the one who asked.

## Definition of done

- [ ] Items 1-6 built with tests; module tiers are green; `--tier core` is green (contracts changed); every CONTRACT.md is updated.
- [ ] `crew-bench` numbers are recorded; the scenarios run within the cap; the findings are written.
