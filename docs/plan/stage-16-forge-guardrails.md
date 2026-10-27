# Stage 16 -- Forge's guardrails in Sim's loop

Status: **in progress** (2026-10-27: plan written; items 1-3 being built on top of the stage 14 branches) · Depends on: stage 2 (native tools), stage 14 (the ablation switches and runner measure this stage) · Modules touched: cognition, orchestration; `agents/` (orchestration lock); `docs/`

## Outcome

Sim's agent loop gets the reliability layer from forge (github.com/antoinezambelli/forge, `src/forge/guardrails/`, `src/forge/prompts/{nudges,templates}.py`, ADRs 010, 013 and 016). On forge's own suite that layer took Haiku 4.5 from 46% to 94% and Sonnet 4.6 from 85% to 98%. Each part arrives behind a stage 14 ablation name, so the stage 14 matrix measures it on Sim's own scenarios.

| Forge piece | Sim piece | Module | Ablation name |
|---|---|---|---|
| `rescue_tool_call`: JSON in fences, `name[ARGS]{}`, Qwen `<function=>` XML, Mistral `[TOOL_CALLS]`, `<tool_call>` | `cognition/rescue.py`, run when a reply carries no call the dialect recognises | cognition | `cognition.ablate "rescue"` (already defined by stage 14; this widens it) |
| `ResponseValidator`: unknown tool, args not an object, fed back on the **tool channel** with the list of tools | `orchestration/guardrails.py::validate`, before `action.proposed` | orchestration | `orchestration.ablate "nudge"` (new) |
| `ErrorTracker`: consecutive retries ≤ 3, consecutive hard tool errors ≤ 2, soft errors not counted (ADR-010) | `guardrails.ErrorBudget`, per session | orchestration | `orchestration.ablate "recovery"` (stage 14) |
| `StepEnforcer`: required steps, terminal tools, prerequisites (name-only and arg-matched), escalating nudges tier 1-3 | `guardrails.Steps`, from agent frontmatter | orchestration | `orchestration.ablate "steps"` (new) |
| ADR-013: text is a valid answer when no tool is needed | kept: a chat or voice reply in text is never nudged | orchestration | -- |

## Definitions (shared by every item; do not rename)

- **A nudge** is a message added to the session transcript and sent with the next think. It is either `role = "tool"` (the correction rides the tool-result channel, for an unknown tool or bad arguments) or `role = "user"` (a step or prerequisite violation, or a "looked like a tool call" retry). It has a `kind` (`unknown_tool | bad_args | retry | step | prerequisite`) and a `tier` (0, or 1-3 for step). A nudge is recorded on the `task:<id>` stream as a step of kind `nudge`, so resume and the TUI tree see it. **A nudge does not spend a step of `max_steps`; it spends the retry budget.**
- **Retry budget**: `max_retries` (default 3) consecutive nudges of kinds `unknown_tool | bad_args | retry`. A clean proposal resets it. When it is exhausted, the session ends `failed` with reason `retries exhausted: <last kind>`.
- **Tool-error budget**: `max_tool_errors` (default 2) consecutive *hard* tool errors (`ToolResult.error_kind == "failed"`). `transient` is soft: fed back, never counted. `refused` and `unconfigured` are fed back once, and a second identical call ends the session `blocked`, because no retry fixes a missing credential. A fully clean step resets the budget. Exhausted means `failed` with reason `tool errors exhausted`.
- **Guardian is untouched.** Validation runs *before* a proposal is published, and covers only things Guardian would deny as malformed: an unknown name, or arguments that are not an object or fail the schema's required and type checks. Every surviving call is still proposed and gated. A Guardian denial for a safety reason is fed back exactly as today, never converted into a nudge, and never retried automatically.
- **Text intent (ADR-013).** For the `chat` and `voice_chat` scaffolds, a text reply is the answer. Text is nudged (`kind = "retry"`) only when it *looks like* a failed call: it names an offered tool followed by `(`, `{` or `[`, or contains a fenced JSON object with a `tool`/`name` key, and rescue found nothing. Task scaffolds treat text as the final answer, subject to step enforcement.
- **Steps**: new optional agent frontmatter keys, all defaulting to empty:
  - `required_steps = ["run_tests"]`: tools that must succeed before the session may finish;
  - `terminal_tools = ["git_commit"]`: the tools that end it; empty means the final text answer ends it;
  - `prerequisites = { git_commit = ["run_tests"], worktree_land = [{ tool = "git_commit", match_arg = "path" }] }`.

  A premature finish or terminal call gets a step nudge at tier `min(attempts, 3)`, using forge's three wordings: polite, direct, then a capitalised "STOP". After `max_premature_attempts` (default 3) the session ends `blocked` with reason `required steps not done: <pending>`. A prerequisite violation blocks the whole batch, and after 2 consecutive violations the session ends `blocked`. Step state lives on the session, not in the transcript, so compaction cannot erase it (forge's StepTracker, P0-1). It is persisted with the session's other resumable state.
- **Config**: `[orchestration] max_retries = 3`, `max_tool_errors = 2`, `max_premature_attempts = 3`, `max_prereq_violations = 2`. `orchestration.ablate` grows `"nudge"` and `"steps"`. The stage 14 preset table grows `no_nudge` and `no_steps`, and `bare` includes both.

## Action items

1. **Rescue parsing.** *Lock `cognition`; parallel to item 2.*
   - Add `simorgh/cognition/rescue.py`, porting forge's four strategies plus `<tool_call>{json}</tool_call>`. Strip think tags first. Accept a call only for a tool **offered to this session**, and only if its arguments parse to an object. Return a list of calls in the same shape the native decoder returns.
   - Wire it where a reply is decoded: after the native decoder finds no typed call, and after the marker parser finds no marker. Whatever rescue recovers is marked `rescued = true` on the parsed output, so the TUI and the ablation can count it.
   - Under `cognition.ablate "rescue"` it is skipped entirely.
   - Tests, using forge's own fixtures as the shape:
     - one per strategy;
     - a tool not offered is never rescued;
     - prose that mentions a tool name is not rescued;
     - default behaviour on a well-formed native call or marker is unchanged.
   - Update CONTRACT.md.

2. **Validation, nudges, budgets and steps.** *Lock `orchestration` (and `agents/`); parallel to item 1.*
   - Add `simorgh/orchestration/guardrails.py` as pure functions and small classes with no bus: `validate(calls, offered, schemas) -> Ok | Nudge`, `ErrorBudget`, `Steps`, and the nudge texts.
   - Wire them into `session.py` at the proposal point and after each `action.result`, per the Definitions.
   - Add the frontmatter keys to `profiles.py` (they are refused today as unknown keys, so add them to `_FIELDS`). Set conservative defaults in `agents/patch.md` and `agents/skill.md`: `prerequisites = { git_commit = ["run_tests"] }` only where a test tool is offered. Add nothing to `chat.md` or `voice_chat.md`.
   - Ablation: `"nudge"` turns off validation and retry nudges (calls go straight to Guardian as today), and `"steps"` turns off step enforcement.
   - Tests:
     - each nudge kind;
     - the budget reset and exhaustion;
     - a soft error not counted;
     - `unconfigured` twice → blocked;
     - a chat text reply never nudged;
     - a looks-like-a-call text nudged;
     - premature tiers 1→2→3 then blocked;
     - an arg-matched prerequisite;
     - step state surviving a resume;
     - all switches off → today's behaviour.
   - Update CONTRACT.md.

3. **Stage 14 preset table.** *Lock `evals`; after stage 14 item 4 merges.* Add `no_nudge` and `no_steps` to `simorgh/evals/ablation.py` and the stage 14 plan table, and put both in `bare`.

4. **Measure.** Run within the creator's $2 cap for the stage 14 matrix: `sim` against `bare`, and against `no_nudge` and `no_steps` if the budget allows. Write the result into the stage 14 findings.

## What this must never do

- Weaken or bypass Guardian, or retry a call Guardian denied for a safety reason.
- Nudge a chat or voice reply that is simply an answer. ADR-013 is the forge author's own lesson here: retrying text in conversation wastes calls and confuses the model.
- Let a nudge loop forever. Every nudge path is bounded by a budget, and every exhaustion is a terminal outcome with a reason.
- Spend a `max_steps` step on a nudge, or hide a nudge from the task stream.
