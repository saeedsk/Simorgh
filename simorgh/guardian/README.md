# `simorgh/guardian/`

The only subsystem the Bus/Kernel enforcement (`simorgh/bus/enforcement.py`'s
`ReservedTopologyPolicy`) lets subscribe to `action.proposed`. Runs every
proposal through a fixed-order pipeline (`rules.DEFAULT_PIPELINE`, driven by
`pipeline.Pipeline`) and either mints a real HMAC approval token
(`tokens.TokenIssuer`, backed by `simorgh.contracts.security`) or emits
`action.denied`/`action.needs_human`. See
`docs/blueprint/subsystems/09-guardian.md` for the full spec.

## Pipeline order

`paused → mode → protected → scope → denylist → immunity → budget →
reversibility` (`rules.py`). Deny always wins and short-circuits the rest
(`pipeline.Pipeline.decide`); an escalate is remembered but evaluation
continues, since a later rule may still deny outright.

## What's built this pass

- `PausedRule`, `ModeRule`, `ProtectedRule` (ported v1 `PROTECTED_SUBJECTS`),
  `DenylistRule` (ported v1 `_DENYLIST_PATTERNS`), `ImmunityRule`
  (`difflib.SequenceMatcher` against the `guardian:rejected` Ledger stream),
  `BudgetRule`, `ReversibilityRule`.
- `posture.Posture`: trust posture that only ever tightens by message
  (`guardian:trust` stream) or resets to baseline -- there is deliberately
  no message type that loosens it (harness-06). As of Phase 4 Wave 2 all
  four tightening triggers from section 5.3 are wired in `Service`:
  failure streak (`task.completed`/`task.failed` among `autonomous_
  origins`), `reflect.drift.detected` -> guarded, budget pressure at or
  above `budget_pressure_tighten_at` (`cognition.provider.status`) ->
  guarded, and `reflect.health.finding{severity:critical}` -> locked.
  `system.resume` resets to `baseline_posture` (the one human-only
  loosening path; `SYSTEM_RESUME`'s publisher allow-list restricts it to
  interface/kernel, never an autonomous subsystem).
- `charter.load_charter`: reads `docs/SOUL.md` read-only at boot; a missing
  file degrades to a placeholder string rather than blocking start, since
  the real boundaries live in `Config.protected_subjects`/`denylist`, not
  parsed prose.

## Deliberate scope cuts (see 09-guardian.md section 12 for the full list)

- `ScopeRule` always abstains -- a real task-vs-proposal scope comparison
  needs Planning's `task.created.scope`, which doesn't exist yet this phase.
  `ProtectedRule` and Execution's own tool-level path-safety checks remain
  the real enforcement in the meantime.
- `BudgetRule` abstains whenever no `cognition.provider.status` has ever
  arrived (`ctx.budgets` empty) -- "no data" must not be treated as
  "exhausted." As of Phase 4 Wave 2, `Service` subscribes to
  `cognition.provider.status` and populates `ctx.budgets` for real (was
  previously always empty -- `BudgetRule` abstained on every proposal
  regardless of actual spend); the same handler also feeds the trust
  posture's budget-pressure tightening trigger (section 5.3).
- `classifier_enabled=False` by default: Cognition doesn't exist yet, so
  every escalation falls through to `action.needs_human` rather than being
  auto-resolved. `pipeline.Pipeline.decide`'s `ctx.classify` hook is real
  and wired, just unused until a classifier subsystem is registered.
- `action.needs_human` is emitted but there's no `ui.prompt` round-trip
  listener yet (Interface doesn't exist this phase).

## A genuine spec/contract naming gap

`action.denied`'s wire schema (`contracts/messages/action.py`'s
`DENY_LAYER` enum) only allows `{policy, denylist, immunity, budget,
paused, scope, classifier, token}` -- narrower than 09-guardian.md
section 5.1's own pseudocode, which names `mode`, `protected`, and
`reversibility` as distinct layers. `service.py`'s `_WIRE_DENY_LAYER`
collapses those three to `policy` on the wire (the specific rule that
fired is still visible in `reasons`); not resolved by editing the shared
contract unilaterally.
