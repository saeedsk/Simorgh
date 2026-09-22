# guardian -- contract

One-line status: layer 3 · 2,402 lines · 15 test files · lock: `guardian` in docs/modules/locks.toml

## Purpose

Guardian is the approval gate: the only subsystem allowed to subscribe to `action.proposed`, and (with the Kernel) the only one allowed to publish `action.approved`. Every proposed tool call runs through one fixed rule pipeline and ends as exactly one of approved (with an HMAC approval token bound to the action id, tool, argument hash and expiry), denied, or needs a human (a `ui.prompt` whose answer Guardian resolves itself). It also owns the trust posture (tightened by failure streaks, drift, critical health findings and budget pressure; loosened only by a human `system.resume` or a lock's own expiry), adaptive immunity (rejected code and commands remembered on `guardian:rejected`), and the `guardian.review` denylist check Verification asks for. It must never execute anything, never loosen posture on an autonomous message, and never let its own package, the constitution or the machine's secrets be edited by Sim. The shaping decision is structural approval: Execution runs nothing without a token it verifies independently (`execution/verifier.py`), so Guardian's verdict is enforced by the bus topology and the token, not by callers' good behaviour. Since stage 2 item 7 (2026-09-19) the rules judge a proposal by the tool registry Execution announces on `tool.registered` (class, read-only flag, argument schema), not by the proposer's label, and check its arguments against the tool's `input_schema`; its remaining weakness is that protected paths are still checked on the proposal's text, not on the diff that lands (S3).

## Files

| File | For |
|---|---|
| `simorgh/guardian/__init__.py` | re-exports `Service` |
| `simorgh/guardian/api.py` | `Proposal`, `DecisionContext`, `ToolInfo`, `BudgetStatus`, `Decision`, `Verdict`, the `Rule` protocol |
| `simorgh/guardian/charter.py` | reads `docs/SOUL.md` read-only at boot; a placeholder if missing |
| `simorgh/guardian/config.py` | `[guardian]` dataclass, `DEFAULT_PROTECTED_SUBJECTS`, `DEFAULT_DENYLIST`, `[guardian.physical]`, `SIMORGH_GUARDIAN_AUTO_APPROVE` |
| `simorgh/guardian/pipeline.py` | runs the rules in order and folds decisions into one verdict |
| `simorgh/guardian/posture.py` | `Posture`: tighten-only trust level, reset to baseline |
| `simorgh/guardian/registry.py` | `ToolRegistry` (name -> registered class, read-only flag, `input_schema`), `ToolInfo` for a proposal, the enforced part of a schema (`enforced_schema`, `schema_errors`), the schema's file arguments (`schema_subject_keys`) |
| `simorgh/guardian/rules.py` | the fifteen rules, `DEFAULT_PIPELINE`, bandit and shellcheck adapters, path and payload extraction |
| `simorgh/guardian/service.py` | the bus subsystem: decide once per action id, record, mint, escalate, posture triggers, review |
| `simorgh/guardian/tokens.py` | `TokenIssuer` over `contracts.security.approval_token` |
| `simorgh/guardian/README.md` | older narrative notes (pipeline order there predates five rules; this file is current) |

## Consumes

Authority: `Service.consumes` in `service.py:97-110`.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | simorgh/guardian/service.py | the gate: dedupe by action id, record `received`, run the pipeline, record `decided`, publish the verdict (competing consumer, group `guardian`) |
| `guardian.review` | `messages/guardian.py::GuardianReview` | simorgh/guardian/service.py | denylist check over a code blob for Verification; replies `approved`/`reasons` |
| `guardian.posture.request` | `messages/guardian.py::GuardianPostureRequest` | simorgh/guardian/service.py | replies current posture, trust score and tightening reasons |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | simorgh/guardian/service.py | resolves a `needs_human` escalation (`prompt_id` = action id) from the recorded proposal; other prompts ignored |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/guardian/service.py | tracks running/paused/stopping for `PausedRule` |
| `system.resume` | `messages/system.py::SystemResume` | simorgh/guardian/service.py | resets posture to baseline (the human loosening path) |
| `task.created` | `messages/task.py::TaskCreated` | simorgh/guardian/service.py | remembers each task's `mode` and `origin` for the rules |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/guardian/service.py | resets an autonomous origin's failure streak on success |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/guardian/service.py | counts an autonomous origin's failure streak; at `max_consecutive_failures` tightens to locked |
| `reflect.drift.detected` | `messages/reflect.py::ReflectDriftDetected` | simorgh/guardian/service.py | tightens to guarded |
| `reflect.health.finding` | `messages/reflect.py::ReflectHealthFinding` | simorgh/guardian/service.py | `severity=critical` tightens to `health_critical_tightens_to` |
| `cognition.provider.status` | `messages/cognition.py::CognitionProviderStatus` | simorgh/guardian/service.py | records budget fraction per provider; at `budget_pressure_tighten_at` tightens to guarded |
| `tool.registered` | `messages/tool.py::ToolRegistered` | simorgh/guardian/service.py | keeps `{input_schema, reversibility, read_only}` per tool in `registry.ToolRegistry`; subscribed first in `start` (Guardian and Execution boot concurrently in one layer) and backed by a replay of `execution:tools` |

The generated draft also listed `guardian.posture.reply` and `ui.prompt` here; Guardian only publishes those.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.approved` | `messages/action.py::ActionApproved` | simorgh/guardian/service.py | pipeline approved, or a human answered yes while the system is not paused; carries token, `args_sha256`, `expires_at` |
| `action.denied` | `messages/action.py::ActionDenied` | simorgh/guardian/service.py | a rule denied, the proposal could not be recorded, an action id was reused for a different call, or a human said no |
| `action.needs_human` | `messages/action.py::ActionNeedsHuman` | simorgh/guardian/service.py | an escalation survived the pipeline; carries the question with the arguments shown (secrets hidden) |
| `ui.prompt` | `messages/ui.py::UiPrompt` | simorgh/guardian/service.py | with every `action.needs_human`, `prompt_id` = action id, default `no`, `timeout_s` = `human_prompt_timeout_s` |
| `guardian.posture.changed` | `messages/guardian.py::GuardianPostureChanged` | simorgh/guardian/service.py | the posture level actually moved (tighten, lock expiry, resume) |
| `guardian.posture.reply` | `messages/guardian.py::GuardianPostureReply` | simorgh/guardian/service.py | reply to `guardian.posture.request` |
| `guardian.review.reply` | `messages/guardian.py::GuardianReviewReply` | simorgh/guardian/service.py | reply to every `guardian.review` |

Wire deny layers (`service.py::_wire_layer`): `mode`, `protected`, `reversibility`, and every layer `action.denied`'s `DENY_LAYER` does not name (`schema`, `static_analysis`, `shellcheck`, `package`, `grant`, `human_only`, `physical`) are sent as `policy`; `paused`, `denylist`, `immunity`, `budget`, `scope`, `classifier` pass through. The rule that fired is in `reasons` and on the `decided` record. Until 2026-09-19 only the first three were mapped, so a denial at any of the others failed the bus's contract validation on publish and reached nobody.

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `action:<action_id>` | simorgh/guardian/service.py | simorgh/execution/service.py (reads `received` args, appends `verified`), simorgh/execution/verifier.py, simorgh/verification, simorgh/voice/service.py, simorgh/interface | `action:` 30d |
| `guardian:rejected` | simorgh/guardian/service.py:27 | read back by Guardian at boot (`_rebuild_rejected_index`) | forever |
| `guardian:trust` | simorgh/guardian/service.py:28 | replayed by Guardian at start (`_restore_posture`) | forever |
| `execution:tools` | simorgh/execution/service.py (writer) | read by Guardian at start (`_replay_tool_registrations`, `service.py::TOOLS_STREAM`); also orchestration and interface | 30d |

Events Guardian writes on `action:<id>`: `received` (the proposal, oversize string args spilled to blobs), `decided` (kind, layer, notes), `duplicate`, `answered`.

## Config

`[guardian]` in simorgh.toml; dataclass in `simorgh/guardian/config.py`. The Kernel builds it, not the Service: `kernel/service.py:202-218` reads the section and sets `irreversible_requires_human = False` unless the file says otherwise (S1); `SIMORGH_GUARDIAN_AUTO_APPROVE` overrides that one field. `[guardian.physical]` maps `auto_approve`, `tool_prefixes`, `observe_tools`, `always_human_tools` to the `physical_*` fields and is not reached by the environment variable.

| Key | Default | Read in the package |
|---|---|---|
| `mode` | `'guarded'` | yes |
| `baseline_posture` | `'guarded'` | yes |
| `approval_ttl_s` | `120.0` | yes |
| `protected_subjects` | `DEFAULT_PROTECTED_SUBJECTS` | yes |
| `denylist` | `field(default_factory=lambda: dict(DEFAULT_DENYLIST))` | yes |
| `immunity_similarity_threshold` | `0.85` | yes |
| `max_consecutive_failures` | `15` | yes |
| `health_critical_tightens_to` | `'guarded'` | yes |
| `lock_ttl_s` | `600.0` | yes |
| `budget_pressure_tighten_at` | `0.9` | yes |
| `irreversible_requires_human` | `True` | yes |
| `reversible_auto_in_guarded` | `True` | NO (declared, never read) |
| `physical_auto_approve` | `False` | yes |
| `physical_tool_prefixes` | `('cam_', 'ring_', 'cast_', 'tv_', 'home_', 'media_', 'music_` | yes |
| `physical_observe_tools` | `('cam_list', 'cam_state', 'cam_snapshot', 'cam_recordings', ` | yes |
| `human_only_tools` | `('apply_skill',)` | yes |
| `physical_always_human_tools` | `('cam_siren', 'ring_siren', 'cam_setup', 'ring_setup', 'cast` | yes |
| `classifier_enabled` | `False` | yes |
| `classifier_timeout_s` | `3.0` | NO (declared, never read) |
| `human_prompt_timeout_s` | `1800.0` | yes |
| `autonomous_origins` | `('curiosity', 'reflection', 'research', 'project', 'assistan` | yes |
| `static_analysis_enabled` | `True` | yes |
| `static_analysis_min_severity` | `'HIGH'` | yes |
| `static_analysis_timeout_s` | `20.0` | yes |
| `shellcheck_enabled` | `True` | yes |
| `shellcheck_timeout_s` | `10.0` | yes |
| `package_denylist` | `('(?i)^sudo', '(?i)^pip$', '(?i)^setuptools$')` | yes |
| `grant_import_denylist` | `('os', 'sys', 'subprocess', 'shutil', 'socket', 'ctypes', 'i` | yes |

`reversible_auto_in_guarded` and `classifier_timeout_s` are listed in `kernel/configcheck.py:126` `KNOWN_DEAD_FIELDS`. `classifier_enabled` is read, but the Service never supplies `DecisionContext.classify`, so the classifier branch never runs.

## Public Python surface

- `simorgh.guardian.Service` (name `guardian`, version `0.1.0`), `Service(config=..., pipeline=...)`: constructed by `kernel/registry.py:145` with the Kernel-built config; refuses to start without the `__hmac__` secret in the Context.
- `simorgh.guardian.config.Config`: imported by `kernel/service.py:44, 491` and `kernel/configcheck.py:217`.
- `approval_question` in `service.py` (module function; tests only).
- Nothing Guardian owns is in `simorgh/contracts`; the token format is `contracts/security.py`, the physical class is `contracts/home/policy.py::classify_call`.
- Module-level mutable state: `rules._bandit_cache` (dict, bounded to 256 entries, process-wide, keyed by code text). Per-instance state lost at restart: `_decided` (action-id dedupe, up to 50,000), `_tasks`, budgets, failure streaks.

## Invariants

Every `guardian.decide` span carries `tier` and `tier_why` alongside `tool`, `mode`, `verdict` and `layer` (stage 6 item 5). Recorded, not re-derived: answering "how many tier-3 actions ran without a human" from a log that stores only the tool means recomputing each tier from today's `contracts/tiers.py` and hoping the table has not moved since, which is not a record of what happened (2026-09-20). The service calls the same `tier_of` the gate does, so the tier a decision records and the tier a rule enforces cannot drift apart.

A proposal with no requester on the `initiative` channel is Sim's OWN idea and has the role `sim` (ceiling 1): ordinary things it does unprompted pass, and anything above that ESCALATES to a person rather than being denied. It used to read as `unknown` -- "a voice I cannot place" -- so every unprompted tier-3 idea died with a warning in the middle of the creator's conversation, and nothing Sim proposed about people could ever reach the person who would say yes (2026-09-20). An unplaced VOICE is still denied; that rule is untouched and has its own test.

The pipeline, in order (`rules.py::DEFAULT_PIPELINE`): `PausedRule` (deny when paused or stopping) -> `SchemaRule` (deny when the arguments fail the registered tool's `input_schema` as `registry.enforced_schema` enforces it; abstains, with a note, for a tool with no registered schema) -> `ModeRule` (observe denies all; locked denies non-read-only; plan-mode tasks read only; read-only here means registered `read_only` AND class `read_only`) -> `ProtectedRule` (deny any write-like subject or code payload naming a protected subject; the subject is read from the schema's file arguments plus `subject`/`path`) -> `ScopeRule` (always abstains today) -> `DenylistRule` (regexes over the `code`/`command` payload, only the changed lines for an existing file) -> `StaticAnalysisRule` (bandit at `static_analysis_min_severity`, abstains if bandit is absent) -> `ShellcheckRule` (abstains if absent) -> `PackageRule` (`install_package` spec must be a plain name) -> `GrantRule` (`grant_capability` never over `os`/`subprocess`/...; MCP launch commands allow-listed) -> `ImmunityRule` (deny at `immunity_similarity_threshold` similarity to a remembered rejection) -> `BudgetRule` (model-costing tools denied when a provider is at its cap) -> `HumanOnlyRule` (tools in `human_only_tools` escalate in every posture, denied when locked) -> `PhysicalRule` (house tools: class recomputed from arguments; `human` class escalates in every posture unless `[guardian.physical] auto_approve`; denied when locked) -> `ReversibilityRule` (on `ToolInfo.reversibility`, not the proposal's label; read-only and reversible allow; irreversible allows in trusted, denies in locked, escalates in guarded only when `irreversible_requires_human`).

Protected subjects (`config.py:21-51`), matched case-folded as substrings of the raw and normalised path: `docs/SOUL.md`, `simorgh/guardian/`, `simorgh/execution/`, `simorgh/contracts/`, `simorgh/kernel/`, `simorgh.toml`, `simloader.py`, `sim.sh`, `agents/` (the agent definitions, since 2026-09-19; as a substring it also covers any `.../agents/` path), `.simorgh/secrets.toml`, `.simorgh/vault`, `.simorgh/ledger`, `.git/hooks`, `/.ssh/`, `/.aws/`, `/.gnupg/`.

- A proposal is judged by the tool registry (`registry.ToolRegistry.info_for`), not by itself (S6): `ToolInfo.read_only` is the registered flag and `ToolInfo.reversibility` is the stricter of the registered class and the proposal's claim, so a proposer can tighten a call (orchestration's per-call `home_call` class) but never loosen it. Only a tool nothing has registered falls back to the claim, and the decision's notes say so. A live `tool.registered` always wins over a replayed `execution:tools` record.
- The schema check (`registry.enforced_schema`) enforces that the arguments are an object, that every required argument is present, and that no argument is a list or object where a scalar is declared (a list-valued `path` would otherwise slip past `ProtectedRule`, which reads strings). It tolerates what today's callers send and the tools accept: extra arguments, a scalar written as text (`CAST_VOLUME: 35` -> `{"level": "35"}`) or a number where text is declared, text where a list is declared, null, any enum/const value; and for a tool with a marker shape (`contracts/toolargs.py`) only the required arguments that shape always supplies (`CAM_PTZ: front left` has no `command`, and the tool reads it from the text). A schema Guardian cannot read is a note, not a denial.
- The rules' file arguments come from the registered schema (`registry.schema_subject_keys`: string or list-of-string properties named `subject`, `path`, `file_path`, `target`, `destination`, ... or ending `_path`/`_file`/`_dir`); `_SUBJECT_ARG_KEYS` (`subject`, `path`) is the fallback for an unregistered tool and is also always checked by `ProtectedRule`. An http(s) URL with no `..` segment is not read as a path (the creator's repository URL contains `simorgh/kernel/`).
- Only `guardian` may subscribe to `action.proposed` (`contracts/topics.py` SUBSCRIBE_ONLY_BY). Only `guardian` or `kernel` may publish `action.approved`; only `guardian` or `execution` may publish `action.denied`, and Execution only with `layer="token"` (PUBLISH_ONLY_BY, PUBLISH_PAYLOAD_CONSTRAINTS).
- The first deny wins and stops the pipeline; an escalate is kept while later rules still run; no deny and no escalate is approval (`pipeline.py`).
- Each action id is decided once: an identical redelivery is recorded as `duplicate` and not answered again; the same id with a different tool or arguments is denied.
- A proposal Guardian cannot record on `action:<id>` is denied, never approved.
- A token is minted only for an approval, over the exact `(action_id, tool, canonical args hash, expires_at)`, with `approval_ttl_s` lifetime.
- A physical tool's class never comes from the proposer's label; a mislabelled `lock.unlock` reaches a person in every posture, and `SIMORGH_GUARDIAN_AUTO_APPROVE` does not reach the house.
- `apply_skill` (default `human_only_tools`) always asks a person, trusted posture and the Kernel's auto-approve included.
- The growth loop cannot loosen its own gate (stage 8 item 5): `rules/`, `agents/` and `simorgh/evals/` are protected subjects, so a policy adoption that would rewrite the rules an agent body is rendered from, the agent definitions, or the suite that judges whether the policy helped is denied at `protected`. `simorgh_skills/` is deliberately NOT protected -- `apply_skill` is human-only, so a skill already reaches a person, and protecting the directory would turn that ask into a flat denial and remove a capability Sim has today.
- Posture only tightens on messages; it loosens only on `system.resume` or when a `locked` posture's `lock_ttl_s` expires. Every tighten is recorded on `guardian:trust`, even when the level does not change.
- A denial at layer `protected`, `denylist` or `immunity` is remembered on `guardian:rejected` (the joined `code` and `command` payload, first 4,096 chars) and reloaded at boot.
- A human's `yes` is refused while the system is paused or stopping; a second answer to the same prompt is ignored.
- The approval question names the tool and its arguments, hides values of secret-looking argument names, and never exceeds 400 characters.
- `guardian.review` with no readable code answers `approved: false`.

The action path end to end (Guardian, token, Execution's verifier) is pinned outside this package, in the Kernel-booting integration tier rather than this contract tier: `tests/simorgh/integration/test_guardian_execution_action_path.py`, `tests/simorgh/integration/test_guardian_decides_once_per_action.py`, `tests/simorgh/integration/test_guardian_down_autopauses.py`, `tests/simorgh/integration/test_guardian_posture_request.py`, `tests/simorgh/integration/test_approval_verifier_adversarial.py`, `tests/simorgh/bus/test_enforcement.py`.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract guardian`.

- `tests/simorgh/guardian/test_rules.py` -- each rule's decision table in isolation.
- `tests/simorgh/guardian/test_pipeline.py` -- deny short-circuits, escalate is kept, classifier handling, default approval.
- `tests/simorgh/guardian/test_physical_rule.py` -- the drill against the real `DEFAULT_PIPELINE`: a mislabelled unlock reaches a person, a light does not, the auto-approve env var does not reach the house.
- `tests/simorgh/guardian/test_code_payload_paths.py` -- a protected file cannot be written through a program or shell payload.
- `tests/simorgh/guardian/test_typed_tool_args.py` -- the registration beats the claim, a missing required argument is denied at `schema`, today's marker shapes still pass, a protected path under a schema-known key is caught, every layer is publishable.
- `tests/simorgh/guardian/test_posture.py` -- posture only tightens; reset returns to baseline.
- `tests/simorgh/guardian/test_tokens.py` -- minted tokens verify with `contracts.security`, as Execution checks them.
- `tests/simorgh/guardian/test_review.py` -- `guardian.review` is answered with the denylist verdict.
- `tests/simorgh/guardian/test_immunity_remembers_commands.py` -- a denied shell command is remembered and a reworded retry matches.

## Known issues (2026-09-18 evaluation)

- S1 -- the live default auto-approved every irreversible action, the house included. **Fixed 2026-09-18 for the house** (`8916e82`: `PhysicalRule`, `[guardian.physical]`); the Kernel's code-path default `irreversible_requires_human = False` stays by design.
- S2 -- the vault, the ledger, `.git/hooks` and credentials were outside the protected list. **Fixed 2026-09-18** (`19f69ce`); `tests/` is still writable by patch tasks.
- S3 -- protected paths are enforced on the proposal's text, not on the diff that lands; `worktree_land` never re-checks. Open; stage 2 item 7 (typed args) and a landing-time check.
- S4 -- skills were `reversible` and auto-approved. **Fixed 2026-09-18** (`8fb3d21`: `HumanOnlyRule`); scanning a skill call's arguments is not done.
- S6 / T1 / T10 -- Guardian trusted the proposer's reversibility label and derived `read_only` from it. **Fixed 2026-09-19** (stage 2 item 7): `ToolInfo` comes from `tool.registered`. Open edge: Execution's `execution:tools` records carry no `input_schema`, so a tool announced before Guardian subscribed (possible: both boot in one layer) or loaded lazily after approval (a skill) has its class checked but not its arguments.
- S7 -- the HMAC token is ceremony within one process. Keep.
- S8 -- physical tools gated like code. **Partly fixed 2026-09-18** (`8916e82`); tiers 0-3 are stage 6 item 5.
- S9 -- immunity never learned from shell rejections. **Fixed 2026-09-18** (`8fb3d21`).
- S11 -- the hand-maintained denylist is doing boundary work it cannot do. Open; stage 6 tiers make it a hint.
- S13 -- `sim_command` lets the model run CLI verbs Guardian sees only as a wrapper. Open (interface).
- T4 / W3 -- Ring WebRTC keepalives were 85% of Guardian decisions. Open; stage 1 item 6 moves signalling off the approval path.
- T5 -- the reversibility taxonomy never changed a verdict (0 escalations). Addressed with S1 for the house.
- L4 -- one tool call is ~13 bus messages and ~20 appends, including Guardian's `received`/`decided` pair. Open; stage 1.
- B10 -- Guardian going down never paused the system. **Fixed 2026-09-18** in the Kernel (`3beb2a5`).
- Found while writing this, fixed 2026-09-19 (commit eff2620): posture was not replayed from `guardian:trust` at start, so a restart (which Execution may request) returned a locked or guarded posture to baseline; start now replays it and re-arms a lock's expiry. And a classifier's `ALLOW` would have settled `HumanOnlyRule` and `PhysicalRule` escalations; those layers are exempt (`pipeline.py::_PERSON_ONLY_LAYERS`). Pinned in `test_posture_survives_a_restart.py`.

## Planned changes (roadmap)

- Stage 1 item 4: Guardian's decide step becomes a span with `rule`, `tier`, `posture` attributes. Stage 1 item 6 (execution/interface) takes Ring signalling off the approval path.
- Stage 2 item 7: done 2026-09-19 (see Invariants). `ScopeRule` still abstains: there is no task scope to compare against until Planning sends one.
- Stage 6 item 5 in part, done 2026-09-19: `guardian/tiers.py`. Every proposal has a tier: 0 reads, 1 reversible, 2 irreversible but local, 3 reaches outside the house (`REACHES_OUTSIDE`, a physical `human` class, or an irreversible tool that uses the network). `TierRule` escalates tier 3 in every posture, `trusted` included, and denies it when locked. `PersonRule` weighs the requester's role (`role_of`: the console is the owner's, a household child is `child`, an unplaced voice is `unknown`) against `CEILING`: above it a child or guest escalates to an adult and an unknown voice is denied. `action.proposed` carries `requester` and `requester_channel`, filled by the session from the speaker. Not done: the permission matrix per person (it needs stage 6 item 4's People store) and recording the tier on every decision as a span attribute.
- Stage 4 item 7: `agents/` joins the protected subjects. Done 2026-09-19.
- Stage 6 items 4-5, 2026-09-22: `PersonRule` takes the requester's role from World Model's People store first (`DecisionContext.role`, asked as `world.env.query{what: people, args: {name}}` with a 0.5 s timeout), and from `role_of`/`contracts/household.py` only when the store has no record of them or does not answer. A role set with `people set_role` -- a tier-3 action a person confirms -- changed nothing Guardian decided until then. A stored `unknown` is refused like an unplaced voice.
- Stage 6 item 5, `PresenceRule` done 2026-09-20: a tier-3 action asked for **by voice** is denied unless World Model places the requester in the house with belief >= `PRESENT_ENOUGH` (0.8) AND the voice was speaker-verified; the refusal says to answer from the phone instead. A television, a phone on speaker, a recording and a guest in the hallway can all say "yes, unlock the door", so the words are not the evidence. Presence is asked of `world.env.query` through `DecisionContext.presence` with a 0.5 s timeout, and every way of not knowing -- no answer, a raised error, an `unknown` area, no presence source at all -- is "not here". Guardian keeps no presence of its own.
- Stage 6 item 5: `guardian/tiers.py`, tiers 0-3 from the ToolSpec plus overrides; `PhysicalRule` folds into the tier computation; `PersonRule` (requester's role) and `PresenceRule` (a voice approval needs the approver present and speaker-verified).
- Stage 8: policy adoption lands through `action.proposed(policy_adopt)`; `rules/`, `simorgh_skills/`, `agents/`, hooks and evals config become protected.
- Stage 9 item 7: Home Assistant automations and scenes as tier-3 tools.

## Working on this module

Lock it first (`python tools/modlock.py claim guardian --by <you> --task "..."`), commit the lock, edit only `simorgh/guardian/`, `tests/simorgh/guardian/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py guardian` before committing; commit subject `guardian: <what changed>`.

This package is Guardian-protected: Sim's own tasks cannot edit it. A human-run agent may, with the lock, because a person is accountable for the commit.

- Telemetry (stage 1 item 4, 2026-09-19): each decision is a span `guardian.decide` (attrs `tool`, `mode`, `verdict`, `layer`), parented to the `action.proposed` message. Recording never affects the verdict.
