# 09 — Guardian (`simorgh/guardian/`)

> Part of the Simorgh v2 blueprint. Governing documents:
> `01-vision-and-principles.md` (principles), `02-system-architecture.md`
> (position and flows), `03-contracts-and-messaging.md` (envelope, topics,
> delivery semantics, protocols). A spec may refine those documents; it
> may not contradict them. If you find a contradiction, fix the governing
> document and note it in `00-README.md`'s changelog.

**Layer:** 2 Agency
**Owner (build):** unassigned
**Status:** draft
**Depends on (contracts only):** `action.proposed` (exclusive), `system.state.changed`, `system.tick.second`, `task.created`, `task.started`, `task.completed`, `task.failed`, `tool.registered`, `tool.unavailable`, `cognition.provider.status`, `reflect.drift.detected`, `reflect.health.finding`, `ui.prompt.answered`, `cognition.think.reply`
**v1 code that migrates here:** `src/orchestrator/audit.py` (`AuditGate`, `PROTECTED_SUBJECTS`, denylist table, `_check_adaptive_immunity`, `REJECTED_KIND`), `src/orchestrator/soul.py` (directive loading), the failure-streak circuit breaker from `src/orchestrator/autonomy.py`, budget-cap enforcement from `src/main.py` (`DEFAULT_CLAUDE_CODE_MAX_CALLS`, `DEFAULT_DAILY_BUDGET_USD` semantics), `src/orchestrator/apply.py` scope constants (mirrored)

## 1. Purpose and responsibilities

Guardian is the constitution made structural. It is the only subsystem
that can turn a proposed action into an approved one, and it does so by
running every proposal through a fixed, ordered pipeline of independent
checks — mode, protected subjects, scope, denylist, adaptive immunity,
budget, reversibility policy, and an optional model-backed classifier for
the ambiguous middle — in which any deny ends the matter, ambiguity
escalates to a human, and only a clean pass produces a cryptographically
bound approval. It also owns the system's trust posture: the graduated
permission level that tightens automatically on evidence of trouble and
loosens only when a human changes configuration. Guardian never acts. It
decides, records why, and tells the human when it could not decide.

**Responsibilities (owns):**
- Exclusive consumption of `action.proposed`; emission of
  `action.approved` (with `approval_token`), `action.denied`, `action.needs_human`.
- The check pipeline and its rule tables (protected subjects, denylist,
  scope rules, reversibility policy per mode, budget caps).
- Permission modes (`observe | plan | guarded | trusted | locked`) at
  system and per-task granularity.
- The trust posture (`guardian:trust`) and its automatic tightening.
- Adaptive immunity: the memory of rejected proposals and the similarity
  check against it.
- The `guardian.review` request/reply used by Verification to run the
  static + immunity checks on candidate code without an action.
- Handling `system.pause`/`system.stop` (deny everything; drain).
- The audit trail on `action:<id>` and transparency notices to Interface.
- Loading `docs/SOUL.md` directives as checkable rules; refusing to ever
  approve a modification of the constitution or of itself.

**Explicit non-responsibilities (belongs elsewhere):**
- Running anything — **Execution**.
- Judging quality or intent of results — **Verification**.
- Deciding which tasks exist or their order — **Planning**.
- Producing the trust *evidence* (drift, calibration, health) —
  **Reflection**; Guardian only consumes it.
- Provider budgets' accounting — **Cognition** (Guardian enforces caps
  from `cognition.provider.status`).

**Principles this subsystem is the primary enforcer of** (`01` §4):
4.3 (structural safety), 4.10 (reversibility-weighted oversight), 4.11
(graduated trust; loosening is human), the deny-first and defense-in-depth
principles of `harness-01`, and SOUL Directives 1–5 as rules.

## 2. Position in the architecture

Layer 2, the chokepoint of the action path (`02` §3). Present in every
flow with an action: 1, 2, 3 (read-only enforcement), 4 (protected
subjects; the self-patch gates), 5 (pause = deny all), 6 (research is
read-only by policy), 9 (no actions — Curiosity only proposes tasks).
Imports only `simorgh.contracts`, bus/ledger clients, stdlib. The Kernel
enforces that only `guardian` may subscribe to `action.proposed`, and
Guardian's package is itself on the protected list, so no self-patch can
ever be approved that touches it.

## 3. Interfaces

### 3.1 Messages consumed

| Type | Pattern | Semantics | What Guardian does with it |
|---|---|---|---|
| `action.proposed` | command (group `guardian`) — reserved | work | run the pipeline (§5.1); emit exactly one of approved/denied/needs_human |
| `system.state.changed` | event | fact | `paused`/`stopping` → deny all with `layer: paused`; `running` → resume |
| `task.created`, `task.started` | events | fact | maintain `TaskModes` projection: `task_id → {mode, kind, risk, scope, origin, channel}` |
| `task.completed`, `task.failed` | events | fact | failure-streak accounting for trust tightening (`succeeded=False` counts; `None` ignored — v1 breaker semantics) |
| `tool.registered`, `tool.unavailable` | events | fact | `ToolTable` projection: `name → {read_only, reversibility, provider}` |
| `cognition.provider.status` | event | fact | `BudgetTable`: per-provider calls/spend in window vs caps |
| `reflect.drift.detected`, `reflect.health.finding{critical}` | events | fact | tighten trust posture |
| `ui.prompt.answered` | event | fact | resolve a pending `action.needs_human`; on `yes` emit `action.approved` (fresh token, fresh expiry), on `no` emit `action.denied{layer: human}` |
| `cognition.think.reply` | reply | rep | classifier answer for an escalated-to-model proposal |
| `guardian.review` | request | req/rep | static denylist + immunity + protected check on `{subject, code}` → `guardian.review.reply` (see §12 Q1: new domain) |

### 3.2 Messages produced

| Type | Semantics | Payload summary | Consumers |
|---|---|---|---|
| `action.approved` | command | `{action_id, tool, args_sha256, expires_at, approval_token, mode_at_approval, constraints}` | execution (exclusive) |
| `action.denied` | event | `{action_id, reasons[], layer}` | orchestration, planning, reflection, interface, learning |
| `action.needs_human` | event | `{action_id, question, options, default}` | interface (renders `ui.prompt`) |
| `ui.prompt` | command | human approval prompt bound to `action_id` | interface |
| `ui.notice` | event | every denial of an autonomous action, every posture change | interface |
| `guardian.review.reply` | reply | `{ok, verdict: pass\|deny, reasons[], layer}` | verification |
| `guardian.posture.changed` | event | `{level, reason, previous}` (see §12 Q1) | interface, reflection, planning, curiosity |
| `system.health` | event | degraded on repeated token/pipeline errors | kernel |
| `cognition.think` | request | classifier prompt for ambiguous proposals | cognition |

### 3.3 Request/reply APIs served

- **`guardian.review` → `guardian.review.reply`** (timeout 5 s). Runs
  protected-subject, static denylist, and adaptive-immunity checks on a
  candidate `{subject, code, rationale}` and returns the verdict with
  the failing layer and reasons. Used by Verification for self-patch and
  skill candidates before the expensive test-suite run (v1's quick
  `DRAFT:` check). A `deny` here also appends to `guardian:rejected`
  (immunity learns from Verification's finds too).

### 3.4 Python protocol (`api.py`)

```python
class Rule(Protocol):
    name: str; layer: Layer                      # policy|paused|mode|protected|scope|denylist|immunity|budget|reversibility|classifier|human
    async def evaluate(self, p: Proposal, ctx: DecisionContext) -> Decision
    # Decision(kind: allow|deny|escalate|abstain, reasons: list[str], layer: Layer)

@dataclass(frozen=True)
class DecisionContext:
    now: float; system_state: str; posture: Posture
    task: TaskMode | None; tool: ToolInfo | None; budgets: BudgetTable
    rejected: RejectedIndex                      # adaptive immunity memory
    config: GuardianConfig; think: Callable[..., Awaitable[ThinkReply]]

class Pipeline:
    rules: tuple[Rule, ...]                      # fixed order, see §5.1
    async def decide(self, p: Proposal, ctx: DecisionContext) -> Verdict   # Verdict(kind, reasons, layer, constraints)

class TokenIssuer:
    def issue(self, action_id: str, tool: str, args: dict, *, ttl_s: float) -> tuple[str, float]   # (token, expires_at)

class Posture:                                   # projection of guardian:trust
    level: Literal["trusted","guarded","locked"]; baseline: str; reasons: list[str]
    def tighten(self, reason: str) -> Posture    # never loosens
```

### 3.5 Configuration (`[guardian]`)

| Key | Type | Default | Controls |
|---|---|---|---|
| `mode` | `observe\|plan\|guarded\|trusted\|locked` | `guarded` | system-wide baseline mode |
| `baseline_posture` | `trusted\|guarded` | `guarded` | posture the system may return to after a human `system.resume` |
| `approval_ttl_s` | float | 120 | token expiry |
| `protected_subjects` | list | `["docs/SOUL.md","src/orchestrator/soul.py","src/orchestrator/audit.py","src/orchestrator/apply.py","src/orchestrator/self_patch.py","simorgh/guardian/","simorgh/execution/","simorgh/contracts/","simorgh/kernel/","simorgh.toml"]` | never writable by any action (v1 `PROTECTED_SUBJECTS` ∪ v2) |
| `denylist` | table of `{pattern, reason, directive}` | v1 `audit.py` table | static code/arg patterns |
| `immunity_similarity_threshold` | float | 0.85 (port v1 value) | `SequenceMatcher` ratio vs rejected code |
| `immunity_window_days` | int | 90 | how far back immunity looks |
| `max_consecutive_failures` | int | 5 | failure streak → tighten to `locked` for autonomous origins (v1 breaker) |
| `budget_pressure_tighten_at` | float | 0.9 | fraction of any provider cap that tightens `trusted → guarded` |
| `irreversible_requires_human` | bool | true | in `guarded` |
| `reversible_auto_in_guarded` | bool | true | |
| `classifier.enabled` | bool | true | model-backed review for the ambiguous middle |
| `classifier.on_floor` | `escalate\|deny` | `escalate` | when no real provider answers the classifier |
| `human_prompt_timeout_s` | float | 1800 | unanswered → `action.denied{layer: human, reasons:["timeout"]}` |
| `autonomous_origins` | list | `["curiosity","reflection","research","project"]` | origins the breaker applies to |
| `SIMORGH_GUARDIAN_MODE` | env | — | override for `mode` (e.g. `observe` during migration) |

Loosening (`locked → guarded`, `guarded → trusted`) happens **only** by
editing this config (or `system.resume` returning to `baseline_posture`),
never by any message or self-patch — `simorgh.toml` is itself protected.

## 4. Data model and Ledger streams

- `action:<id>` — Guardian appends `received {proposal}`, one `check
  {rule, decision, reasons}` per rule evaluated, and `decided {kind,
  layer, token_hash?, expires_at?}`. This is the per-action audit trail
  (Execution appends its own events after).
- `guardian:rejected` — `rejected {subject, code_sha, code_excerpt(≤4KB),
  reasons, layer, source: action|review}`; projection `RejectedIndex`
  (bounded by `immunity_window_days`) used by adaptive immunity. v1's
  `kind=rejected_proposal` records migrate here.
- `guardian:trust` — `tightened {from, to, reason, evidence_ref}`,
  `reset_to_baseline {by: human, via: resume|config}`; projection `Posture`.
- `guardian:pending_human` — `asked {action_id, prompt_id, proposal}`,
  `answered {answer}`; re-issued on restart if unanswered.
- `guardian:failures` — streak counter events per origin.

No state outside the Ledger except the in-memory projections rebuilt at
start (`TaskModes`, `ToolTable`, `BudgetTable`, `RejectedIndex`, `Posture`).

## 5. Internal design

```
guardian/
  service.py       reserved subscription, projections, wiring, health
  pipeline.py      ordered rules, short-circuit semantics, verdict → messages
  rules/
    paused.py  mode.py  protected.py  scope.py  denylist.py  immunity.py
    budget.py  reversibility.py  classifier.py
  tokens.py        HMAC issue; canonical args hashing (shared helper in contracts)
  posture.py       trust projection; tighten triggers
  charter.py       loads SOUL.md directives; exposes directive text per rule for reasons
  review.py        guardian.review handler (subset pipeline: protected, denylist, immunity)
  human.py         needs_human ↔ ui.prompt lifecycle, timeouts
```

### 5.1 The pipeline (fixed order; deny short-circuits; escalations accumulate)

```
proposal ─▶ [0 paused]  stopping/paused ─▶ DENY layer=paused
        ─▶ [1 mode]     system mode ∧ task mode:
                          observe → DENY(all)   locked → DENY(all non-read_only from autonomous origins; human origin: read_only only)
                          plan    → tool.read_only ? continue : DENY layer=mode
                          guarded/trusted → continue
        ─▶ [2 protected] any path in proposal.scope.paths ∩ protected_subjects (prefix match) ─▶ DENY layer=protected
                         tool ∈ {apply_source_patch, apply_skill, git_commit, shell} with subject protected ─▶ DENY
        ─▶ [3 scope]     proposal.scope ⊄ task.scope (paths outside subject/parent scope; network when task.scope.network=false)
                          ─▶ read_only tool: ALLOW-with-note (reading beyond scope is fine)  |  write tool: ESCALATE (guarded) / DENY (locked)
        ─▶ [4 denylist]  args.code / args.command / args.url against patterns ─▶ DENY layer=denylist (reason cites the directive)
        ─▶ [5 immunity]  SequenceMatcher(args.code, rejected.code_excerpt) ≥ threshold ─▶ DENY layer=immunity
        ─▶ [6 budget]    tool causes model calls? (drafting tools) ∧ provider at cap ─▶ DENY layer=budget
                         per-task cost cap exceeded ─▶ DENY
        ─▶ [7 reversibility]  read_only → ALLOW
                              reversible → guarded: ALLOW ; locked: DENY
                              irreversible → trusted: ALLOW ; guarded: ESCALATE(human) ; locked: DENY
        ─▶ [8 classifier] only if some rule returned ESCALATE with kind=ambiguous (scope) and classifier.enabled:
                          cognition.think(purpose=review, require_real_provider=true) → "ALLOW"/"DENY"/"ASK" line-scan
                          floor or no verdict → classifier.on_floor (default ESCALATE)
        ─▶ verdict:  any DENY → action.denied{layer of first deny}
                     any ESCALATE remaining → action.needs_human (+ ui.prompt), pending record
                     else → action.approved{token, constraints from tool + task}
```

**Deny always wins over allow**: a rule cannot override an earlier deny,
and no allow-list exists that a deny-list entry cannot beat
(`harness-01`, "deny always wins over allow, regardless of specificity").
`constraints` on approval are the intersection of the tool's defaults,
the task's scope (`allowed_paths`, `network`), and mode-specific limits
(plan mode: `timeout_s ≤ 30`).

### 5.2 Modes and where they come from

System mode = `config.mode` narrowed by `Posture` (`locked` posture ⇒
effective mode `locked` for autonomous origins) narrowed by
`system_state` (paused ⇒ everything denied). Task mode comes from
`TaskModes[task_id].mode` (`plan` for plan-phase project tasks and for
`kind=research` by policy). A proposal without `task_id` (an Interface
command from the creator) uses the system mode with `origin=human`.

### 5.3 Trust posture

`Posture` starts at `baseline_posture`. Tightening triggers, each
appending `tightened` with evidence: failure streak ≥
`max_consecutive_failures` among `autonomous_origins` → `locked`
(v1 breaker: prints the loud notice, and `autonomous` work stops);
`reflect.drift.detected` → `guarded` (from `trusted`); any provider at
≥ `budget_pressure_tighten_at` → `guarded`; `reflect.health.finding{
critical}` → `locked`. Reset only by `system.resume` (a human action,
which v1 modeled as `autonomous on`) back to `baseline_posture`, recorded
as `reset_to_baseline{by: human}`. There is deliberately no message that
loosens posture (`harness-06`, "graduated trust … should go through a
human decision explicitly").

### 5.4 Tokens

`TokenIssuer.issue` computes `sha256(canonical_json(args))`, `expires_at
= now + approval_ttl_s`, `token = HMAC-SHA256(secret, f"{action_id}|{tool}|{args_sha256}|{expires_at}")`.
Only the token's hash is written to the Ledger. A human-approved action
gets a *new* token at answer time (the original would have expired).

### 5.5 Concurrency

Proposals are independent; the pipeline runs per message under the
Bus's per-partition ordering (all actions of one task serialize, so a
denial's immunity write is visible to the next proposal of that task).
Projections are updated by event handlers on the same loop; no locks
beyond an `asyncio.Lock` around `RejectedIndex` writes.

## 6. Key behaviors — worked scenarios

**S1 — Plan-mode read approved, write denied (Flow 3).** Task P is
`mode=plan`. `action.proposed{tool:read_file}` → paused? no → mode: plan ∧
read_only ✓ → protected ✓ → scope: path outside subject but read_only →
allow-with-note → denylist n/a → immunity n/a → budget n/a →
reversibility read_only → ALLOW → `action.approved{token, constraints:{
timeout_s:30}}`. Next, `action.proposed{tool:apply_source_patch}` from the
same Worker → mode: plan ∧ not read_only → `action.denied{layer:mode,
reasons:["plan mode: only read-only tools"]}` → `ui.notice`.

**S2 — Irreversible action escalates, human answers (Flow 1/5).**
Creator-originated turn proposes `shell{command:"rm -rf build/"}` in
`guarded` → mode ok → protected ✓ → scope ✓ (creator channel) → denylist
(no pattern) → reversibility irreversible ∧ guarded → ESCALATE →
`action.needs_human{question:"Run `rm -rf build/`?", options:[yes,no],
default:no}` + `ui.prompt` → `ui.prompt.answered{yes}` → fresh token →
`action.approved`. Timeout instead → `action.denied{layer:human,
reasons:["no answer in 1800s"]}`.

**S3 — Self-patch targeting the Guardian (failure, Flow 4).**
`action.proposed{tool:apply_source_patch, args:{subject:"simorgh/guardian/pipeline.py"}}`
→ protected prefix match → `action.denied{layer:protected, reasons:["'simorgh/guardian/' is protected; only the creator may edit it directly"]}`;
`guardian:rejected` gains the excerpt so immunity catches a reworded
retry; `ui.notice`.

**S4 — Immunity.** A skill candidate `eval(input())` was denied last week
(`layer:denylist`). Today a new proposal's code is 91% similar →
`action.denied{layer:immunity, reasons:["91% similar to a previously
rejected proposal (adaptive immunity)"]}` without running any further
check — remembering a threat responds faster the second time.

**S5 — Failure streak locks autonomous work.** Five consecutive
`task.failed` from `origin=curiosity` → `guardian:trust tightened{to:
locked, reason:"5 consecutive failed autonomous actions"}` →
`guardian.posture.changed` → `ui.notice("paused itself … 'resume' to
continue")`. Subsequent autonomous proposals are denied `layer:mode`;
a creator-originated read still passes. `system.resume` → `reset_to_baseline`.

**S6 — Paused.** `system.pause` → every proposal denied `layer:paused`
until `system.resume`; pending human prompts are kept, not answered.

## 7. Design considerations and tradeoffs

- **One chokepoint, many independent techniques.** A static list, a
  learned similarity memory, a budget table, a policy matrix, and an
  optional model classifier each have different blind spots
  (`harness-01` "defense in depth"; `harness-05` §5). Ordering cheap and
  deterministic checks first keeps the common case sub-millisecond and
  leaves the model call for the genuinely ambiguous middle.
- **Escalate, don't guess.** When the classifier gets only the floor,
  the default is to ask a human rather than deny (which would silently
  stall autonomous work) or allow (deny-first forbids it) — `harness-04`'s
  "a non-answer is not a rejection," applied to permissions.
- **Reversibility-weighted policy** makes oversight proportional to
  consequence (`harness-01`); it depends on Execution's honest tool
  metadata, which is why skills are never treated as read-only (§08 Q3).
- **Posture never loosens by message.** The cost is that a spuriously
  tripped breaker needs a human `resume`; the benefit is that no chain of
  self-generated evidence can talk the system into trusting itself more
  (`harness-06`; SOUL Directive 4/5).
- **Scope for read-only tools is advisory.** Reading beyond a task's
  subject is how context gets gathered; blocking it would re-create v1's
  "unwinnable check" problem (milestone 84, `harness-05` §3 tradeoff).
- **Protected list includes v2 substrate and the config file** — the
  system can evolve every cognitive subsystem but not the parts that
  decide what it may do (`AGI-04` §9, corrigibility).

Alternatives rejected: allow-lists per tool (a broad deny could be
overridden by a narrow allow — exactly the failure `harness-01` warns
about); embedding the checks in Execution (loses the independent
decision record and lets a compromised executor approve itself);
weighted scoring across rules (opaque; a deny must be a deny).

## 8. Safety, degradation, and failure modes

- **Provider down / floor:** only the classifier depends on a model;
  `classifier.on_floor` escalates. Every other rule is deterministic.
- **Budget exhausted:** rule 6 denies model-costing tools with a clear
  reason; read-only, non-model tools continue.
- **Malformed proposal:** schema failure → `action.denied{layer:policy,
  reasons:["schema"]}`; ack.
- **Rule crash:** treated as DENY for that proposal (`layer:policy`,
  reason includes the rule name); `system.health{degraded}`; never an
  allow by accident.
- **Restart mid-decision:** the proposal is redelivered (command
  semantics); `action:<id>` shows a `received` without `decided`; the
  pipeline re-runs idempotently (immunity writes are keyed by `action_id`).
- **Duplicate proposal:** if `decided` already exists on `action:<id>`,
  re-emit the same verdict (a fresh token only if the original expired).
- **Ledger unavailable:** DENY everything with `layer:policy,
  reasons:["audit trail unavailable"]` — no unrecorded approvals.
- **Secret missing:** refuse to start (`health: down`); the Kernel treats
  a Guardian without a secret as a boot failure.
- **Corrigibility:** `system.pause`/`stop` are the first rule; nothing
  can be approved while paused; Guardian cannot be patched, and its
  config file is protected.
- **Floor:** with no model and no Ledger, Guardian denies — the safe
  floor for a safety gate is "no."

## 9. Testing strategy

- Contract tests: all produced types; consumed types with valid/invalid.
- Unit per rule with a table of cases; pipeline ordering test (a later
  allow cannot flip an earlier deny; escalations accumulate); token
  issue/verify round-trip with the contracts HMAC helper; posture
  transitions (tighten paths, `reset_to_baseline` only via resume/config,
  no loosening message exists — assert the catalog has none);
  `guardian.review` subset; human prompt timeout; duplicate proposal
  re-emits verdict.
- Ported v1: `tests/test_audit.py` in full (denylist table, immunity,
  protected subjects, sandbox scoping now living in Verification — the
  Guardian tests assert the *policy*, Verification's assert the *check*),
  breaker tests from `tests/test_autonomy.py`.
- Integration: `test_action_path_forged_token.py` (with Execution),
  `test_flow_5_pause_denies_all.py`, `test_flow_3_plan_mode_read_only.py`,
  `test_trust_posture_locks_after_failures.py`.
- Invariants: for every `action.approved` there is exactly one `decided{
  allow}` on its stream; no `action.approved` exists while
  `system_state != running`; no approved action ever has a protected path.
- Mocks: `FakeClock`, `FakeCognition` for the classifier, scripted
  `ui.prompt.answered`.

## 10. Build steps (an agent picks this up here)

Size: **M/L**. Parallelizable after step 2: rules are independent files.

1. Skeleton, reserved subscription, projections (`TaskModes`,
   `ToolTable`, `BudgetTable`), `charter.py` loading SOUL directives.
   *Accept:* boundary/contract tests; boots with secret; refuses without.
2. `tokens.py` + `pipeline.py` with rules `paused`, `mode`,
   `reversibility` only. *Accept:* S1, S6; token round-trip with Execution's verifier.
3. `protected.py`, `scope.py`, `denylist.py` (port table). *Accept:* S3; ported denylist tests.
4. `immunity.py` + `guardian:rejected`. *Accept:* S4; ported immunity tests.
5. `budget.py` from `cognition.provider.status`. *Accept:* cap denial test.
6. `human.py` (`needs_human` ↔ `ui.prompt`, timeout, fresh token). *Accept:* S2.
7. `classifier.py`. *Accept:* floor → escalate; ALLOW/DENY/ASK parsing.
8. `posture.py` + streak/drift/budget/health triggers; `guardian.posture.changed`. *Accept:* S5; no-loosening invariant.
9. `review.py` (`guardian.review`). *Accept:* Verification's fake passes.
10. v1 adapter: `src/orchestrator/audit.py` `AuditGate.review` delegates
    to `guardian.review` semantics in-process; `tests/test_audit.py` green.
    Docs + EVOLUTION milestone.

## 11. Migration notes

- `AuditGate.review` splits: policy layers (denylist, immunity,
  protected) → Guardian rules; the sandboxed smoke run → Verification's
  `sandbox_smoke` check (skills only, milestone 84). `AuditVerdict` →
  `guardian.review.reply` / `action.denied` shapes.
- `PROTECTED_SUBJECTS` → `protected_subjects` config (extended); the
  constant stays exported from `src/orchestrator/audit.py` as an adapter.
- `_check_adaptive_immunity` → `rules/immunity.py`; `REJECTED_KIND`
  memory records → `guardian:rejected` via `migrate-v1`.
- Circuit breaker (`max_consecutive_failures`, `reset_failure_streak`,
  the "paused itself" notice) → `posture.py`; `autonomous on/off` →
  `system.resume`/`system.pause` scoped to autonomous origins (Interface
  maps the old command names).
- Budget caps (`DEFAULT_CLAUDE_CODE_MAX_CALLS`, daily USD) → Cognition
  config + Guardian's `budget.py` enforcement.
- `soul.py` directive loading → `charter.py` (SOUL.md unchanged).

## 12. Open questions

1. **`guardian.*` domain is missing from `03` §3/§4.** `02` Flow 4 uses
   `guardian.review`; this spec also needs `guardian.posture.changed`.
   *Default:* file a contracts change adding domain `guardian` with
   `guardian.review`/`.reply` and `guardian.posture.changed`.
2. **Per-task scope on `task.created`.** Needed by rule 3; see
   `07-planning.md` Q1. *Default:* optional `scope` field; until it lands,
   derive from `subject`.
3. **Human-origin proposals without a task** (Interface commands like
   `patch`, `!shell`). *Default:* Interface publishes them with
   `proposed_by: "interface"`, `channel: "creator"`, no `task_id`; Guardian
   uses system mode.
4. **Should `trusted` ever be default?** *Default:* no; `trusted` exists
   for a creator who has reviewed enough history to set it in config.
